"""
ReplayEngine — Motor de reprodução de histórico como fluxo de eventos.

Responsabilidades:
- Isolar a lógica de reconstrução temporal de dados históricos
- Ler pings, stats e alerts do Storage
- Converter linhas do banco em eventos padronizados (ReplayEvent)
- Ordenar cronologicamente e fornecer um stream iterável
- Puro Python: independente de Qt, UI ou rede
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Generator, Literal

from app.infra.storage import Storage


@dataclass
class ReplayEvent:
    """Evento padronizado representando um acontecimento no tempo."""
    host: str
    timestamp: datetime
    event_type: Literal["ping", "alert", "stats"]
    payload: dict


class ReplayEngine:
    """Motor de event sourcing para reprodução de histórico do banco."""

    def __init__(self, storage: Storage):
        self._storage = storage

    def stream_session(self, session_id: str) -> Generator[ReplayEvent, None, None]:
        """
        Busca todos os dados de uma sessão e gera um fluxo ordenado de eventos
        simulando a linha do tempo exata em que ocorreram.
        """
        hosts = self._storage.get_session_hosts(session_id)
        events: list[ReplayEvent] = []

        # 1. Carrega pings
        for host in hosts:
            for p in self._storage.get_session_pings(session_id, host):
                events.append(ReplayEvent(
                    host=host,
                    timestamp=datetime.fromisoformat(p["timestamp"]),
                    event_type="ping",
                    payload={
                        "latency_ms": p["latency_ms"],
                        "success": bool(p["success"]),
                        "error_msg": p["error_msg"]
                    }
                ))

        # 2. Carrega alertas
        for a in self._storage.get_session_alerts(session_id):
            events.append(ReplayEvent(
                host=a["host"],
                timestamp=datetime.fromisoformat(a["timestamp"]),
                event_type="alert",
                payload={
                    "severity": a["severity"],
                    "kind": a["kind"],
                    "message": a["message"]
                }
            ))

        # 3. Carrega stats snapshots
        for s in self._storage.get_session_stats(session_id):
            events.append(ReplayEvent(
                host=s["host"],
                timestamp=datetime.fromisoformat(s["timestamp"]),
                event_type="stats",
                payload={
                    "avg_latency": s["avg_latency"] or 0.0,
                    "min_latency": s["min_latency"] or 0.0,
                    "max_latency": s["max_latency"] or 0.0,
                    "packet_loss": s["packet_loss"] or 0.0,
                    "std_dev": s.get("std_dev", 0.0) or 0.0,
                    "mos": s.get("mos", 0.0) or 0.0,
                }
            ))

        # Ordenação global por timestamp para reconstruir a linha do tempo
        events.sort(key=lambda e: e.timestamp)

        # Yield sequencial do stream
        for event in events:
            yield event
