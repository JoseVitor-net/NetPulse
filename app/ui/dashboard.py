from PyQt6.QtWidgets import QWidget, QVBoxLayout
import pyqtgraph as pg
from collections import deque
import random

class PyQtGraphDashboard(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        
        # Configurar cores base
        pg.setConfigOption('background', '#1e1e2e')
        pg.setConfigOption('foreground', '#cdd6f4')
        pg.setConfigOptions(antialias=True)
        
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.addLegend() # Adiciona legenda para múltiplos hosts
        self.layout.addWidget(self.plot_widget)
        
        self.plot_widget.setLabel('left', 'Latency (ms)')
        self.plot_widget.setLabel('bottom', 'Pings')
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        
        # Estado do Multi-host
        self.hosts_data = {}  # dict[host] -> {'x': deque, 'y': deque, 'times': int, 'curve': PlotDataItem}
        
        # Cores predefinidas para os primeiros hosts, depois sorteia
        self.palette = ['#a6e3a1', '#89b4fa', '#f38ba8', '#f9e2af', '#cba6f7', '#94e2d5']
        self.color_idx = 0

    def init_host(self, host: str):
        if host in self.hosts_data:
            return
            
        color = self.palette[self.color_idx % len(self.palette)]
        self.color_idx += 1
        
        pen = pg.mkPen(color=color, width=2)
        curve = self.plot_widget.plot(
            [], [], 
            pen=pen, 
            symbol='o', 
            symbolSize=5, 
            symbolBrush=color,
            name=host
        )
        
        self.hosts_data[host] = {
            'x': deque(maxlen=60),
            'y': deque(maxlen=60),
            'times': 0,
            'curve': curve
        }

    def update_data(self, host: str, latency_ms: float):
        if host not in self.hosts_data:
            self.init_host(host)
            
        data = self.hosts_data[host]
        data['times'] += 1
        data['x'].append(data['times'])
        data['y'].append(latency_ms)
        
        data['curve'].setData(list(data['x']), list(data['y']))
        
    def reset(self):
        self.plot_widget.clear()
        self.hosts_data.clear()
        self.color_idx = 0
