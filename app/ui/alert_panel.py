"""
AlertPanel — Painel de visualização de alertas de diagnóstico de rede.

Responsabilidades:
- Exibir alertas gerados pelo NetworkAnalyzer em tempo real
- Colorir entradas por severidade (CRITICAL / WARNING / INFO)
- Limitar o histórico visual a MAX_ALERTS entradas (sem crescimento infinito)
- Não contém lógica de negócio — apenas renderização
"""
from collections import deque

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QListWidget, QListWidgetItem, QPushButton, QLabel
)
from PyQt6.QtCore import Qt, pyqtSlot
from PyQt6.QtGui import QColor, QFont

from app.core.models import Alert


# Limite de entradas visíveis no painel (evita crescimento infinito da lista Qt)
MAX_ALERTS = 100

# Mapeamento de severidade → (emoji, cor de texto)
_SEVERITY_STYLE: dict[str, tuple[str, str]] = {
    "CRITICAL": ("🔴", "#f38ba8"),
    "WARNING":  ("🟡", "#f9e2af"),
    "INFO":     ("🔵", "#89b4fa"),
}

# Mapeamento de kind → descrição amigável
_KIND_LABEL: dict[str, str] = {
    "LATENCY_TREND":  "Trend",
    "LATENCY_SPIKE":  "Spike",
    "PACKET_LOSS":    "Loss",
    "ISP_FAILURE":    "ISP",
}


class AlertPanel(QWidget):
    """Widget de exibição de alertas com scroll automático e botão de limpeza."""

    def __init__(self, parent=None):
        super().__init__(parent)

        # Controle de limite sem remover itens da QListWidget um a um (custo alto)
        # O deque controla a contagem e disparamos remoção apenas quando necessário
        self._count = 0

        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Cabeçalho
        header_layout = QHBoxLayout()
        title = QLabel("⚡ Diagnostic Alerts")
        title.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        title.setStyleSheet("color: #cba6f7;")

        self.btn_clear = QPushButton("Clear")
        self.btn_clear.setFixedWidth(60)
        self.btn_clear.clicked.connect(self.clear)

        header_layout.addWidget(title)
        header_layout.addStretch()
        header_layout.addWidget(self.btn_clear)
        layout.addLayout(header_layout)

        # Lista de alertas
        self.list_widget = QListWidget()
        self.list_widget.setFixedHeight(120)
        self.list_widget.setStyleSheet("""
            QListWidget {
                background-color: #181825;
                border: 1px solid #313244;
                border-radius: 4px;
                color: #cdd6f4;
                font-size: 12px;
            }
            QListWidget::item { padding: 3px 6px; border-bottom: 1px solid #1e1e2e; }
            QListWidget::item:selected { background-color: #313244; }
        """)
        layout.addWidget(self.list_widget)

    # ─────────────────────────────────────────────
    # Slot público — conectado ao PingManager.alert_raised
    # ─────────────────────────────────────────────

    @pyqtSlot(Alert)
    def add_alert(self, alert: Alert) -> None:
        """Insere um novo alerta no topo da lista com formatação por severidade."""
        # Remove o alerta mais antigo se atingiu o limite
        if self._count >= MAX_ALERTS:
            self.list_widget.takeItem(self.list_widget.count() - 1)
        else:
            self._count += 1

        emoji, color = _SEVERITY_STYLE.get(alert.severity, ("⚪", "#cdd6f4"))
        kind_label = _KIND_LABEL.get(alert.kind, alert.kind)
        ts = alert.timestamp.strftime("%H:%M:%S")

        text = f"{emoji} [{ts}] [{kind_label}] {alert.host} — {alert.message}"

        item = QListWidgetItem(text)
        item.setForeground(QColor(color))

        # Insere no topo (mais recente primeiro)
        self.list_widget.insertItem(0, item)

    def clear(self) -> None:
        """Limpa todos os alertas do painel. Parte do contrato público do widget."""
        self.list_widget.clear()
        self._count = 0

