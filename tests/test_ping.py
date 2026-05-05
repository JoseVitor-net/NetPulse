import pytest
from app.core.models import PingStats

def test_ping_stats_loss_calculation():
    stats = PingStats(host="8.8.8.8")
    assert stats.packet_loss == 0.0
    
    stats.packets_sent = 4
    stats.packets_received = 2
    assert stats.packet_loss == 50.0
    
    stats.packets_received = 4
    assert stats.packet_loss == 0.0
    
    stats.packets_received = 0
    assert stats.packet_loss == 100.0
