"""
MainWindow — Camada de apresentação do NetPulse v0.6.

Responsabilidades EXCLUSIVAS:
- Renderizar a interface gráfica com dois modos: LIVE e REPLAY
- Capturar inputs do usuário e delegar ao PingManager / ReplayEngine
- Reagir aos sinais emitidos por PingManager e ReplayEngine
- Coordenar HistoryPanel e SessionDetailPanel sem expor lógica de negócio

NÃO deve:
- Conhecer PingService ou QThread
- Gerenciar estado de rede (stats_map, threads_map)
- Acessar Storage diretamente
"""
import json

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPlainTextEdit, QPushButton, QComboBox,
    QSpinBox, QGroupBox, QMessageBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QTabWidget, QSplitter
)
from PyQt6.QtCore import Qt, pyqtSlot
from PyQt6.QtGui import QFont, QColor

from app.core.models import Alert, PingStats, SessionConfig
from app.core.replay_engine import ReplayEngine
from app.services.ping_manager import PingManager
from app.services.report_service import ReportService
from app.ui.alert_panel import AlertPanel
from app.ui.dashboard import PyQtGraphDashboard
from app.ui.history_panel import HistoryPanel
from app.ui.session_detail_panel import SessionDetailPanel


# Modo de operação da janela
_MODE_LIVE   = "LIVE"
_MODE_REPLAY = "REPLAY"


