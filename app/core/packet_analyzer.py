"""
PacketAnalyzer — Motor de análise e filtragem de pacotes PCAP.

Responsabilidades:
- Manter a lista mestre de PacketRow em memória
- Aplicar filtros combináveis (IP, porta, protocolo, texto)
- Calcular FlowSummary a partir dos pacotes filtrados
- Calcular CaptureSummary (top talkers, top protocolos)
- Gerar relatórios HTML e CSV

Design:
- Puro Python — nenhuma dependência de Qt, Storage ou rede
- Stateless no sentido de filtros: filtros sempre aplicados sobre _all_packets
- Extensível: substituir _all_packets por stream ao vivo sem mudar a UI
"""
from __future__ import annotations

import csv
import io
from collections import Counter, defaultdict
from datetime import datetime

from app.core.models import PacketRow, FlowSummary, CaptureSummary


# ─────────────────────────────────────────────────────────────────────────────
# Filtro de pacotes
# ─────────────────────────────────────────────────────────────────────────────

class PacketFilter:
    """
    Filtro combinável de pacotes.
    Todos os critérios são ANDs — string vazia/None ignora o critério.
    """

    def __init__(
        self,
        ip: str = "",
        port: str = "",
        protocol: str = "",
        text: str = "",
    ):
        self.ip       = ip.strip()
        self.port     = port.strip()
        self.protocol = protocol.strip().upper()
        self.text     = text.strip().lower()

    @property
    def is_empty(self) -> bool:
        return not any([self.ip, self.port, self.protocol, self.text])

    def matches(self, pkt: PacketRow) -> bool:
        if self.ip and self.ip not in (pkt.src_ip, pkt.dst_ip):
            return False
        if self.port:
            try:
                p = int(self.port)
                if p not in (pkt.src_port, pkt.dst_port):
                    return False
            except ValueError:
                pass
        if self.protocol and self.protocol not in pkt.protocol.upper():
            return False
        if self.text and self.text not in pkt.info.lower():
            return False
        return True


# ─────────────────────────────────────────────────────────────────────────────
# Analisador principal
# ─────────────────────────────────────────────────────────────────────────────

class PacketAnalyzer:
    """
    Ponto central de análise de pacotes PCAP.

    Uso típico:
        analyzer = PacketAnalyzer()
        analyzer.add_packets(batch)          # chamado pelo PcapReader via sinal
        packets = analyzer.filter(f)         # retorna lista filtrada
        flows   = analyzer.get_flows(pkts)   # agrega por fluxo
        summary = analyzer.get_summary(pkts) # métricas globais
    """

    def __init__(self) -> None:
        self._all: list[PacketRow] = []

    # ── API pública ────────────────────────────────────────────────────────

    def add_packets(self, batch: list[PacketRow]) -> None:
        """Adiciona um batch de pacotes à lista mestre."""
        self._all.extend(batch)

    def clear(self) -> None:
        """Limpa todos os pacotes (nova captura)."""
        self._all.clear()

    @property
    def all_packets(self) -> list[PacketRow]:
        return self._all

    def filter(self, f: PacketFilter) -> list[PacketRow]:
        """Retorna os pacotes que atendem ao filtro. O(n)."""
        if f.is_empty:
            return list(self._all)
        return [p for p in self._all if f.matches(p)]

    def get_flows(self, packets: list[PacketRow]) -> list[FlowSummary]:
        """
        Agrega pacotes por fluxo bidirecional.
        Retorna lista ordenada por número de pacotes (desc).
        """
        flows: dict[tuple, FlowSummary] = {}
        for pkt in packets:
            key = pkt.flow_key
            if key not in flows:
                flows[key] = FlowSummary(
                    key=key,
                    first_seen=pkt.timestamp,
                    last_seen=pkt.timestamp,
                )
            flow = flows[key]
            flow.packets += 1
            flow.bytes_  += pkt.length
            flow.last_seen = max(flow.last_seen, pkt.timestamp)

        return sorted(flows.values(), key=lambda f: f.packets, reverse=True)

    def get_summary(self, packets: list[PacketRow]) -> CaptureSummary:
        """Computa métricas globais da lista de pacotes."""
        if not packets:
            return CaptureSummary(
                total_packets=0, total_bytes=0,
                top_protocols=[], top_hosts=[],
                flow_count=0, duration_s=0.0,
            )

        proto_count: Counter[str] = Counter()
        host_count:  Counter[str] = Counter()

        for pkt in packets:
            proto_count[pkt.protocol] += 1
            host_count[pkt.src_ip]   += 1
            host_count[pkt.dst_ip]   += 1

        ts_min = min(p.timestamp for p in packets)
        ts_max = max(p.timestamp for p in packets)

        flows = self.get_flows(packets)

        return CaptureSummary(
            total_packets=len(packets),
            total_bytes=sum(p.length for p in packets),
            top_protocols=proto_count.most_common(10),
            top_hosts=host_count.most_common(10),
            flow_count=len(flows),
            duration_s=max(0.0, ts_max - ts_min),
        )

    # ── Exportação ─────────────────────────────────────────────────────────

    def export_html(self, packets: list[PacketRow], filepath: str) -> str:
        """Gera relatório HTML da captura. Retorna o caminho do arquivo."""
        summary  = self.get_summary(packets)
        flows    = self.get_flows(packets)
        date_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>NetPulse PCAP Report</title>
