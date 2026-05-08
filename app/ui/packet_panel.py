"""
PacketPanel — Tabela de pacotes PCAP com filtros em tempo real.

Responsabilidades:
- Exibir a lista de PacketRow em QTableWidget com virtualização por batch
- Oferecer filtros por IP, porta e protocolo sem bloquear UI
- Emitir sinal filter_changed quando o usuário aplica filtros
- Emitir sinal export_requested para exportação
- Não contém lógica de negócio — é pura apresentação
"""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QComboBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QGroupBox, QProgressBar
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont

from app.core.models import PacketRow

# Mapeamento de protocolo → cor de linha
_PROTO_COLORS: dict[str, str] = {
    "TCP":  "#89b4fa",
    "UDP":  "#a6e3a1",
    "ICMP": "#f9e2af",
    "ARP":  "#cba6f7",
    "IPv6": "#94e2d5",
}
_DEFAULT_COLOR = "#cdd6f4"

# Máximo de linhas exibidas na tabela (performance)
_MAX_DISPLAY_ROWS = 10_000


class PacketPanel(QWidget):
    """
    Painel de tabela de pacotes PCAP.

    Sinais:
        filter_applied(ip, port, protocol, text) — usuário aplicou filtros
        export_requested()                        — usuário pediu exportação
        open_file_requested()                     — usuário quer abrir arquivo
    """

    filter_applied    = pyqtSignal(str, str, str, str)
    export_requested  = pyqtSignal()
    open_file_requested = pyqtSignal()
    
    # Live Capture Sinais
    live_start_requested = pyqtSignal(str, str) # iface, bpf_filter
    live_stop_requested  = pyqtSignal()
    live_save_requested  = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        # ── Barra de ferramentas (Live Capture & File) ─────────────────────
        toolbar = QHBoxLayout()

        self.btn_open = QPushButton("📂  Open PCAP")
        self.btn_open.clicked.connect(self.open_file_requested)
        toolbar.addWidget(self.btn_open)

        self.btn_export = QPushButton("⬇  Export")
        self.btn_export.clicked.connect(self.export_requested)
        self.btn_export.setEnabled(False)
        toolbar.addWidget(self.btn_export)
        
        toolbar.addSpacing(20)

        # Controles Live Capture
        toolbar.addWidget(QLabel("Interface:"))
        self.combo_iface = QComboBox()
        self.combo_iface.setMinimumWidth(150)
        toolbar.addWidget(self.combo_iface)

        toolbar.addWidget(QLabel("BPF Filter:"))
        self.input_bpf = QLineEdit()
        self.input_bpf.setPlaceholderText("ex: tcp port 80")
        self.input_bpf.setMinimumWidth(120)
        toolbar.addWidget(self.input_bpf)

        self.btn_live_start = QPushButton("▶  Start")
        self.btn_live_start.clicked.connect(self._on_live_start)
        toolbar.addWidget(self.btn_live_start)

        self.btn_live_stop = QPushButton("⏹  Stop")
        self.btn_live_stop.clicked.connect(self.live_stop_requested)
        self.btn_live_stop.setEnabled(False)
        toolbar.addWidget(self.btn_live_stop)

        self.btn_live_save = QPushButton("💾  Save .pcap")
        self.btn_live_save.clicked.connect(self.live_save_requested)
        self.btn_live_save.setEnabled(False)
        toolbar.addWidget(self.btn_live_save)

        toolbar.addStretch()

        self.status_label = QLabel("No file loaded")
        self.status_label.setStyleSheet("color: #6c7086; font-size: 12px;")
        toolbar.addWidget(self.status_label)

        layout.addLayout(toolbar)

        # ── Barra de progresso ─────────────────────────────────────────────
        self.progress = QProgressBar()
        self.progress.setMaximum(0)   # modo indeterminate
        self.progress.setFixedHeight(6)
        self.progress.setTextVisible(False)
        self.progress.hide()
        self.progress.setStyleSheet("""
            QProgressBar { border: none; background: #181825; }
            QProgressBar::chunk { background: #89b4fa; }
        """)
        layout.addWidget(self.progress)

        # ── Filtros ────────────────────────────────────────────────────────
        filter_group = QGroupBox("Filters")
        fg = QHBoxLayout(filter_group)

        fg.addWidget(QLabel("IP:"))
        self.ip_input = QLineEdit()
        self.ip_input.setPlaceholderText("ex: 8.8.8.8")
        self.ip_input.setMaximumWidth(160)
        fg.addWidget(self.ip_input)

        fg.addWidget(QLabel("Port:"))
        self.port_input = QLineEdit()
        self.port_input.setPlaceholderText("443")
        self.port_input.setMaximumWidth(80)
        fg.addWidget(self.port_input)

        fg.addWidget(QLabel("Protocol:"))
        self.proto_combo = QComboBox()
        self.proto_combo.addItems(["Any", "TCP", "UDP", "ICMP", "ARP", "IPv6"])
        self.proto_combo.setMaximumWidth(90)
        fg.addWidget(self.proto_combo)

        fg.addWidget(QLabel("Search:"))
        self.text_input = QLineEdit()
        self.text_input.setPlaceholderText("text in Info field…")
        self.text_input.setMaximumWidth(200)
        fg.addWidget(self.text_input)

        self.btn_apply = QPushButton("Apply")
        self.btn_apply.clicked.connect(self._on_apply)
        fg.addWidget(self.btn_apply)

        self.btn_clear_filter = QPushButton("Clear")
        self.btn_clear_filter.clicked.connect(self._on_clear_filter)
        fg.addWidget(self.btn_clear_filter)

        fg.addStretch()
        self.result_label = QLabel("")
        self.result_label.setStyleSheet("color: #a6e3a1; font-size: 12px;")
        fg.addWidget(self.result_label)

        layout.addWidget(filter_group)

        # ── Tabela de pacotes ──────────────────────────────────────────────
        self.table = QTableWidget()
        self.table.setColumnCount(9)
        self.table.setHorizontalHeaderLabels([
            "No.", "Time", "Src IP", "Dst IP", "Src Port", "Dst Port", "Proto", "Length", "Info"
        ])
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(7, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(8, QHeaderView.ResizeMode.Stretch)

        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet("""
            QTableWidget {
                background-color: #181825; gridline-color: #313244;
                border: 1px solid #313244; border-radius: 4px;
                alternate-background-color: #1e1e2e;
                font-size: 11px;
            }
            QHeaderView::section {
                background-color: #313244; color: #cdd6f4;
                font-weight: bold; padding: 4px;
            }
            QTableWidget::item:selected { background-color: #45475a; }
        """)
        layout.addWidget(self.table, stretch=1)

    # ── API pública ────────────────────────────────────────────────────────

    def populate(self, packets: list[PacketRow]) -> None:
        """
        Preenche a tabela com a lista de pacotes.
        Trunca em _MAX_DISPLAY_ROWS para manter performance.
        """
        display = packets[:_MAX_DISPLAY_ROWS]
        self.table.setRowCount(0)
        self.table.setRowCount(len(display))

        for row, pkt in enumerate(display):
            color = QColor(_PROTO_COLORS.get(pkt.protocol, _DEFAULT_COLOR))

            def _item(text: str) -> QTableWidgetItem:
                it = QTableWidgetItem(str(text))
                it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                it.setForeground(color)
                return it

            self.table.setItem(row, 0, _item(pkt.index))
            self.table.setItem(row, 1, _item(pkt.ts_str))
            self.table.setItem(row, 2, _item(pkt.src_ip))
            self.table.setItem(row, 3, _item(pkt.dst_ip))
            self.table.setItem(row, 4, _item(pkt.src_port or ""))
            self.table.setItem(row, 5, _item(pkt.dst_port or ""))
            self.table.setItem(row, 6, _item(pkt.protocol))
            self.table.setItem(row, 7, _item(pkt.length))

            info_item = QTableWidgetItem(pkt.info)
            info_item.setForeground(color)
            self.table.setItem(row, 8, info_item)

        self.result_label.setText(
            f"{len(display):,} packets" +
            (f" (of {len(packets):,})" if len(packets) > _MAX_DISPLAY_ROWS else "")
        )

    def set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def set_loading(self, loading: bool) -> None:
        if loading:
            self.progress.show()
            self.btn_open.setEnabled(False)
        else:
            self.progress.hide()
            self.btn_open.setEnabled(True)
            self.btn_export.setEnabled(True)

    def populate_interfaces(self, interfaces: list[str]) -> None:
        self.combo_iface.clear()
        self.combo_iface.addItems(interfaces)

    def set_live_mode(self, active: bool) -> None:
        if active:
            self.btn_live_start.setEnabled(False)
            self.btn_live_stop.setEnabled(True)
            self.btn_live_save.setEnabled(False)
            self.btn_open.setEnabled(False)
            self.combo_iface.setEnabled(False)
            self.input_bpf.setEnabled(False)
        else:
            self.btn_live_start.setEnabled(True)
            self.btn_live_stop.setEnabled(False)
            self.btn_live_save.setEnabled(True)
            self.btn_open.setEnabled(True)
            self.combo_iface.setEnabled(True)
            self.input_bpf.setEnabled(True)

    # ── Slots internos ─────────────────────────────────────────────────────

    def _on_apply(self) -> None:
        ip    = self.ip_input.text().strip()
        port  = self.port_input.text().strip()
        proto = self.proto_combo.currentText()
        proto = "" if proto == "Any" else proto
        text  = self.text_input.text().strip()
        self.filter_applied.emit(ip, port, proto, text)

    def _on_clear_filter(self) -> None:
        self.ip_input.clear()
        self.port_input.clear()
        self.proto_combo.setCurrentIndex(0)
        self.text_input.clear()
        self.filter_applied.emit("", "", "", "")

    def _on_live_start(self) -> None:
        iface = self.combo_iface.currentText()
        bpf = self.input_bpf.text().strip()
        self.live_start_requested.emit(iface, bpf)
