"""
pcap_reader.py — Leitor assíncrono de arquivos PCAP/PCAPNG.

Responsabilidades:
- Ler arquivos .pcap / .pcapng usando scapy (offline apenas)
- Parsear cada pacote em PacketRow
- Rodar em QThread dedicada para nunca bloquear a UI
- Emitir progresso, batch de pacotes e sinal de conclusão

NÃO deve:
- Conhecer widgets Qt
- Fazer captura ao vivo (escopo v0.7+)
- Conter lógica de filtro ou agregação (responsabilidade do PacketAnalyzer)

Extensibilidade:
- A classe base _BasePcapReader facilita futura implementação de live capture
  em uma subclasse separada sem modificar este arquivo.
"""
from __future__ import annotations

from PyQt6.QtCore import QThread, pyqtSignal, QObject
from loguru import logger

from app.core.models import PacketRow
import time

# Tamanho de batch para emissão — não inundar a UI com 100k eventos
_BATCH_SIZE = 200


class PcapReader(QThread):
    """
    Worker de leitura de arquivo PCAP.

    Sinais:
        packets_ready(list[PacketRow])  — batch de pacotes parseados
        progress(int, int)              — (lidos, total_estimado)
        finished_ok(int)                — total de pacotes lidos
        error_occurred(str)             — mensagem de erro
    """

    packets_ready  = pyqtSignal(list)   # list[PacketRow]
    progress       = pyqtSignal(int, int)
    finished_ok    = pyqtSignal(int)
    error_occurred = pyqtSignal(str)

    def __init__(self, filepath: str, parent: QObject | None = None):
        super().__init__(parent)
        self._filepath = filepath
        self._stopped  = False

    def stop(self) -> None:
        self._stopped = True

    def run(self) -> None:
        try:
            from scapy.utils import PcapReader as ScapyReader
            from scapy.all import IP, IPv6, TCP, UDP, ICMP, ARP

            batch: list[PacketRow] = []
            total_read = 0

            with ScapyReader(self._filepath) as reader:
                for raw_pkt in reader:
                    if self._stopped:
                        break

                    row = _parse_packet(raw_pkt, total_read, IP, IPv6, TCP, UDP, ICMP, ARP)
                    if row:
                        batch.append(row)
                        total_read += 1

                    if len(batch) >= _BATCH_SIZE:
                        self.packets_ready.emit(batch)
                        self.progress.emit(total_read, total_read)
                        batch = []

            if batch:
                self.packets_ready.emit(batch)

            self.progress.emit(total_read, total_read)
            self.finished_ok.emit(total_read)
            logger.info(f"[PcapReader] {total_read} pacotes lidos de {self._filepath}")

        except FileNotFoundError:
            self.error_occurred.emit(f"File not found: {self._filepath}")
        except Exception as e:
            logger.error(f"[PcapReader] Erro ao ler PCAP: {e}")
            self.error_occurred.emit(str(e))


def _parse_packet(pkt, index: int, IP, IPv6, TCP, UDP, ICMP, ARP) -> PacketRow | None:
    """
    Converte um pacote Scapy em PacketRow.
    Retorna None se o pacote não for interpretável.
    """
    try:
        ts = float(pkt.time)
    except Exception:
        ts = 0.0

    length = len(pkt)
    src_ip = dst_ip = ""
    src_port = dst_port = 0
    protocol = "Other"
    info = ""

    try:
        if pkt.haslayer(ARP):
            arp = pkt[ARP]
            src_ip   = arp.psrc or ""
            dst_ip   = arp.pdst or ""
            protocol = "ARP"
            info     = f"Who has {dst_ip}? Tell {src_ip}"

        elif pkt.haslayer(IP):
            ip = pkt[IP]
            src_ip = ip.src
            dst_ip = ip.dst

            if pkt.haslayer(TCP):
                tcp = pkt[TCP]
                src_port = tcp.sport
                dst_port = tcp.dport
                protocol = "TCP"
                flags    = str(tcp.flags)
                info     = f"{src_ip}:{src_port} → {dst_ip}:{dst_port} [{flags}]"

            elif pkt.haslayer(UDP):
                udp = pkt[UDP]
                src_port = udp.sport
                dst_port = udp.dport
                protocol = "UDP"
                info     = f"{src_ip}:{src_port} → {dst_ip}:{dst_port}"

            elif pkt.haslayer(ICMP):
                icmp = pkt[ICMP]
                protocol = "ICMP"
                info     = f"{src_ip} → {dst_ip} type={icmp.type}"

            else:
                protocol = f"IP/{ip.proto}"
                info     = f"{src_ip} → {dst_ip}"

        elif pkt.haslayer(IPv6):
            ip6 = pkt[IPv6]
            src_ip   = ip6.src
            dst_ip   = ip6.dst
            protocol = "IPv6"
            info     = f"{src_ip} → {dst_ip}"

        else:
            protocol = pkt.__class__.__name__
            info     = "Non-IP frame"

    except Exception:
        info = "Parse error"

    if not src_ip and not dst_ip:
        return None

    return PacketRow(
        index=index,
        timestamp=ts,
        src_ip=src_ip,
        dst_ip=dst_ip,
        src_port=src_port,
        dst_port=dst_port,
        protocol=protocol,
        length=length,
        info=info,
    )

