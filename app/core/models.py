from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List

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
    latencies: List[float] = field(default_factory=list)

    @property
    def packet_loss(self) -> float:
        if self.packets_sent == 0:
            return 0.0
        return ((self.packets_sent - self.packets_received) / self.packets_sent) * 100.0

    @property
    def min_latency(self) -> float:
        return min(self.latencies) if self.latencies else 0.0

    @property
    def max_latency(self) -> float:
        return max(self.latencies) if self.latencies else 0.0

    @property
    def avg_latency(self) -> float:
        return sum(self.latencies) / len(self.latencies) if self.latencies else 0.0

    @property
    def jitter(self) -> float:
        if len(self.latencies) < 2:
            return 0.0
        diffs = [abs(self.latencies[i] - self.latencies[i-1]) for i in range(1, len(self.latencies))]
        return sum(diffs) / len(diffs)
    
    def add_latency(self, latency: float):
        self.packets_sent += 1
        self.packets_received += 1
        self.latencies.append(latency)
        
    def add_failure(self):
        self.packets_sent += 1
