from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Literal


@dataclass
class Alert:
    """Diagnóstico gerado pelo NetworkAnalyzer para um host monitorado."""
    host: str
    severity: Literal["INFO", "WARNING", "CRITICAL"]
    kind: Literal["LATENCY_SPIKE", "LATENCY_TREND", "PACKET_LOSS", "ISP_FAILURE"]
    message: str
    timestamp: datetime


@dataclass
class SessionConfig:
    """Configuração de uma sessão de monitoramento. Objeto de transporte puro (DTO)."""
    hosts: list[str]
    count: int
    continuous: bool


@dataclass
class PingResult:
    host: str
    timestamp: datetime
    success: bool
    latency_ms: Optional[float] = None
    error_msg: Optional[str] = None


@dataclass
class PingStats:
    host: str
    packets_sent: int = 0
    packets_received: int = 0

    # Acumuladores O(1) — sem listas crescentes
    _min_latency: float = float('inf')
    _max_latency: float = 0.0
    _sum_latency: float = 0.0
    _m2_latency: float = 0.0

    # Para Jitter cumulativo
    _last_latency: Optional[float] = None
    _sum_jitter: float = 0.0
    _jitter_count: int = 0

    @property
    def packet_loss(self) -> float:
        if self.packets_sent == 0:
            return 0.0
        return ((self.packets_sent - self.packets_received) / self.packets_sent) * 100.0

    @property
    def min_latency(self) -> float:
        return self._min_latency if self._min_latency != float('inf') else 0.0

    @property
    def max_latency(self) -> float:
        return self._max_latency

    @property
    def avg_latency(self) -> float:
        return self._sum_latency / self.packets_received if self.packets_received > 0 else 0.0

    @property
    def std_dev(self) -> float:
        import math
        if self.packets_received < 2:
            return 0.0
        return math.sqrt(self._m2_latency / (self.packets_received - 1))

    @property
    def mos(self) -> float:
        if self.packets_received == 0:
            return 0.0
        eff_latency = self.avg_latency + (2 * self.jitter)
        r = 93.2 - (eff_latency / 40.0)
        r = r - (2.5 * self.packet_loss)
        if r < 0: r = 0.0
        if r > 100: r = 100.0
        mos = 1.0 + (0.035 * r) + (r * (r - 60.0) * (100.0 - r) * 0.000007)
        return max(1.0, min(4.5, mos))

    @property
    def jitter(self) -> float:
        return self._sum_jitter / self._jitter_count if self._jitter_count > 0 else 0.0

    def add_latency(self, latency: float):
        self.packets_sent += 1
        
        # Welford's algorithm (online variance)
        delta = latency - self.avg_latency if self.packets_received > 0 else latency
        
        self.packets_received += 1
        self._sum_latency += latency
        
        delta2 = latency - self.avg_latency
        self._m2_latency += delta * delta2
        if latency < self._min_latency:
            self._min_latency = latency
        if latency > self._max_latency:
            self._max_latency = latency

        if self._last_latency is not None:
            self._sum_jitter += abs(latency - self._last_latency)
            self._jitter_count += 1

        self._last_latency = latency

    def add_failure(self):
        self.packets_sent += 1


# ──────────────────────────────────────────────────────────────
# DTOs de Análise de Pacotes (v0.7)
# ──────────────────────────────────────────────────────────────

@dataclass
class PacketRow:
    """
    Representa uma linha de pacote na tabela da UI.
    Imutável após construção.
    """
    index:      int
    timestamp:  float          # epoch seconds (float)
    src_ip:     str
    dst_ip:     str
    src_port:   int            # 0 se protocolo sem porta (ICMP, etc.)
    dst_port:   int
    protocol:   str            # 'TCP', 'UDP', 'ICMP', 'ARP', 'Other'
    length:     int            # bytes
    info:       str            # descrição resumida

    @property
    def ts_str(self) -> str:
        """Timestamp formatado para exibição."""
        from datetime import datetime
        return datetime.fromtimestamp(self.timestamp).strftime("%H:%M:%S.%f")[:-3]

    @property
    def flow_key(self) -> tuple:
        """Chave de fluxo normalizada (bidirecional)."""
        a = (self.src_ip, self.src_port)
        b = (self.dst_ip, self.dst_port)
        lo, hi = (a, b) if a <= b else (b, a)
        return (lo[0], lo[1], hi[0], hi[1], self.protocol)


@dataclass
class FlowSummary:
    """
    Resumo de um fluxo de rede (conversa bidirecional entre dois endpoints).
    key = (src_ip, src_port, dst_ip, dst_port, protocol)
    """
    key:        tuple
    packets:    int   = 0
    bytes_:     int   = 0
    first_seen: float = 0.0   # epoch
    last_seen:  float = 0.0   # epoch

    @property
    def duration_s(self) -> float:
        return max(0.0, self.last_seen - self.first_seen)

    @property
    def label(self) -> str:
        src_ip, src_port, dst_ip, dst_port, proto = self.key
        return f"{src_ip}:{src_port}  ↔  {dst_ip}:{dst_port}  [{proto}]"


@dataclass
class CaptureSummary:
    """
    Métricas globais de uma captura PCAP.
    """
    total_packets:   int
    total_bytes:     int
    top_protocols:   list[tuple[str, int]]   # [(proto, count), ...] ordenado desc
    top_hosts:       list[tuple[str, int]]   # [(ip, packet_count), ...]
    flow_count:      int
    duration_s:      float
