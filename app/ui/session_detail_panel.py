"""
SessionDetailPanel — Painel de detalhe de sessão histórica com controles de replay.

Responsabilidades:
- Exibir resumo agregado da sessão (summary cards)
- Controlar o ReplayEngine (Play/Pause/Stop/Velocidade)
- Permitir filtro de host para replay parcial
- Emitir export_requested(session_id) para geração de relatórios
- NÃO acessa Storage ou PingManager diretamente
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QGroupBox,
    QPushButton, QComboBox, QSlider, QProgressBar, QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QFont, QColor

from app.core.replay_engine import ReplayEngine


class SessionDetailPanel(QWidget):
    """
    Painel de detalhe de sessão histórica.

    Sinais:
        replay_play_requested(session_id, host_filter)
        export_requested(session_id)
    """

    replay_play_requested = pyqtSignal(str, str)   # session_id, host_filter ('' = todos)
    export_requested      = pyqtSignal(str)         # session_id

    def __init__(self, replay_engine: ReplayEngine, parent=None):
        super().__init__(parent)
        self._engine = replay_engine
        self._session_id: str | None = None
        self._hosts: list[str] = []
        self._build_ui()
        self._connect_engine_signals()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(8)

        # Título
        title = QLabel("Session Detail")
        title.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        title.setStyleSheet("color: #cba6f7;")
        layout.addWidget(title)

        # ── Summary cards ──────────────────────────────────────────────────
        summary_group = QGroupBox("Aggregated Summary")
        summary_layout = QHBoxLayout(summary_group)

        self._labels: dict[str, QLabel] = {}
        for key, caption in [
            ("hosts",       "Hosts"),
            ("total_pings", "Total Pings"),
            ("total_losses","Losses"),
            ("avg_latency", "Avg (ms)"),
            ("min_latency", "Min (ms)"),
            ("max_latency", "Max (ms)"),
            ("avg_mos",     "MOS"),
            ("alert_count", "Alerts"),
        ]:
            card = self._make_card(caption)
            value_lbl = card.findChild(QLabel, f"val_{key}")
            if value_lbl:
                self._labels[key] = value_lbl
            summary_layout.addWidget(card)

        layout.addWidget(summary_group)

        # ── Replay controls ────────────────────────────────────────────────
        ctrl_group = QGroupBox("Replay Controls")
        ctrl_layout = QVBoxLayout(ctrl_group)

        # Host selector
        host_row = QHBoxLayout()
        host_row.addWidget(QLabel("Host:"))
        self.host_combo = QComboBox()
        self.host_combo.addItem("All hosts", "")
        host_row.addWidget(self.host_combo)
        ctrl_layout.addLayout(host_row)

        # Speed slider
        speed_row = QHBoxLayout()
        speed_row.addWidget(QLabel("Speed:"))
        self.speed_slider = QSlider(Qt.Orientation.Horizontal)
        self.speed_slider.setRange(1, 10)   # 0.5× a 5×
        self.speed_slider.setValue(2)        # 1× default (step × 0.5)
        self.speed_slider.setTickInterval(1)
        self.speed_slider.valueChanged.connect(self._on_speed_changed)
        speed_row.addWidget(self.speed_slider)
        self.speed_label = QLabel("1.0×")
        self.speed_label.setFixedWidth(40)
        speed_row.addWidget(self.speed_label)
        ctrl_layout.addLayout(speed_row)

        # Progress
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setValue(0)
        self.progress_bar.setStyleSheet("""
            QProgressBar { border: 1px solid #313244; border-radius: 4px;
                           background: #181825; color: #cdd6f4; text-align: center; }
            QProgressBar::chunk { background-color: #89b4fa; border-radius: 3px; }
        """)
        ctrl_layout.addWidget(self.progress_bar)

        # Buttons
        btn_row = QHBoxLayout()
        self.btn_play  = QPushButton("▶  Play")
        self.btn_pause = QPushButton("⏸  Pause")
        self.btn_stop  = QPushButton("⏹  Stop")
        self.btn_export= QPushButton("⬇  Export")

        self.btn_play.clicked.connect(self._on_play)
        self.btn_pause.clicked.connect(self._on_pause)
        self.btn_stop.clicked.connect(self._on_stop)
        self.btn_export.clicked.connect(self._on_export)

        self.btn_pause.setEnabled(False)
        self.btn_stop.setEnabled(False)

        for btn in (self.btn_play, self.btn_pause, self.btn_stop, self.btn_export):
            btn_row.addWidget(btn)

        ctrl_layout.addLayout(btn_row)

        # Status label
        self.status_label = QLabel("No session loaded")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet("color: #6c7086; font-size: 12px;")
        ctrl_layout.addWidget(self.status_label)

        layout.addWidget(ctrl_group)
        layout.addStretch()

    # ── API pública ────────────────────────────────────────────────────────

    def load_summary(self, summary: dict) -> None:
        """
        Carrega o resumo da sessão nos cards.
        summary = dict retornado por Storage.get_session_summary()
        """
        self._session_id = summary.get("session_id")
        self._hosts = summary.get("hosts", [])

        # Atualiza cards
        if "hosts" in self._labels:
            self._labels["hosts"].setText(", ".join(self._hosts) or "—")
        for key in ("total_pings", "total_losses", "alert_count"):
            if key in self._labels:
                self._labels[key].setText(str(summary.get(key, "—")))
        for key in ("avg_latency", "min_latency", "max_latency", "avg_mos"):
            if key in self._labels:
                val = summary.get(key, 0.0)
                self._labels[key].setText(f"{val:.2f}")

        # Atualiza host combo
        self.host_combo.clear()
        self.host_combo.addItem("All hosts", "")
        for h in self._hosts:
            self.host_combo.addItem(h, h)

        self.status_label.setText(f"Session: {self._session_id}")
        self.progress_bar.setValue(0)

    # ── Slots de controle ──────────────────────────────────────────────────

    def _on_play(self) -> None:
        if not self._session_id:
            return
        host_filter = self.host_combo.currentData() or ""
        self.replay_play_requested.emit(self._session_id, host_filter)

    def _on_pause(self) -> None:
        self._engine.pause()

    def _on_stop(self) -> None:
        self._engine.stop()

    def _on_export(self) -> None:
        if self._session_id:
            self.export_requested.emit(self._session_id)

    def _on_speed_changed(self, value: int) -> None:
        speed = value * 0.5
        self.speed_label.setText(f"{speed:.1f}×")
        self._engine.set_speed(speed)

    # ── Slots do engine ────────────────────────────────────────────────────

    def _connect_engine_signals(self) -> None:
        self._engine.state_changed.connect(self._on_state_changed)
        self._engine.progress_changed.connect(self._on_progress)
        self._engine.replay_finished.connect(self._on_replay_finished)

    @pyqtSlot(str)
    def _on_state_changed(self, state: str) -> None:
        playing = (state == "playing")
        paused  = (state == "paused")
        idle    = state in ("idle", "stopped")

        self.btn_play.setEnabled(not playing)
        self.btn_pause.setEnabled(playing)
        self.btn_stop.setEnabled(playing or paused)

        state_labels = {
            "playing": "Replaying...",
            "paused":  "Paused",
            "stopped": "Stopped",
            "idle":    "Ready",
        }
        self.status_label.setText(state_labels.get(state, state))

    @pyqtSlot(int, int)
    def _on_progress(self, current: int, total: int) -> None:
        if total > 0:
            self.progress_bar.setMaximum(total)
            self.progress_bar.setValue(current)
            self.progress_bar.setFormat(f"{current}/{total}")

    @pyqtSlot()
    def _on_replay_finished(self) -> None:
        self.status_label.setText("Replay complete")

    # ── Helper de criação de card ──────────────────────────────────────────

    def _make_card(self, caption: str) -> QWidget:
        """Cria um widget card com label de caption e label de valor."""
        key = caption.lower().replace(" ", "_").replace("(", "").replace(")", "")
        card = QWidget()
        card.setStyleSheet("""
            QWidget { background-color: #313244; border-radius: 6px; }
        """)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        vl = QVBoxLayout(card)
        vl.setContentsMargins(8, 6, 8, 6)

        cap_lbl = QLabel(caption)
        cap_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cap_lbl.setStyleSheet("color: #bac2de; font-size: 11px; background: transparent;")
        vl.addWidget(cap_lbl)

        val_lbl = QLabel("—")
        val_lbl.setObjectName(f"val_{key}")
        val_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        val_lbl.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        val_lbl.setStyleSheet("color: #a6e3a1; background: transparent;")
        vl.addWidget(val_lbl)

        return card
