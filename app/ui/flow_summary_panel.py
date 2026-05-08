"""
FlowSummaryPanel — Painel de resumo de fluxos, top talkers e top protocolos.

Responsabilidades:
- Exibir CaptureSummary em cards de métricas globais
- Listar flows ordenados por volume (pacotes/bytes)
- Exibir top talkers (IPs mais ativos)
- Exibir top protocolos
- Sem lógica de análise — recebe dados prontos via populate()
"""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget,
    QTableWidgetItem, QHeaderView, QGroupBox, QSplitter, QSizePolicy
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont

from app.core.models import CaptureSummary, FlowSummary


class FlowSummaryPanel(QWidget):
    """
    Painel de análise de fluxos e top talkers.
    Recebe dados prontos do PacketAnalyzer via MainWindow.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(8)

        # ── Cards de summary ───────────────────────────────────────────────
        summary_group = QGroupBox("Capture Summary")
        cards_layout = QHBoxLayout(summary_group)

        self._summary_labels: dict[str, QLabel] = {}
        for key, caption in [
            ("total_packets", "Packets"),
            ("total_bytes",   "Bytes"),
            ("flow_count",    "Flows"),
            ("duration_s",    "Duration (s)"),
        ]:
            card, lbl = self._make_card(caption)
            self._summary_labels[key] = lbl
            cards_layout.addWidget(card)

        layout.addWidget(summary_group)

        # ── Splitter: fluxos | top talkers/protos ─────────────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Tabela de fluxos
        flow_group = QGroupBox("Top Flows (by packet count)")
        flow_vl = QVBoxLayout(flow_group)
        self.flow_table = self._make_table(["Flow", "Packets", "Bytes", "Duration"])
        flow_vl.addWidget(self.flow_table)
        splitter.addWidget(flow_group)

        # Painel direito: top talkers + top protocolos (vertical)
        right = QWidget()
        right_vl = QVBoxLayout(right)
        right_vl.setContentsMargins(0, 0, 0, 0)

        talkers_group = QGroupBox("Top Talkers (by packet count)")
        talkers_vl = QVBoxLayout(talkers_group)
        self.talkers_table = self._make_table(["IP Address", "Packets"])
        talkers_vl.addWidget(self.talkers_table)
        right_vl.addWidget(talkers_group)

        protos_group = QGroupBox("Top Protocols")
        protos_vl = QVBoxLayout(protos_group)
        self.protos_table = self._make_table(["Protocol", "Packets", "%"])
        protos_vl.addWidget(self.protos_table)
        right_vl.addWidget(protos_group)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)

        layout.addWidget(splitter, stretch=1)

    # ── API pública ────────────────────────────────────────────────────────

    def populate(self, summary: CaptureSummary, flows: list[FlowSummary]) -> None:
        """Atualiza todos os sub-painéis com os dados analisados."""
        self._update_summary_cards(summary)
        self._update_flows(flows, summary.total_packets)
        self._update_talkers(summary.top_hosts)
        self._update_protos(summary.top_protocols, summary.total_packets)

    def clear(self) -> None:
        for lbl in self._summary_labels.values():
            lbl.setText("—")
        for table in (self.flow_table, self.talkers_table, self.protos_table):
            table.setRowCount(0)

    # ── Internos ───────────────────────────────────────────────────────────

    def _update_summary_cards(self, s: CaptureSummary) -> None:
        self._summary_labels["total_packets"].setText(f"{s.total_packets:,}")
        self._summary_labels["total_bytes"].setText(f"{s.total_bytes:,}")
        self._summary_labels["flow_count"].setText(str(s.flow_count))
        self._summary_labels["duration_s"].setText(f"{s.duration_s:.2f}")

    def _update_flows(self, flows: list[FlowSummary], total: int) -> None:
        self.flow_table.setRowCount(0)
        for row, flow in enumerate(flows[:100]):
            self.flow_table.insertRow(row)
            self._set_row(self.flow_table, row, [
                flow.label,
                str(flow.packets),
                f"{flow.bytes_:,}",
                f"{flow.duration_s:.2f}s",
            ], "#89b4fa")

    def _update_talkers(self, hosts: list[tuple[str, int]]) -> None:
        self.talkers_table.setRowCount(0)
        for row, (ip, cnt) in enumerate(hosts):
            self.talkers_table.insertRow(row)
            self._set_row(self.talkers_table, row, [ip, str(cnt)], "#a6e3a1")

    def _update_protos(self, protos: list[tuple[str, int]], total: int) -> None:
        self.protos_table.setRowCount(0)
        for row, (proto, cnt) in enumerate(protos):
            pct = f"{cnt / total * 100:.1f}%" if total else "0%"
            self.protos_table.insertRow(row)
            color = {
                "TCP": "#89b4fa", "UDP": "#a6e3a1", "ICMP": "#f9e2af",
                "ARP": "#cba6f7", "IPv6": "#94e2d5",
            }.get(proto, "#cdd6f4")
            self._set_row(self.protos_table, row, [proto, str(cnt), pct], color)

    def _set_row(self, table: QTableWidget, row: int, values: list[str], color: str) -> None:
        for col, val in enumerate(values):
            it = QTableWidgetItem(val)
            it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            it.setForeground(QColor(color))
            table.setItem(row, col, it)

    def _make_table(self, headers: list[str]) -> QTableWidget:
        t = QTableWidget()
        t.setColumnCount(len(headers))
        t.setHorizontalHeaderLabels(headers)
        t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        t.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        t.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        t.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        t.setStyleSheet("""
            QTableWidget {
                background-color: #181825; gridline-color: #313244;
                border: 1px solid #313244; border-radius: 4px; font-size: 11px;
            }
            QHeaderView::section {
                background-color: #313244; color: #cdd6f4;
                font-weight: bold; padding: 4px;
            }
            QTableWidget::item:selected { background-color: #45475a; }
        """)
        return t

    def _make_card(self, caption: str) -> tuple[QWidget, QLabel]:
        card = QWidget()
        card.setStyleSheet("QWidget { background-color: #313244; border-radius: 6px; }")
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        vl = QVBoxLayout(card)
        vl.setContentsMargins(8, 6, 8, 6)

        cap_lbl = QLabel(caption)
        cap_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cap_lbl.setStyleSheet("color: #bac2de; font-size: 11px; background: transparent;")
        vl.addWidget(cap_lbl)

        val_lbl = QLabel("—")
        val_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        val_lbl.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        val_lbl.setStyleSheet("color: #a6e3a1; background: transparent;")
        vl.addWidget(val_lbl)

        return card, val_lbl
