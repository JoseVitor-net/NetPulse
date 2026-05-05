from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QLabel, QLineEdit, QPushButton, QComboBox, 
    QSpinBox, QGroupBox, QGridLayout, QMessageBox
)
from PyQt6.QtCore import Qt, pyqtSlot
from PyQt6.QtGui import QFont

from app.services.ping_service import PingService
from app.services.report_service import ReportService
from app.infra.database import DatabaseSetup
from app.core.models import PingResult, PingStats
from app.ui.dashboard import PlotlyDashboard

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("NetPulse - Professional Network Monitor")
        self.resize(1000, 700)
        
        self.db = DatabaseSetup()
        self.ping_service = None
        self.report_service = ReportService()
        
        self.stats = PingStats(host="")
        self._setup_ui()
        self._apply_styles()

    def _setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        # Header
        header = QLabel("NetPulse")
        header.setFont(QFont("Segoe UI", 24, QFont.Weight.Bold))
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(header)
        
        # Controls Group
        controls_group = QGroupBox("Configuration")
        controls_layout = QHBoxLayout()
        
        self.host_input = QLineEdit("8.8.8.8")
        self.host_input.setPlaceholderText("Enter IP or Domain")
        
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["Standard (4)", "Custom Count", "Continuous"])
        self.mode_combo.currentIndexChanged.connect(self._on_mode_change)
        
        self.count_input = QSpinBox()
        self.count_input.setRange(1, 1000)
        self.count_input.setValue(4)
        self.count_input.setEnabled(False)
        
        self.btn_start = QPushButton("Start Ping")
        self.btn_start.clicked.connect(self._toggle_ping)
        
        self.btn_report = QPushButton("Generate Report")
        self.btn_report.clicked.connect(self._generate_report)
        self.btn_report.setEnabled(False)
        
        controls_layout.addWidget(QLabel("Target:"))
        controls_layout.addWidget(self.host_input)
        controls_layout.addWidget(QLabel("Mode:"))
        controls_layout.addWidget(self.mode_combo)
        controls_layout.addWidget(self.count_input)
        controls_layout.addWidget(self.btn_start)
        controls_layout.addWidget(self.btn_report)
        controls_group.setLayout(controls_layout)
        
        main_layout.addWidget(controls_group)
        
        # Stats Group
        stats_group = QGroupBox("Real-time Statistics")
        stats_layout = QGridLayout()
        
        self.lbl_sent = self._create_stat_label("0")
        self.lbl_recv = self._create_stat_label("0")
        self.lbl_loss = self._create_stat_label("0%")
        self.lbl_min = self._create_stat_label("0 ms")
        self.lbl_max = self._create_stat_label("0 ms")
        self.lbl_avg = self._create_stat_label("0 ms")
        self.lbl_jitter = self._create_stat_label("0 ms")
        self.lbl_status = self._create_stat_label("Idle", color="#a6adc8")
        
        stats_layout.addWidget(QLabel("Sent:"), 0, 0)
        stats_layout.addWidget(self.lbl_sent, 0, 1)
        stats_layout.addWidget(QLabel("Received:"), 0, 2)
        stats_layout.addWidget(self.lbl_recv, 0, 3)
        stats_layout.addWidget(QLabel("Loss:"), 0, 4)
        stats_layout.addWidget(self.lbl_loss, 0, 5)
        
        stats_layout.addWidget(QLabel("Min:"), 1, 0)
        stats_layout.addWidget(self.lbl_min, 1, 1)
        stats_layout.addWidget(QLabel("Max:"), 1, 2)
        stats_layout.addWidget(self.lbl_max, 1, 3)
        stats_layout.addWidget(QLabel("Avg:"), 1, 4)
        stats_layout.addWidget(self.lbl_avg, 1, 5)
        
        stats_layout.addWidget(QLabel("Jitter:"), 2, 0)
        stats_layout.addWidget(self.lbl_jitter, 2, 1)
        stats_layout.addWidget(QLabel("Status:"), 2, 2)
        stats_layout.addWidget(self.lbl_status, 2, 3)
        
        stats_group.setLayout(stats_layout)
        main_layout.addWidget(stats_group)
        
        # Dashboard (Plotly)
        self.dashboard = PlotlyDashboard()
        main_layout.addWidget(self.dashboard, stretch=1)

    def _create_stat_label(self, text, color="#a6e3a1"):
        lbl = QLabel(text)
        lbl.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        lbl.setStyleSheet(f"color: {color};")
        return lbl

    def _apply_styles(self):
        style = """
        QMainWindow, QWidget { background-color: #1e1e2e; color: #cdd6f4; font-family: 'Segoe UI'; }
        QGroupBox { font-weight: bold; border: 1px solid #313244; border-radius: 6px; margin-top: 12px; padding-top: 10px; }
        QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; color: #89b4fa; }
        QLineEdit, QSpinBox, QComboBox { background-color: #181825; border: 1px solid #313244; border-radius: 4px; padding: 5px; color: #cdd6f4; }
        QPushButton { background-color: #89b4fa; color: #1e1e2e; font-weight: bold; border: none; border-radius: 4px; padding: 8px 15px; }
        QPushButton:hover { background-color: #b4befe; }
        QPushButton:disabled { background-color: #45475a; color: #a6adc8; }
        QLabel { font-size: 14px; }
        """
        self.setStyleSheet(style)

    def _on_mode_change(self, index):
        self.count_input.setEnabled(index == 1)

    def _toggle_ping(self):
        if self.ping_service and self.ping_service.isRunning():
            self.ping_service.stop()
            self.btn_start.setText("Start Ping")
            self.lbl_status.setText("Stopped")
            self.btn_report.setEnabled(True)
        else:
            host = self.host_input.text().strip()
            
            # Higienização simples (removendo http/https e barras)
            host = host.replace("http://", "").replace("https://", "").split("/")[0]
            if not host:
                QMessageBox.warning(self, "Invalid Input", "Please enter a valid host or IP.")
                return

            self.host_input.setText(host)
            self.dashboard.reset()
            self.stats = PingStats(host=host)
            self.btn_report.setEnabled(False)
            
            mode_idx = self.mode_combo.currentIndex()
            count = 4 if mode_idx == 0 else self.count_input.value()
            continuous = mode_idx == 2
            
            self.ping_service = PingService(host=host, count=count, continuous=continuous, db=self.db)
            self.ping_service.result_received.connect(self._on_ping_result)
            self.ping_service.finished.connect(self._on_ping_finished)
            
            self.ping_service.start()
            self.btn_start.setText("Stop Ping")
            self.lbl_status.setText("Running...")
            self.lbl_status.setStyleSheet("color: #f9e2af;")

    @pyqtSlot(PingResult)
    def _on_ping_result(self, result: PingResult):
        if result.success and result.latency_ms is not None:
            self.stats.add_latency(result.latency_ms)
            self.dashboard.update_data(result.latency_ms)
        else:
            self.stats.add_failure()
            # Quando falha, adicionamos o ponto com latência 0 para manter o gráfico visualmente
            # indicando quebra, ou ignoramos. Aqui vamos ignorar no gráfico e mostrar só no texto.
        
        self._update_stats_ui()

    def _update_stats_ui(self):
        self.lbl_sent.setText(str(self.stats.packets_sent))
        self.lbl_recv.setText(str(self.stats.packets_received))
        
        loss = self.stats.packet_loss
        self.lbl_loss.setText(f"{loss:.1f}%")
        if loss > 0:
            self.lbl_loss.setStyleSheet("color: #f38ba8;")
        else:
            self.lbl_loss.setStyleSheet("color: #a6e3a1;")
            
        self.lbl_min.setText(f"{self.stats.min_latency:.1f} ms")
        self.lbl_max.setText(f"{self.stats.max_latency:.1f} ms")
        self.lbl_avg.setText(f"{self.stats.avg_latency:.1f} ms")
        self.lbl_jitter.setText(f"{self.stats.jitter:.1f} ms")

    @pyqtSlot()
    def _on_ping_finished(self):
        self.btn_start.setText("Start Ping")
        self.lbl_status.setText("Finished")
        self.lbl_status.setStyleSheet("color: #a6e3a1;")
        self.btn_report.setEnabled(True)

    def _generate_report(self):
        filepath = self.report_service.generate_html_report(self.stats)
        if filepath:
            QMessageBox.information(self, "Report Generated", f"Report successfully saved to:\n{filepath}")
        else:
            QMessageBox.warning(self, "Error", "Failed to generate report.")