class MainWindow(QMainWindow):
    def __init__(
        self,
        manager: PingManager,
        report_service: ReportService,
        replay_engine: ReplayEngine | None = None,
    ):
        super().__init__()
        self.setWindowTitle("NetPulse - NOC Edition")
        self.resize(1280, 860)

        self._manager        = manager
        self._report_service = report_service
        self._replay_engine  = replay_engine or ReplayEngine(manager._storage)
        self._mode           = _MODE_LIVE
        self._host_row: dict[str, int] = {}

        self._setup_ui()
        self._apply_styles()
        self._connect_signals()

    # ─────────────────────────────────────────────
    # Construção da UI
    # ─────────────────────────────────────────────

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setSpacing(6)
        root.setContentsMargins(6, 6, 6, 6)

        # ── Painel esquerdo: histórico ──────────────────────────────────────
        self.history_panel = HistoryPanel()
        self.history_panel.setFixedWidth(360)
        self.history_panel.session_selected.connect(self._on_history_session_selected)
        self.history_panel.filter_requested.connect(self._on_history_filter)

        # Botão rápido para abrir histórico
        root.addWidget(self.history_panel)

        # ── Painel direito: conteúdo principal ─────────────────────────────
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)

        # Header com indicador de modo
        header_row = QHBoxLayout()
        header = QLabel("NetPulse NOC")
        header.setFont(QFont("Segoe UI", 22, QFont.Weight.Bold))
        header.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.mode_badge = QLabel(f"● {_MODE_LIVE}")
        self.mode_badge.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        self.mode_badge.setStyleSheet("color: #a6e3a1;")
        header_row.addWidget(header)
        header_row.addStretch()
        header_row.addWidget(self.mode_badge)
        right_layout.addLayout(header_row)

        # Abas Live / Replay
        self.tabs = QTabWidget()
        self.tabs.currentChanged.connect(self._on_tab_changed)

        # ── Aba Live ────────────────────────────────────────────────────────
        live_tab = QWidget()
        live_layout = QVBoxLayout(live_tab)
        live_layout.setContentsMargins(4, 4, 4, 4)

        # Controls
        controls_group = QGroupBox("Configuration  —  hosts separados por vírgula, espaço ou nova linha")
        controls_layout = QHBoxLayout()

        self.host_input = QPlainTextEdit("8.8.8.8, 1.1.1.1, google.com")
        self.host_input.setPlaceholderText("ex: 8.8.8.8\n1.1.1.1\ncloudflare.com")
        self.host_input.setMaximumHeight(50)

        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["Standard (4)", "Custom Count", "Continuous"])
        self.mode_combo.currentIndexChanged.connect(self._on_mode_change)

        self.count_input = QSpinBox()
        self.count_input.setRange(1, 1000)
        self.count_input.setValue(4)
        self.count_input.setEnabled(False)

        self.btn_start = QPushButton("▶  Start Ping")
        self.btn_start.clicked.connect(self._toggle_live_session)

        self.btn_report = QPushButton("⬇  Export Report")
        self.btn_report.clicked.connect(self._export_live_report)
        self.btn_report.setEnabled(False)

        controls_layout.addWidget(QLabel("Target(s):"))
        controls_layout.addWidget(self.host_input, stretch=1)
        controls_layout.addWidget(QLabel("Mode:"))
        controls_layout.addWidget(self.mode_combo)
        controls_layout.addWidget(self.count_input)
        controls_layout.addWidget(self.btn_start)
        controls_layout.addWidget(self.btn_report)
        controls_group.setLayout(controls_layout)
        live_layout.addWidget(controls_group)

        # Stats Table
        self.table = QTableWidget()
        self.table.setColumnCount(11)
        self.table.setHorizontalHeaderLabels([
            "Host", "Sent", "Recv", "Loss (%)", "Min (ms)", "Max (ms)",
            "Avg (ms)", "Jitter (ms)", "StdDev", "MOS", "Status"
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.setMinimumHeight(140)
        live_layout.addWidget(self.table)

        # Alert panel
        self.alert_panel = AlertPanel()
        live_layout.addWidget(self.alert_panel)

        # Dashboard
        self.dashboard = PyQtGraphDashboard()
        live_layout.addWidget(self.dashboard, stretch=1)

        self.tabs.addTab(live_tab, "  Live Monitoring  ")

        # ── Aba Replay ───────────────────────────────────────────────────────
        replay_tab = QWidget()
        replay_layout = QVBoxLayout(replay_tab)
        replay_layout.setContentsMargins(4, 4, 4, 4)

        self.session_detail = SessionDetailPanel(self._replay_engine)
        self.session_detail.replay_play_requested.connect(self._on_replay_play)
        self.session_detail.export_requested.connect(self._on_replay_export)
        replay_layout.addWidget(self.session_detail)

        # Dashboard de replay (separado do live para não sobrescrever)
        self.replay_dashboard = PyQtGraphDashboard()
        replay_layout.addWidget(self.replay_dashboard, stretch=1)

        # Alert panel de replay
        self.replay_alert_panel = AlertPanel()
        replay_layout.addWidget(self.replay_alert_panel)

        self.tabs.addTab(replay_tab, "  Session Replay  ")

        right_layout.addWidget(self.tabs, stretch=1)
        root.addWidget(right_panel, stretch=1)

    def _apply_styles(self):
        self.setStyleSheet("""
        QMainWindow, QWidget {
            background-color: #1e1e2e; color: #cdd6f4; font-family: 'Segoe UI';
        }
        QTabWidget::pane {
            border: 1px solid #313244; border-radius: 4px;
        }
        QTabBar::tab {
            background: #181825; color: #6c7086; border: 1px solid #313244;
            padding: 6px 16px; border-radius: 4px 4px 0 0; margin-right: 2px;
        }
        QTabBar::tab:selected { background: #313244; color: #cdd6f4; }
        QGroupBox {
            font-weight: bold; border: 1px solid #313244;
            border-radius: 6px; margin-top: 12px; padding-top: 10px;
        }
        QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; color: #89b4fa; }
        QPlainTextEdit, QSpinBox, QComboBox, QLineEdit {
            background-color: #181825; border: 1px solid #313244;
            border-radius: 4px; padding: 5px; color: #cdd6f4;
        }
        QDateEdit {
            background-color: #181825; border: 1px solid #313244;
            border-radius: 4px; padding: 4px; color: #cdd6f4;
        }
        QPushButton {
            background-color: #89b4fa; color: #1e1e2e;
            font-weight: bold; border: none; border-radius: 4px; padding: 8px 16px;
        }
        QPushButton:hover { background-color: #b4befe; }
        QPushButton:disabled { background-color: #45475a; color: #a6adc8; }
        QTableWidget {
            background-color: #181825; gridline-color: #313244;
            border: 1px solid #313244; border-radius: 4px;
        }
        QHeaderView::section {
            background-color: #313244; color: #cdd6f4;
            font-weight: bold; padding: 4px; border: 1px solid #181825;
        }
        QLabel { font-size: 13px; }
        QSlider::groove:horizontal {
            border: 1px solid #313244; height: 6px;
            background: #181825; border-radius: 3px;
        }
        QSlider::handle:horizontal {
            background: #89b4fa; border: 1px solid #45475a;
            width: 14px; margin: -4px 0; border-radius: 7px;
        }
        """)

    # ─────────────────────────────────────────────
    # Conexão de sinais
    # ─────────────────────────────────────────────

    def _connect_signals(self):
        # PingManager → Live UI
        self._manager.stats_updated.connect(self._on_stats_updated)
        self._manager.chart_point_ready.connect(self.dashboard.update_data)
        self._manager.alert_raised.connect(self.alert_panel.add_alert)
        self._manager.session_finished.connect(self._on_session_finished)

        # ReplayEngine → Replay UI
        self._replay_engine.ping_replayed.connect(self._on_replay_ping)
        self._replay_engine.alert_replayed.connect(self._on_replay_alert)
        self._replay_engine.stats_replayed.connect(self._on_replay_stats)
        self._replay_engine.state_changed.connect(self._on_replay_state)

        # Carrega histórico inicial ao abrir
        self._refresh_history()

    # ─────────────────────────────────────────────
    # Handlers — Live Monitoring
    # ─────────────────────────────────────────────

    def _on_mode_change(self, index: int):
        self.count_input.setEnabled(index == 1)

    def _toggle_live_session(self):
        if self._manager.is_running:
            self._manager.stop_session()
            self.btn_start.setText("▶  Start Ping")
            self.btn_report.setEnabled(True)
            self._set_all_status("Stopped")
        else:
            hosts = self._manager.parse_hosts(self.host_input.toPlainText())
            if not hosts:
                QMessageBox.warning(self, "Invalid Input", "Please enter at least one valid host.")
                return
            self._init_table(hosts)
            self.dashboard.reset()
            self.alert_panel.clear()
            self.btn_report.setEnabled(False)
            self.btn_start.setText("⏹  Stop Ping")

            mode_idx = self.mode_combo.currentIndex()
            config = SessionConfig(
                hosts=hosts,
                count=4 if mode_idx == 0 else self.count_input.value(),
                continuous=(mode_idx == 2),
            )
            self._manager.start_session(config)

    @pyqtSlot(str, PingStats, str)
    def _on_stats_updated(self, host: str, stats: PingStats, status: str):
        row = self._host_row.get(host)
        if row is None:
            return
        self._update_table_row(row, host, stats, status)

    @pyqtSlot()
    def _on_session_finished(self):
        self.btn_start.setText("▶  Start Ping")
        self.btn_report.setEnabled(True)
        self._set_all_status("Finished")
        self._refresh_history()   # atualiza lista após sessão completar

    # ─────────────────────────────────────────────
    # Handlers — Histórico / HistoryPanel
    # ─────────────────────────────────────────────

    def _on_tab_changed(self, index: int):
        if index == 1:  # aba Replay
            self._set_mode(_MODE_REPLAY)
        else:
            self._set_mode(_MODE_LIVE)

    def _refresh_history(self, host_filter: str = "", date_from: str = "", date_to: str = ""):
        sessions = self._manager.list_sessions(
            host_filter=host_filter or None,
            date_from=date_from or None,
            date_to=date_to or None,
        )
        self.history_panel.populate(sessions)

    @pyqtSlot(str, str, str)
    def _on_history_filter(self, host_filter: str, date_from: str, date_to: str):
        self._refresh_history(host_filter, date_from, date_to)

    @pyqtSlot(str)
    def _on_history_session_selected(self, session_id: str):
        """Carrega summary e muda para aba Replay."""
        summary = self._manager.get_session_summary(session_id)
        if not summary:
            QMessageBox.warning(self, "Error", f"Could not load session {session_id}")
            return
        self.session_detail.load_summary(summary)
        # Muda para aba de replay automaticamente
        self.tabs.setCurrentIndex(1)

    # ─────────────────────────────────────────────
    # Handlers — ReplayEngine
    # ─────────────────────────────────────────────

    @pyqtSlot(str, str)
    def _on_replay_play(self, session_id: str, host_filter: str):
        """Carrega e inicia replay de uma sessão."""
        if self._manager.is_running:
            QMessageBox.warning(
                self, "LIVE in progress",
                "Stop the live monitoring before starting a replay."
            )
            return

        self.replay_dashboard.reset()
        self.replay_alert_panel.clear()

        count = self._replay_engine.load_session(
            session_id, host_filter=host_filter or None
        )
        if count == 0:
            QMessageBox.information(self, "Empty session", "No events found for this session/host.")
            return

        self._replay_engine.set_speed(self.session_detail.speed_slider.value() * 0.5)
        self._replay_engine.play()

    @pyqtSlot(str)
    def _on_replay_export(self, session_id: str):
        """Exporta relatório a partir de snapshot de dados históricos."""
        summary = self._manager.get_session_summary(session_id)
        if not summary:
            QMessageBox.warning(self, "Error", "Could not load session data for export.")
            return

        # Monta PingStats-like objects a partir do resumo
        from app.core.models import PingStats
        hosts = summary.get("hosts", [])
        stats_list = []
        for host in hosts:
            st = PingStats(host=host)
            # Popula com dados do snapshot histórico
            pings = self._manager._storage.get_session_results(session_id, host)
            for p in pings:
                if p["success"] and p["latency_ms"] is not None:
                    st.add_latency(p["latency_ms"])
                else:
                    st.add_failure()
            stats_list.append(st)

        if not stats_list:
            QMessageBox.warning(self, "No data", "No ping data found for export.")
            return

        html_path = self._report_service.generate_html_report(stats_list)
        csv_path  = self._report_service.generate_csv_report(stats_list)

        if html_path and csv_path:
            QMessageBox.information(
                self, "Reports Generated",
                f"HTML: {html_path}\nCSV:  {csv_path}"
            )
        else:
            QMessageBox.warning(self, "Error", "Failed to generate reports.")

    @pyqtSlot(str, object)
    def _on_replay_ping(self, host: str, payload: dict):
        if payload.get("success") and payload.get("latency_ms") is not None:
            self.replay_dashboard.update_data(host, payload["latency_ms"])

    @pyqtSlot(str, object)
    def _on_replay_alert(self, host: str, payload: dict):
        from app.core.models import Alert
        from datetime import datetime
        alert = Alert(
            host=host,
            severity=payload["severity"],
            kind=payload["kind"],
            message=payload["message"],
            timestamp=datetime.now(),
        )
        self.replay_alert_panel.add_alert(alert)

    @pyqtSlot(str, object)
    def _on_replay_stats(self, host: str, payload: dict):
        # Stats do replay apenas atualizam o painel de detalhes — sem sobrescrever live
        pass

    @pyqtSlot(str)
    def _on_replay_state(self, state: str):
        # O SessionDetailPanel já reage via seus próprios slots ao engine
        pass

    # ─────────────────────────────────────────────
    # Modo LIVE / REPLAY
    # ─────────────────────────────────────────────

    def _set_mode(self, mode: str):
        self._mode = mode
        if mode == _MODE_LIVE:
            self.mode_badge.setText(f"● {_MODE_LIVE}")
            self.mode_badge.setStyleSheet("color: #a6e3a1;")
        else:
            self.mode_badge.setText(f"◈ {_MODE_REPLAY}")
            self.mode_badge.setStyleSheet("color: #cba6f7;")

    # ─────────────────────────────────────────────
    # Export — Relatório LIVE
    # ─────────────────────────────────────────────

    def _export_live_report(self):
        all_stats = self._manager.get_all_stats()
        if not all_stats:
            return
        stats_list = list(all_stats.values())
        html_path = self._report_service.generate_html_report(stats_list)
        csv_path  = self._report_service.generate_csv_report(stats_list)
        if html_path and csv_path:
            QMessageBox.information(
                self, "Reports Generated",
                f"HTML: {html_path}\nCSV:  {csv_path}"
            )
        else:
            QMessageBox.warning(self, "Error", "Failed to generate reports.")

    # ─────────────────────────────────────────────
    # Helpers de Renderização (sem lógica de negócio)
    # ─────────────────────────────────────────────

    def _parse_hosts(self) -> list[str]:
        return self._manager.parse_hosts(self.host_input.toPlainText())

    def _init_table(self, hosts: list[str]):
        self.table.setRowCount(0)
        self._host_row.clear()
        for row, host in enumerate(hosts):
            self.table.insertRow(row)
            self._host_row[host] = row
            self._update_table_row(row, host, PingStats(host=host), "Starting...")

    def _update_table_row(self, row: int, host: str, stats: PingStats, status: str):
        loss = stats.packet_loss
        loss_color   = QColor("#f38ba8") if loss > 0 else QColor("#a6e3a1")
        status_color = (
            QColor("#a6e3a1") if status in ("Finished", "Stopped")
            else QColor("#f9e2af") if status == "Starting..."
            else QColor("#89b4fa")
        )

        def _item(text: str, color: QColor = QColor("#cdd6f4")) -> QTableWidgetItem:
            it = QTableWidgetItem(text)
            it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            it.setForeground(color)
            return it

        self.table.setItem(row, 0,  _item(host))
        self.table.setItem(row, 1,  _item(str(stats.packets_sent)))
        self.table.setItem(row, 2,  _item(str(stats.packets_received)))
        self.table.setItem(row, 3,  _item(f"{loss:.1f}%", loss_color))
        self.table.setItem(row, 4,  _item(f"{stats.min_latency:.1f}"))
        self.table.setItem(row, 5,  _item(f"{stats.max_latency:.1f}"))
        self.table.setItem(row, 6,  _item(f"{stats.avg_latency:.1f}"))
        self.table.setItem(row, 7,  _item(f"{stats.jitter:.1f}"))
        self.table.setItem(row, 8,  _item(f"{stats.std_dev:.1f}"))
        mos = stats.mos
        mos_color = (
            QColor("#a6e3a1") if mos >= 4.0
            else QColor("#f9e2af") if mos >= 3.0
            else QColor("#f38ba8")
        )
        self.table.setItem(row, 9,  _item(f"{mos:.1f}", mos_color))
        self.table.setItem(row, 10, _item(status, status_color))

    def _set_all_status(self, status: str):
        color = QColor("#a6e3a1") if status in ("Finished", "Stopped") else QColor("#cdd6f4")
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 10)
            if item:
                item.setText(status)
                item.setForeground(color)
