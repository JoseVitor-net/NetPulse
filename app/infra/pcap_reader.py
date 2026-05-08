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
