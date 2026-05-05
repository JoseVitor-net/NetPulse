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
    def jitter(self) -> float:
        return self._sum_jitter / self._jitter_count if self._jitter_count > 0 else 0.0

    def add_latency(self, latency: float):
        self.packets_sent += 1
        self.packets_received += 1

        self._sum_latency += latency
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
