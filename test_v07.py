"""
test_v07.py — Teste automatizado da v0.7: PCAP Packet Analysis.

Valida:
1. PcapReader parseando pacotes corretamente
2. PacketAnalyzer filtrando e agregando fluxos
3. Exportação de PCAP report
4. Integração das UI tabs
"""
import sys
import os
import time
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer
from app.infra.logger import setup_logger
from app.core.models import PacketRow
from app.core.packet_analyzer import PacketAnalyzer, PacketFilter
from app.infra.pcap_reader import PcapReader
from app.infra.storage import Storage
from app.core.session_manager import SessionManager
from app.core.replay_engine import ReplayEngine
from app.services.ping_manager import PingManager
from app.services.report_service import ReportService
from app.ui.main_window import MainWindow

PASS = "[PASS]"
FAIL = "[FAIL]"

def _create_dummy_pcap():
    # Cria um PCAP mínimo com scapy para teste se não existir
    from scapy.all import IP, TCP, UDP, ICMP, wrpcap
    pkts = [
        IP(src="192.168.1.10", dst="8.8.8.8")/TCP(sport=12345, dport=443),
        IP(src="192.168.1.10", dst="8.8.8.8")/TCP(sport=12345, dport=443),
        IP(src="8.8.8.8", dst="192.168.1.10")/TCP(sport=443, dport=12345),
        IP(src="192.168.1.10", dst="1.1.1.1")/UDP(sport=5353, dport=53),
        IP(src="10.0.0.1", dst="10.0.0.2")/ICMP()
    ]
    filepath = "test_dummy.pcap"
    wrpcap(filepath, pkts)
    return filepath

def run_tests():
    setup_logger()
    app = QApplication(sys.argv)
    
    # ── Teste 1: Packet Analyzer (Core Logic) ──────────────────────────
    analyzer = PacketAnalyzer()
    
    p1 = PacketRow(1, 1000.0, "10.0.0.1", "10.0.0.2", 1234, 80, "TCP", 100, "Info")
    p2 = PacketRow(2, 1000.1, "10.0.0.2", "10.0.0.1", 80, 1234, "TCP", 200, "Info")
    p3 = PacketRow(3, 1000.2, "10.0.0.1", "8.8.8.8", 0, 0, "ICMP", 50, "Info")
    analyzer.add_packets([p1, p2, p3])
    
    f1 = PacketFilter(protocol="TCP")
    res1 = analyzer.filter(f1)
    assert len(res1) == 2, f"Filtro TCP falhou: {len(res1)}"
    print(f"{PASS} PacketAnalyzer: filter(TCP) ok.")
    
    f2 = PacketFilter(ip="10.0.0.2")
    res2 = analyzer.filter(f2)
    assert len(res2) == 2, f"Filtro IP falhou: {len(res2)}"
    print(f"{PASS} PacketAnalyzer: filter(IP) ok.")
    
    flows = analyzer.get_flows([p1, p2, p3])
    assert len(flows) == 2, f"get_flows falhou, esperava 2, obteve {len(flows)}"
    assert flows[0].packets == 2, "Flow TCP deve ter 2 pacotes"
    print(f"{PASS} PacketAnalyzer: get_flows ok.")
    
    summary = analyzer.get_summary([p1, p2, p3])
    assert summary.total_packets == 3
    assert summary.total_bytes == 350
    print(f"{PASS} PacketAnalyzer: get_summary ok.")

    # ── Teste 2: PCAP Reader (Assíncrono) ───────────────────────────────
    pcap_file = _create_dummy_pcap()
    
    class ReaderTest:
        def __init__(self):
            self.total = 0
            self.pkts = []
        def on_ready(self, b):
            self.pkts.extend(b)
        def on_finish(self, t):
            self.total = t
            self.check()
        def check(self):
            assert self.total == 5, f"Expected 5 packets, got {self.total}"
            assert len(self.pkts) == 5
            print(f"{PASS} PcapReader: read {self.total} packets from dummy pcap.")
            
            # Testa Window UI
            self.test_ui()
            
        def test_ui(self):
            storage = Storage()
            sm = SessionManager(storage)
            mgr = PingManager(storage=storage, session_manager=sm)
            rs = ReportService()
            re = ReplayEngine(storage)
            w = MainWindow(manager=mgr, report_service=rs, replay_engine=re)
            
            # Muda pra aba PCAP
            w.tabs.setCurrentIndex(2)
            assert w._mode == "PCAP", w._mode
            print(f"{PASS} MainWindow: mode=PCAP on tab 2.")
            
            # Força injeção de pacotes na UI
            w._analyzer.clear()
            w._on_pcap_packets_ready(self.pkts)
            w._on_pcap_finished(5)
            
            assert w.packet_panel.table.rowCount() == 5
            assert w.flow_panel.flow_table.rowCount() == 3 # 3 flows no dummy
            print(f"{PASS} MainWindow: packet_panel and flow_panel populated.")
            
            # Export
            export_html = "test_export.html"
            w._analyzer.export_html(self.pkts, export_html)
            assert os.path.exists(export_html)
            os.remove(export_html)
            print(f"{PASS} PacketAnalyzer: export_html ok.")
            
            os.remove(pcap_file)
            
            print("=" * 60)
            print("  v0.7 VALIDADA — todos os criterios de aceite passaram.")
            print("=" * 60)
            app.quit()
            
    test_obj = ReaderTest()
    reader = PcapReader(pcap_file)
    reader.packets_ready.connect(test_obj.on_ready)
    reader.finished_ok.connect(test_obj.on_finish)
    reader.start()

    sys.exit(app.exec())


if __name__ == "__main__":
    run_tests()
