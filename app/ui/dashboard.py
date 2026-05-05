from PyQt6.QtWidgets import QWidget, QVBoxLayout
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtCore import QUrl
import plotly.graph_objects as go
import plotly.io as pio
import os
import tempfile
from collections import deque

class PlotlyDashboard(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        
        self.web_view = QWebEngineView()
        self.layout.addWidget(self.web_view)
        
        self.x_data = deque(maxlen=60)
        self.y_data = deque(maxlen=60)
        self.times = 0
        
        self._init_plot()

    def _init_plot(self):
        self.fig = go.Figure()
        self.fig.add_trace(go.Scatter(
            x=list(self.x_data), 
            y=list(self.y_data), 
            mode='lines+markers',
            name='Latency',
            line=dict(color='#a6e3a1', width=2),
            marker=dict(size=6, color='#89b4fa')
        ))
        
        self.fig.update_layout(
            template="plotly_dark",
            paper_bgcolor="#1e1e2e",
            plot_bgcolor="#1e1e2e",
            margin=dict(l=20, r=20, t=20, b=20),
            xaxis=dict(title="Time", showgrid=True, gridcolor="#313244", zeroline=False),
            yaxis=dict(title="Latency (ms)", showgrid=True, gridcolor="#313244", zeroline=False),
            font=dict(color="#cdd6f4")
        )
        self._update_webview()

    def update_data(self, latency_ms: float):
        self.times += 1
        self.x_data.append(self.times)
        self.y_data.append(latency_ms)
        
        # In a very high frequency app we would use JavaScript injection.
        # For 1 ping per second, regenerating HTML is acceptable and robust.
        self.fig.data[0].x = tuple(self.x_data)
        self.fig.data[0].y = tuple(self.y_data)
        self._update_webview()
        
    def reset(self):
        self.x_data.clear()
        self.y_data.clear()
        self.times = 0
        self._init_plot()

    def _update_webview(self):
        html = pio.to_html(self.fig, include_plotlyjs='cdn', full_html=True)
        self.web_view.setHtml(html)
