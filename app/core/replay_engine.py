"""
ReplayEngine v0.6 — Motor de reprodução controlável de histórico.

Responsabilidades:
- Carregar eventos de uma sessão do Storage (pings, alerts, stats)
- Executar o replay em QThread separada (nunca trava a UI)
- Expor API de controle: load_session, play, pause, stop, seek, set_speed
- Emitir sinais tipados por evento para que a UI reaja identicamente ao LIVE

NÃO deve:
- Conhecer widgets Qt
- Modificar estado de sessão LIVE
- Bloquear a main thread
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from app.infra.storage import Storage


# ─────────────────────────────────────────────────────────────────────────────
# Tipos de domínio
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ReplayEvent:
    """Evento normalizado representando um acontecimento da sessão histórica."""
    host: str
    timestamp: datetime
    event_type: Literal["ping", "alert", "stats"]
    payload: dict


# ─────────────────────────────────────────────────────────────────────────────
# Worker de reprodução (roda em thread dedicada)
# ─────────────────────────────────────────────────────────────────────────────

class _ReplayWorker(QThread):
    """Thread que lê a lista de eventos e os emite com delays controlados."""

    # Sinais emitidos para o ReplayEngine (que re-emite para a UI)
    event_dispatched = pyqtSignal(ReplayEvent)   # cada evento individual
    progress_changed = pyqtSignal(int, int)       # (current_index, total)
    replay_finished  = pyqtSignal()

    def __init__(self, events: list[ReplayEvent], speed: float = 1.0):
        super().__init__()
        self._events  = events
        self._speed   = max(0.1, speed)
        self._paused  = False
        self._stopped = False
        self._seek_to: int | None = None
        self._cursor  = 0

    # ── Controle público (chamado da main thread) ──────────────────────────

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    def stop(self) -> None:
        self._stopped = True
        self._paused  = False   # desbloqueia o loop de pausa

    def seek(self, index: int) -> None:
        self._seek_to = max(0, min(index, len(self._events) - 1))

    def set_speed(self, speed: float) -> None:
        self._speed = max(0.1, speed)

    # ── Loop principal ─────────────────────────────────────────────────────

    def run(self) -> None:
        total = len(self._events)
        self._cursor = 0

        while self._cursor < total and not self._stopped:
            # Seek externo solicitado
            if self._seek_to is not None:
                self._cursor = self._seek_to
                self._seek_to = None

            # Pausa ativa (polling leve, não spinlock)
            if self._paused:
                self.msleep(50)
                continue

            event = self._events[self._cursor]
            self.event_dispatched.emit(event)
            self.progress_changed.emit(self._cursor, total)
            self._cursor += 1

            # Delay entre eventos baseado na velocidade
            # Clamp mínimo de 50 ms para não inundar a UI em sessões densas
            delay_ms = max(50, int(1000 / self._speed))
            self.msleep(delay_ms)

        if not self._stopped:
            self.progress_changed.emit(total, total)
        self.replay_finished.emit()


# ─────────────────────────────────────────────────────────────────────────────
# ReplayEngine — fachada pública (vive na main thread)
# ─────────────────────────────────────────────────────────────────────────────

class ReplayEngine(QObject):
    """
    Motor de replay de sessão histórica.

    Ciclo de vida:
        engine.load_session(session_id)   # carrega eventos do banco
        engine.play()                     # inicia reprodução em thread
        engine.pause() / engine.resume()
        engine.seek(index)                # pula para posição
        engine.set_speed(2.0)             # 2× velocidade
        engine.stop()                     # encerra a thread
    """

    # Sinais re-emitidos para a UI / PingManager
    ping_replayed   = pyqtSignal(str, object)   # (host, PingResult-like dict)
    alert_replayed  = pyqtSignal(str, object)   # (host, alert dict)
    stats_replayed  = pyqtSignal(str, object)   # (host, stats dict)
    progress_changed = pyqtSignal(int, int)      # (current, total)
    replay_finished  = pyqtSignal()
    state_changed    = pyqtSignal(str)           # "idle"|"playing"|"paused"|"stopped"

    def __init__(self, storage: Storage, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._storage = storage
        self._events:  list[ReplayEvent] = []
        self._worker:  _ReplayWorker | None = None
        self._session_id: str | None = None

    # ── API pública ────────────────────────────────────────────────────────

    def load_session(self, session_id: str, host_filter: str | None = None) -> int:
        """
        Lê e ordena cronologicamente todos os eventos da sessão.
        Retorna o número de eventos carregados.
        Deve ser chamado antes de play().
        """
        if self._worker and self._worker.isRunning():
            self.stop()

        self._session_id = session_id
        self._events = self._build_events(session_id, host_filter)
        self.state_changed.emit("idle")
        return len(self._events)

    def play(self) -> None:
        """Inicia (ou continua após pause) a reprodução dos eventos carregados."""
        if not self._events:
            return

        # Se estiver pausado, apenas resume o worker existente
        if self._worker and self._worker.isRunning():
            self._worker.resume()
            self.state_changed.emit("playing")
            return

        # Inicia novo worker
        self._worker = _ReplayWorker(self._events)
        self._worker.event_dispatched.connect(self._dispatch_event)
        self._worker.progress_changed.connect(self.progress_changed)
        self._worker.replay_finished.connect(self._on_finished)
        self._worker.start()
        self.state_changed.emit("playing")

    def pause(self) -> None:
        if self._worker and self._worker.isRunning():
            self._worker.pause()
            self.state_changed.emit("paused")

    def resume(self) -> None:
        if self._worker and self._worker.isRunning():
            self._worker.resume()
            self.state_changed.emit("playing")

    def stop(self) -> None:
        if self._worker:
            self._worker.stop()
            self._worker.wait()
            self._worker = None
        self.state_changed.emit("stopped")

    def seek(self, index: int) -> None:
        """Salta para o evento na posição index (0-based)."""
        if self._worker and self._worker.isRunning():
            self._worker.seek(index)

    def set_speed(self, speed: float) -> None:
        """Define o multiplicador de velocidade (1.0 = tempo real, 2.0 = 2×)."""
        if self._worker:
            self._worker.set_speed(speed)

    @property
    def total_events(self) -> int:
        return len(self._events)

    @property
    def session_id(self) -> str | None:
        return self._session_id

    # ── Internos ───────────────────────────────────────────────────────────

    def _build_events(
        self, session_id: str, host_filter: str | None
    ) -> list[ReplayEvent]:
        hosts = self._storage.get_session_hosts(session_id)
        if host_filter:
            hosts = [h for h in hosts if h == host_filter]

        events: list[ReplayEvent] = []

        # 1. Pings
        results = self._storage.get_session_results(session_id, host_filter)
        for r in results:
            try:
                ts = datetime.fromisoformat(r["timestamp"])
            except Exception:
                continue
            events.append(ReplayEvent(
                host=r["host"],
                timestamp=ts,
                event_type="ping",
                payload={
                    "latency_ms": r["latency_ms"],
                    "success": bool(r["success"]),
                    "error_msg": r["error_msg"],
                },
            ))

        # 2. Alertas
        for a in self._storage.get_session_alerts(session_id):
            if host_filter and a["host"] != host_filter:
                continue
            try:
                ts = datetime.fromisoformat(a["timestamp"])
            except Exception:
                continue
            events.append(ReplayEvent(
                host=a["host"],
                timestamp=ts,
                event_type="alert",
                payload={
                    "severity": a["severity"],
                    "kind": a["kind"],
                    "message": a["message"],
                },
            ))

        # 3. Stats snapshots
        for s in self._storage.get_session_stats(session_id):
            if host_filter and s["host"] != host_filter:
                continue
            try:
                ts = datetime.fromisoformat(s["timestamp"])
            except Exception:
                continue
            events.append(ReplayEvent(
                host=s["host"],
                timestamp=ts,
                event_type="stats",
                payload={
                    "avg_latency": s.get("avg_latency") or 0.0,
                    "min_latency": s.get("min_latency") or 0.0,
                    "max_latency": s.get("max_latency") or 0.0,
                    "packet_loss": s.get("packet_loss") or 0.0,
                    "std_dev":     s.get("std_dev") or 0.0,
                    "mos":         s.get("mos") or 0.0,
                },
            ))

        events.sort(key=lambda e: e.timestamp)
        return events

    def _dispatch_event(self, event: ReplayEvent) -> None:
        if event.event_type == "ping":
            self.ping_replayed.emit(event.host, event.payload)
        elif event.event_type == "alert":
            self.alert_replayed.emit(event.host, event.payload)
        elif event.event_type == "stats":
            self.stats_replayed.emit(event.host, event.payload)

    def _on_finished(self) -> None:
        self._worker = None
        self.replay_finished.emit()
        self.state_changed.emit("stopped")

    # ── stream_session — alias de compatibilidade com PingManager legado ──

    def stream_session(self, session_id: str):
        """Gerador síncrono (usado pelo PingManager antigo). Não recomendado para UI."""
        for event in self._build_events(session_id, host_filter=None):
            yield event
