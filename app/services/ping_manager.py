"""
PingManager — Controlador central de monitoramento multi-host.

Responsabilidades:
- Criar e gerenciar o ciclo de vida dos PingService workers
- Ser a única fonte de verdade do estado (stats_map, threads_map)
- Mediar o fluxo de dados: PingService → PingManager → UI/Dashboard
- Acionar o NetworkAnalyzer e propagar alertas gerados
- Higienizar e validar entradas de host (a UI passa string bruta)
- Persistir dados via Storage (batch — não bloqueia workers)
- Gerenciar sessões via SessionManager

A UI não deve ter conhecimento de PingService, threads, Storage ou sessões.
"""
from datetime import datetime

from PyQt6.QtCore import QObject, pyqtSignal

from app.core.analyzer import NetworkAnalyzer
from app.core.models import Alert, PingResult, PingStats, SessionConfig
from app.core.replay_engine import ReplayEngine
from app.core.session_manager import SessionManager
from app.infra.storage import Storage
from app.services.ping_service import PingService


class PingManager(QObject):
    """Mediador central entre a camada de rede e a camada de apresentação."""

    # Sinais emitidos para os consumidores da UI
    stats_updated = pyqtSignal(str, PingStats, str)  # (host, stats, status) → Tabela
    chart_point_ready = pyqtSignal(str, float)        # (host, latency_ms) → Gráfico
    alert_raised = pyqtSignal(Alert)                  # Alert → AlertPanel
    session_finished = pyqtSignal()                   # Todos os hosts terminaram
    sessions_loaded = pyqtSignal(list)                # list[dict] → UI dropdown

    def __init__(
        self,
        storage: Storage,
        session_manager: SessionManager,
        parent: QObject = None,
    ) -> None:
        super().__init__(parent)
        self._storage = storage
        self._session_manager = session_manager
        self._threads: dict[str, PingService] = {}
        self._stats: dict[str, PingStats] = {}
        self._analyzer = NetworkAnalyzer()
        self._is_running = False

    # ─────────────────────────────────────────────
    # API Pública — Monitoramento
    # ─────────────────────────────────────────────

    @staticmethod
    def parse_hosts(raw: str) -> list[str]:
        """
        Higieniza e deduplica a string de hosts fornecida pelo usuário.
        Responsabilidade de negócio — pertence ao Manager, não à UI.
        """
        hosts = []
        for h in raw.split(","):
            clean = h.strip().replace("http://", "").replace("https://", "").split("/")[0]
            if clean and clean not in hosts:
                hosts.append(clean)
        return hosts

    def start_session(self, config: SessionConfig) -> None:
        """Inicia uma nova sessão de monitoramento a partir de um SessionConfig."""
        self._cleanup()
        self._is_running = True

        # Registra sessão no banco e obtém session_id
        self._session_manager.begin(config.hosts)

        for host in config.hosts:
            self._stats[host] = PingStats(host=host)

            # PingService recebe db=None — persistência agora é responsabilidade do Manager
            worker = PingService(
                host=host,
                count=config.count,
                continuous=config.continuous,
                db=None,
            )
            worker.result_received.connect(self._on_result)
            worker.finished.connect(lambda h=host: self._on_worker_finished(h))

            self._threads[host] = worker
            worker.start()

    def stop_session(self) -> None:
        """Para todos os workers, faz flush do storage e encerra a sessão."""
        self._is_running = False
        for worker in self._threads.values():
            if worker.isRunning():
                worker.stop()
                worker.wait()
        self._storage.flush_all()
        self._session_manager.end()

    def get_all_stats(self) -> dict[str, PingStats]:
        """Retorna o estado atual de todos os hosts (para relatórios)."""
        return dict(self._stats)

    @property
    def is_running(self) -> bool:
        return self._is_running

    # ─────────────────────────────────────────────
    # API Pública — Histórico
    # ─────────────────────────────────────────────

    def request_sessions(self) -> None:
        """
        Busca sessões recentes no banco e emite sessions_loaded para a UI.
        A UI chama isso ao clicar 'Load History' — não acessa Storage diretamente.
        """
        sessions = self._storage.get_sessions()
        self.sessions_loaded.emit(sessions)

    def load_session(self, session_id: str) -> None:
        """
        Carrega dados históricos de uma sessão convertidos em event stream.
        A UI recebe os mesmos sinais na mesma ordem cronológica que ocorreram.
        """
        engine = ReplayEngine(self._storage)
        
        for event in engine.stream_session(session_id):
            if event.event_type == "ping":
                if event.payload["success"] and event.payload["latency_ms"] is not None:
                    self.chart_point_ready.emit(event.host, event.payload["latency_ms"])
                    
            elif event.event_type == "stats":
                fake_stats = _StatsSnapshot(
                    host=event.host,
                    avg=event.payload["avg_latency"],
                    min_val=event.payload["min_latency"],
                    max_val=event.payload["max_latency"],
                    loss=event.payload["packet_loss"],
                    std_dev=event.payload["std_dev"],
                    mos=event.payload["mos"],
                )
                self.stats_updated.emit(event.host, fake_stats, "Historical")
                
            elif event.event_type == "alert":
                alert = Alert(
                    host=event.host,
                    severity=event.payload["severity"],
                    kind=event.payload["kind"],
                    message=event.payload["message"],
                    timestamp=event.timestamp,
                )
                self.alert_raised.emit(alert)

    # ─────────────────────────────────────────────
    # Handlers Internos (privados)
    # ─────────────────────────────────────────────

    def _on_result(self, result: PingResult) -> None:
        """
        Recebe resultado bruto do PingService e:
        1. Atualiza stats do host
        2. Persiste no buffer do Storage (batch — sem I/O bloqueante)
        3. Aciona o motor de análise
        4. Redistribui sinais prontos para a UI
        """
        host = result.host
        if host not in self._stats:
            return

        stats = self._stats[host]

        if result.success and result.latency_ms is not None:
            stats.add_latency(result.latency_ms)
            self.chart_point_ready.emit(host, result.latency_ms)
            status = "Running"
        else:
            stats.add_failure()
            status = result.error_msg or "Failed"

        # Persistência passiva — não bloqueia a thread de rede
        self._storage.buffer_ping(result)

        # Status já calculado — UI recebe dado pronto
        self.stats_updated.emit(host, stats, status)

        # Motor de diagnóstico
        alerts = self._analyzer.feed(host, result)
        for alert in alerts:
            self._storage.save_alert(alert)
            self.alert_raised.emit(alert)

    def _on_worker_finished(self, host: str) -> None:
        """Persiste snapshot final, emite stats e verifica fim de sessão."""
        if host in self._stats:
            stats = self._stats[host]
            # Flush do buffer e snapshot de métricas ao fim do host
            self._storage.flush_host(host)
            self._storage.save_stats_snapshot(stats)
            self.stats_updated.emit(host, stats, "Finished")

        if all(not w.isRunning() for w in self._threads.values()):
            if self._is_running:
                self._is_running = False
                self._storage.flush_all()
                self._session_manager.end()
            self.session_finished.emit()

    def _cleanup(self) -> None:
        """Limpa o estado anterior antes de iniciar nova sessão."""
        self.stop_session()
        self._threads.clear()
        self._stats.clear()
        self._analyzer.reset()


# ─────────────────────────────────────────────────────────────
# DTO interno para emissão de stats históricas
# ─────────────────────────────────────────────────────────────

class _StatsSnapshot(PingStats):
    """
    Subclasse de PingStats que sobrescreve as propriedades com valores pré-calculados
    vindos do banco. Permite reutilizar o sinal stats_updated sem criar nova tipagem Qt.
    """
    def __init__(self, host: str, avg: float, min_val: float, max_val: float, loss: float, std_dev: float, mos: float):
        super().__init__(host=host)
        self._avg = avg
        self._min = min_val
        self._max = max_val
        self._loss = loss
        self._std_dev = std_dev
        self._mos = mos

    @property
    def avg_latency(self) -> float:
        return self._avg

    @property
    def min_latency(self) -> float:
        return self._min

    @property
    def max_latency(self) -> float:
        return self._max

    @property
    def packet_loss(self) -> float:
        return self._loss

    @property
    def std_dev(self) -> float:
        return self._std_dev

    @property
    def mos(self) -> float:
        return self._mos