<style>
  body {{ font-family: 'Segoe UI', sans-serif; background: #1e1e2e; color: #cdd6f4; margin: 0; padding: 20px; }}
  .container {{ max-width: 1100px; margin: 0 auto; background: #181825; padding: 24px; border-radius: 10px; }}
  h1 {{ color: #89b4fa; text-align: center; }}
  h2 {{ color: #cba6f7; border-bottom: 1px solid #313244; padding-bottom: 6px; }}
  .cards {{ display: flex; gap: 16px; flex-wrap: wrap; margin: 16px 0; }}
  .card {{ background: #313244; border-radius: 8px; padding: 12px 20px; min-width: 130px; text-align: center; }}
  .card-val {{ font-size: 22px; font-weight: bold; color: #a6e3a1; }}
  .card-lbl {{ font-size: 12px; color: #bac2de; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 12px; }}
  th {{ background: #313244; color: #cdd6f4; padding: 6px; text-align: left; }}
  td {{ padding: 5px 8px; border-bottom: 1px solid #313244; }}
  tr:hover {{ background: #262636; }}
  .footer {{ text-align: center; margin-top: 30px; font-size: 11px; color: #6c7086; }}
</style>
</head>
<body>
<div class="container">
  <h1>NetPulse PCAP Report</h1>
  <p style="text-align:center">Generated: {date_str}</p>

  <div class="cards">
    <div class="card"><div class="card-val">{summary.total_packets}</div><div class="card-lbl">Packets</div></div>
    <div class="card"><div class="card-val">{summary.total_bytes:,}</div><div class="card-lbl">Bytes</div></div>
    <div class="card"><div class="card-val">{summary.flow_count}</div><div class="card-lbl">Flows</div></div>
    <div class="card"><div class="card-val">{summary.duration_s:.1f}s</div><div class="card-lbl">Duration</div></div>
  </div>

  <h2>Top Protocols</h2>
  <table>
    <tr><th>Protocol</th><th>Packets</th><th>% of Total</th></tr>
"""
        for proto, cnt in summary.top_protocols:
            pct = (cnt / summary.total_packets * 100) if summary.total_packets else 0
            html += f"    <tr><td>{proto}</td><td>{cnt}</td><td>{pct:.1f}%</td></tr>\n"

        html += """  </table>
  <h2>Top Hosts</h2>
  <table>
    <tr><th>IP Address</th><th>Packet Count</th></tr>
"""
        for ip, cnt in summary.top_hosts:
            html += f"    <tr><td>{ip}</td><td>{cnt}</td></tr>\n"

        html += """  </table>
  <h2>Top Flows</h2>
  <table>
    <tr><th>Flow</th><th>Packets</th><th>Bytes</th><th>Duration</th></tr>
"""
        for flow in flows[:50]:
            html += f"    <tr><td>{flow.label}</td><td>{flow.packets}</td><td>{flow.bytes_:,}</td><td>{flow.duration_s:.2f}s</td></tr>\n"

        html += """  </table>
  <div class="footer">Generated by NetPulse v0.7 | NOC Edition</div>
</div>
</body>
</html>"""

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(html)
        return filepath

    def export_csv(self, packets: list[PacketRow], filepath: str) -> str:
        """Exporta tabela de pacotes em CSV. Retorna o caminho."""
        with open(filepath, mode="w", newline="", encoding="utf-8") as fout:
            writer = csv.writer(fout, delimiter=";")
            writer.writerow([
                "No.", "Time", "Src IP", "Dst IP",
                "Src Port", "Dst Port", "Protocol", "Length", "Info"
            ])
            for pkt in packets:
                writer.writerow([
                    pkt.index, pkt.ts_str, pkt.src_ip, pkt.dst_ip,
                    pkt.src_port, pkt.dst_port, pkt.protocol,
                    pkt.length, pkt.info,
                ])
        return filepath