class PcapSniffer(QThread):
    """
    Worker de captura ao vivo de PCAP usando scapy.sniff().

    Sinais:
        packet_captured(list[PacketRow]) - emitido em batches para n travar UI
        capture_error(str)
        capture_stopped()
    """

    packet_captured = pyqtSignal(list)
    capture_error = pyqtSignal(str)
    capture_stopped = pyqtSignal()

    def __init__(self, iface: str, bpf_filter: str = "", max_packets: int = 0, parent: QObject | None = None):
        super().__init__(parent)
        self._iface = iface
        self._bpf_filter = bpf_filter
        self._max_packets = max_packets
        self._stopped = False
        self._batch: list[PacketRow] = []
        self._total_read = 0
        self._last_emit = time.time()
        self._scapy_pkts = [] # Para salvar em pcap se pedido

    def stop(self) -> None:
        self._stopped = True

    def get_raw_packets(self):
        """Retorna os pacotes raw capturados (Scapy Packet objects)."""
        return self._scapy_pkts

    def run(self) -> None:
        try:
            from scapy.all import sniff, IP, IPv6, TCP, UDP, ICMP, ARP
            
            def _stop_cb(p):
                return self._stopped

            def _prn(raw_pkt):
                if self._stopped:
                    return

                # Parse the packet
                row = _parse_packet(raw_pkt, self._total_read, IP, IPv6, TCP, UDP, ICMP, ARP)
                if row:
                    self._batch.append(row)
                    self._total_read += 1
                    self._scapy_pkts.append(raw_pkt)

                now = time.time()
                # Emite lote se passou de 50ms ou encheu batch
                if len(self._batch) >= _BATCH_SIZE or (now - self._last_emit) > 0.05:
                    if self._batch:
                        self.packet_captured.emit(list(self._batch))
                        self._batch.clear()
                        self._last_emit = now

            # store=False is critical to avoid memory leak during long captures. We store manually in _scapy_pkts if we want to save.
            sniff(
                iface=self._iface,
                filter=self._bpf_filter,
                count=self._max_packets,
                prn=_prn,
                stop_filter=_stop_cb,
                store=False
            )

            # Emite os ultimos q faltaram
            if self._batch:
                self.packet_captured.emit(list(self._batch))
                self._batch.clear()

            self.capture_stopped.emit()

        except PermissionError:
            self.capture_error.emit("Acesso negado. Por favor, execute o NetPulse como Administrador.")
        except Exception as e:
            if "Npcap" in str(e) or "libpcap" in str(e) or "winpcap" in str(e).lower() or "WinPcap" in str(e):
                self.capture_error.emit("O Npcap não está instalado ou configurado. Instale o Npcap com suporte a compatibilidade para capturar tráfego no Windows.")
            else:
                logger.error(f"[PcapSniffer] Erro ao capturar: {e}")
                self.capture_error.emit(f"Erro ao capturar pacotes: {str(e)}")

    def save(self, filepath: str) -> None:
        try:
            from scapy.all import wrpcap
            wrpcap(filepath, self._scapy_pkts)
        except Exception as e:
            self.capture_error.emit(f"Erro ao salvar arquivo PCAP: {str(e)}")

def get_windows_if_list() -> list[str]:
    """Retorna lista de interfaces. Retorna os nomes amigáveis quando possível."""
    try:
        from scapy.arch.windows import get_windows_if_list as scapy_if_list
        interfaces = scapy_if_list()
        # scapy returns list of dicts on windows: [{'name': '...', 'description': '...', ...}, ...]
        return [iface['name'] for iface in interfaces if 'name' in iface]
    except Exception:
        # Fallback if the scapy function is not available or fails
        try:
            from scapy.all import get_if_list
            return get_if_list()
        except Exception:
            return ["any"]
