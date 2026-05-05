"""
MainWindow — Camada de apresentação do NetPulse.

Responsabilidades EXCLUSIVAS:
- Renderizar a interface gráfica
- Capturar inputs do usuário e delegar ao PingManager
- Reagir aos sinais emitidos pelo PingManager

NÃO deve:
- Conhecer PingService ou QThread
- Gerenciar estado de rede (stats_map, threads_map)
- Conter lógica de negócio de rede
"""
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QComboBox,
    QSpinBox, QGroupBox, QMessageBox, QTableWidget, QTableWidgetItem, QHeaderView
)
import json

from PyQt6.QtCore import Qt, pyqtSlot
from PyQt6.QtGui import QFont, QColor

from app.core.models import Alert, PingStats, SessionConfig
from app.services.ping_manager import PingManager
from app.services.report_service import ReportService
from app.ui.alert_panel import AlertPanel
from app.ui.dashboard import PyQtGraphDashboard


class MainWindow(QMainWindow):
    def __init__(self, manager: PingManager, report_service: ReportService):
        """
        :param manager: Instância do PingManager injetada pelo entry point.
        :param report_service: Serviço de geração de relatórios.
        """
        super().__init__()
        self.setWindowTitle("NetPulse - NOC Edition")
        self.resize(1100, 800)

        # Dependências injetadas — UI não cria serviços de rede
        self._manager = manager
        self._report_service = report_service

        # Índice de linha por host (lookup O(1) na tabela)
        self._host_row: dict[str, int] = {}

        self._setup_ui()
        self._apply_styles()
        self._connect_manager_signals()

    # ─────────────────────────────────────────────
    # Construção da UI
    # ─────────────────────────────────────────────

    def _setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # Header
        header = QLabel("NetPulse NOC")
        header.setFont(QFont("Segoe UI", 24, QFont.Weight.Bold))
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(header)

        # Controls
        controls_group = QGroupBox("Configuration  —  separate multiple hosts with commas")
        controls_layout = QHBoxLayout()

        self.host_input = QLineEdit("8.8.8.8, 1.1.1.1, google.com")
        self.host_input.setPlaceholderText("ex: 8.8.8.8, 1.1.1.1, cloudflare.com")

        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["Standard (4)", "Custom Count", "Continuous"])
        self.mode_combo.currentIndexChanged.connect(self._on_mode_change)

        self.count_input = QSpinBox()
        self.count_input.setRange(1, 1000)
        self.count_input.setValue(4)
        self.count_input.setEnabled(False)

        self.btn_start = QPushButton("▶  Start Ping")
        self.btn_start.clicked.connect(self._toggle_session)

        self.btn_report = QPushButton("⬇  Export Report")
        self.btn_report.clicked.connect(self._generate_report)
        self.btn_report.setEnabled(False)

        controls_layout.addWidget(QLabel("Target(s):"))
        controls_layout.addWidget(self.host_input, stretch=1)
        controls_layout.addWidget(QLabel("Mode:"))
        controls_layout.addWidget(self.mode_combo)
        controls_layout.addWidget(self.count_input)
        controls_layout.addWidget(self.btn_start)
        controls_layout.addWidget(self.btn_report)
        controls_group.setLayout(controls_layout)
        main_layout.addWidget(controls_group)

        # History Group
        history_group = QGroupBox("Session History")
        history_layout = QHBoxLayout()

        self.session_combo = QComboBox()
        self.session_combo.setPlaceholderText("Select a previous session...")
        self.session_combo.setMinimumWidth(320)

        self.btn_load_history = QPushButton("📂  Load History")
        self.btn_load_history.clicked.connect(self._on_load_history)

        history_layout.addWidget(QLabel("Session:"))
        history_layout.addWidget(self.session_combo, stretch=1)
        history_layout.addWidget(self.btn_load_history)
        history_group.setLayout(history_layout)
        main_layout.addWidget(history_group)

        # Stats Table
        self.table = QTableWidget()
        self.table.setColumnCount(9)
        self.table.setHorizontalHeaderLabels([
            "Host", "Sent", "Recv", "Loss (%)", "Min (ms)", "Max (ms)", "Avg (ms)", "Jitter (ms)", "Status"
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.setMinimumHeight(150)
        main_layout.addWidget(self.table)

        # Painel de Alertas de Diagnóstico
        self.alert_panel = AlertPanel()
        main_layout.addWidget(self.alert_panel)

        # Dashboard (pyqtgraph) — sem lógica, só renderização
        self.dashboard = PyQtGraphDashboard()
        main_layout.addWidget(self.dashboard, stretch=1)

    def _apply_styles(self):
        self.setStyleSheet("""
        QMainWindow, QWidget {
            background-color: #1e1e2e; color: #cdd6f4; font-family: 'Segoe UI';
        }
        QGroupBox {
            font-weight: bold; border: 1px solid #313244;
            border-radius: 6px; margin-top: 12px; padding-top: 10px;
        }
        QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; color: #89b4fa; }
        QLineEdit, QSpinBox, QComboBox {
            background-color: #181825; border: 1px solid #313244;
            border-radius: 4px; padding: 5px; color: #cdd6f4;
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
        QLabel { font-size: 14px; }
        """)

    # ─────────────────────────────────────────────
    # Conexão com PingManager (feita uma única vez)
    # ─────────────────────────────────────────────

    def _connect_manager_signals(self):
        """Registra os callbacks da UI nos sinais do PingManager."""
        self._manager.stats_updated.connect(self._on_stats_updated)
        self._manager.chart_point_ready.connect(self.dashboard.update_data)
        self._manager.alert_raised.connect(self.alert_panel.add_alert)
        self._manager.session_finished.connect(self._on_session_finished)
        self._manager.sessions_loaded.connect(self._on_sessions_loaded)

    # ─────────────────────────────────────────────
    # Handlers de Eventos de Input (UI → Manager)
    # ─────────────────────────────────────────────

    def _on_mode_change(self, index: int):
        self.count_input.setEnabled(index == 1)

    def _toggle_session(self):
        if self._manager.is_running:
            self._manager.stop_session()
            self.btn_start.setText("▶  Start Ping")
            self.btn_report.setEnabled(True)
            self._set_all_status("Stopped")
        else:
            # Delega parse ao Manager (regra de negócio, não de renderização)
            hosts = self._manager.parse_hosts(self.host_input.text())
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

    # ─────────────────────────────────────────────
    # Slots: Manager → UI
    # ─────────────────────────────────────────────

    @pyqtSlot(str, PingStats, str)
    def _on_stats_updated(self, host: str, stats: PingStats, status: str):
        """Recebe estado + status já calculado pelo Manager e repinta a tabela."""
        row = self._host_row.get(host)
        if row is None:
            return
        self._update_table_row(row, host, stats, status)

    @pyqtSlot()
    def _on_session_finished(self):
        self.btn_start.setText("▶  Start Ping")
        self.btn_report.setEnabled(True)
        self._set_all_status("Finished")

    # ─────────────────────────────────────────────
    # Slots: Histórico
    # ─────────────────────────────────────────────

    @pyqtSlot()
    def _on_load_history(self):
        """Solicita sessões recentes ao Manager. Resposta chega via sessions_loaded."""
        self._manager.request_sessions()

    @pyqtSlot(list)
    def _on_sessions_loaded(self, sessions: list):
        """Popula o combo com sessões recentes e escuta seleção."""
        self.session_combo.clear()
        self._session_map: dict[int, str] = {}  # combo index → session_id

        for i, s in enumerate(sessions):
            started = s["started_at"][:19].replace("T", " ")
            ended = s["ended_at"][:19].replace("T", " ") if s["ended_at"] else "ongoing"
            try:
                hosts = json.loads(s["hosts"])
                label = f"{started} → {ended}  |  {', '.join(hosts)}"
            except Exception:
                label = f"{started} → {ended}"
            self.session_combo.addItem(label)
            self._session_map[i] = s["session_id"]

        # Conecta seleção apenas uma vez
        try:
            self.session_combo.currentIndexChanged.disconnect(self._on_session_selected)
        except RuntimeError:
            pass
        self.session_combo.currentIndexChanged.connect(self._on_session_selected)

        if sessions:
            self.session_combo.setCurrentIndex(0)
            self._on_session_selected(0)

    @pyqtSlot(int)
    def _on_session_selected(self, index: int):
        """Carrega dados históricos da sessão selecionada."""
        if not hasattr(self, "_session_map") or index not in self._session_map:
            return
        session_id = self._session_map[index]
        self.dashboard.reset()
        self.alert_panel.clear()
        self.table.setRowCount(0)
        self._host_row.clear()
        self._manager.load_session(session_id)

    # ─────────────────────────────────────────────
    # Helpers de Renderização (sem lógica de negócio)
    # ─────────────────────────────────────────────

    def _parse_hosts(self) -> list[str]:
        """Delega parse ao Manager. Mantido apenas como compat. — use manager.parse_hosts."""
        return self._manager.parse_hosts(self.host_input.text())


    def _init_table(self, hosts: list[str]):
        """Reinicia a tabela com uma linha por host."""
        self.table.setRowCount(0)
        self._host_row.clear()
        for row, host in enumerate(hosts):
            self.table.insertRow(row)
            self._host_row[host] = row
            self._update_table_row(row, host, PingStats(host=host), "Starting...")

    def _update_table_row(self, row: int, host: str, stats: PingStats, status: str):
        """Repinta uma linha inteira da tabela com os dados atualizados."""
        loss = stats.packet_loss
        loss_color = QColor("#f38ba8") if loss > 0 else QColor("#a6e3a1")

        if status in ("Finished", "Stopped"):
            status_color = QColor("#a6e3a1")
        elif status == "Starting...":
            status_color = QColor("#f9e2af")
        else:
            status_color = QColor("#89b4fa")  # Running / OK

        def _item(text: str, color: QColor = QColor("#cdd6f4")) -> QTableWidgetItem:
            it = QTableWidgetItem(text)
            it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            it.setForeground(color)
            return it

        self.table.setItem(row, 0, _item(host))
        self.table.setItem(row, 1, _item(str(stats.packets_sent)))
        self.table.setItem(row, 2, _item(str(stats.packets_received)))
        self.table.setItem(row, 3, _item(f"{loss:.1f}%", loss_color))
        self.table.setItem(row, 4, _item(f"{stats.min_latency:.1f}"))
        self.table.setItem(row, 5, _item(f"{stats.max_latency:.1f}"))
        self.table.setItem(row, 6, _item(f"{stats.avg_latency:.1f}"))
        self.table.setItem(row, 7, _item(f"{stats.jitter:.1f}"))
        self.table.setItem(row, 8, _item(status, status_color))

    def _set_all_status(self, status: str):
        """Atualiza a coluna Status de todas as linhas da tabela."""
        color = QColor("#a6e3a1") if status in ("Finished", "Stopped") else QColor("#cdd6f4")
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 8)
            if item:
                item.setText(status)
                item.setForeground(color)

    # ─────────────────────────────────────────────
    # Relatório
    # ─────────────────────────────────────────────

    def _generate_report(self):
        all_stats = self._manager.get_all_stats()
        if not all_stats:
            return
        first_stats = next(iter(all_stats.values()))
        filepath = self._report_service.generate_html_report(first_stats)
        if filepath:
            QMessageBox.information(self, "Report Generated", f"Saved to:\n{filepath}")
        else:
            QMessageBox.warning(self, "Error", "Failed to generate report.")
