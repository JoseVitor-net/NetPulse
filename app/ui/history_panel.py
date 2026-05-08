"""
HistoryPanel — Painel de listagem e filtro de sessões históricas.

Responsabilidades:
- Exibir a lista de sessões com contagem de pings
- Permitir filtro por host (substring) e período (data)
- Emitir sinal session_selected(session_id) quando usuário escolhe uma sessão
- NÃO acessa Storage diretamente: recebe dados via método populate()
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
    QDateEdit, QGroupBox
)
from PyQt6.QtCore import Qt, pyqtSignal, QDate
from PyQt6.QtGui import QColor, QFont

import json


class HistoryPanel(QWidget):
    """
    Painel lateral de histórico.
    Sinal session_selected: str — session_id selecionado pelo usuário.
    """

    session_selected = pyqtSignal(str)   # session_id
    filter_requested = pyqtSignal(str, str, str)  # host_filter, date_from, date_to

    def __init__(self, parent=None):
        super().__init__(parent)
        self._session_map: dict[int, str] = {}  # row → session_id
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        # Título
        title = QLabel("Session History")
        title.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        title.setStyleSheet("color: #89b4fa;")
        layout.addWidget(title)

        # Filtros
        filter_group = QGroupBox("Filters")
        fg_layout = QVBoxLayout(filter_group)

        # Host filter
        host_row = QHBoxLayout()
        host_row.addWidget(QLabel("Host:"))
        self.host_filter = QLineEdit()
        self.host_filter.setPlaceholderText("8.8.8.8 or partial…")
        host_row.addWidget(self.host_filter)
        fg_layout.addLayout(host_row)

        # Date filter
        date_row = QHBoxLayout()
        date_row.addWidget(QLabel("From:"))
        self.date_from = QDateEdit()
        self.date_from.setCalendarPopup(True)
        self.date_from.setDate(QDate.currentDate().addDays(-30))
        self.date_from.setDisplayFormat("yyyy-MM-dd")
        date_row.addWidget(self.date_from)

        date_row.addWidget(QLabel("To:"))
        self.date_to = QDateEdit()
        self.date_to.setCalendarPopup(True)
        self.date_to.setDate(QDate.currentDate())
        self.date_to.setDisplayFormat("yyyy-MM-dd")
        date_row.addWidget(self.date_to)
        fg_layout.addLayout(date_row)

        # Botão buscar
        self.btn_search = QPushButton("Search")
        self.btn_search.clicked.connect(self._on_search)
        fg_layout.addWidget(self.btn_search)

        layout.addWidget(filter_group)

        # Tabela de sessões
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Started", "Ended", "Hosts", "Pings"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.itemSelectionChanged.connect(self._on_row_selected)
        self.table.setStyleSheet("""
            QTableWidget {
                background-color: #181825; gridline-color: #313244;
                border: 1px solid #313244; border-radius: 4px;
                font-size: 12px;
            }
            QHeaderView::section {
                background-color: #313244; color: #cdd6f4;
                font-weight: bold; padding: 4px; border: 1px solid #181825;
            }
            QTableWidget::item:selected { background-color: #45475a; }
        """)
        layout.addWidget(self.table, stretch=1)

    # ── API pública ────────────────────────────────────────────────────────

    def populate(self, sessions: list[dict]) -> None:
        """
        Preenche a tabela com a lista de sessões.
        Cada dict: {session_id, started_at, ended_at, hosts, ping_count}
        """
        self.table.setRowCount(0)
        self._session_map.clear()

        for row, s in enumerate(sessions):
            self.table.insertRow(row)
            self._session_map[row] = s["session_id"]

            started = s.get("started_at", "")[:16].replace("T", " ")
            ended   = (s.get("ended_at") or "ongoing")[:16].replace("T", " ")

            try:
                hosts = json.loads(s["hosts"]) if isinstance(s["hosts"], str) else s["hosts"]
                hosts_str = ", ".join(hosts)
            except Exception:
                hosts_str = str(s.get("hosts", ""))

            ping_count = str(s.get("ping_count", ""))

            def _item(text: str, color: str = "#cdd6f4") -> QTableWidgetItem:
                it = QTableWidgetItem(text)
                it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                it.setForeground(QColor(color))
                return it

            self.table.setItem(row, 0, _item(started))
            self.table.setItem(row, 1, _item(ended))
            self.table.setItem(row, 2, _item(hosts_str, "#89b4fa"))
            self.table.setItem(row, 3, _item(ping_count, "#a6e3a1"))

    # ── Slots internos ─────────────────────────────────────────────────────

    def _on_search(self) -> None:
        host_filter = self.host_filter.text().strip()
        date_from   = self.date_from.date().toString("yyyy-MM-dd")
        date_to     = self.date_to.date().toString("yyyy-MM-dd")
        self.filter_requested.emit(host_filter, date_from, date_to)

    def _on_row_selected(self) -> None:
        rows = self.table.selectedItems()
        if not rows:
            return
        row = self.table.currentRow()
        session_id = self._session_map.get(row)
        if session_id:
            self.session_selected.emit(session_id)
