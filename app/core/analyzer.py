"""
NetworkAnalyzer — Motor de diagnóstico inteligente de rede.

Design:
- Puro Python. Sem Qt, sem rede, sem I/O. Totalmente testável em isolamento.
- Stateful por host: mantém janela deslizante de resultados recentes.
- Chamado de forma síncrona pelo PingManager a cada resultado recebido.
- Retorna lista de alertas (pode ser vazia) — nunca lança exceções para o caller.

Detectores implementados:
  1. LATENCY_TREND  — Tendência crescente via regressão linear simples (OLS)
  2. PACKET_LOSS    — Perda contínua acima do limiar na janela recente
  3. ISP_FAILURE    — Múltiplos hosts em degradação simultânea (correlação)
"""
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from app.core.models import Alert, PingResult


# ─────────────────────────────────────────────────────────────
# Configuração de Limiares (thresholds)
# ─────────────────────────────────────────────────────────────

WINDOW_SIZE = 20          # Tamanho da janela deslizante por host (pacotes)
LOSS_WINDOW = 10          # Janela menor para detecção de perda contínua
LOSS_THRESHOLD = 0.30     # 30% de perda → alerta PACKET_LOSS
ISP_HOSTS_THRESHOLD = 2   # Mínimo de hosts simultâneos em falha → ISP_FAILURE
ISP_LOSS_THRESHOLD = 0.50 # 50% de perda por host para contar na correlação ISP
SLOPE_THRESHOLD = 2.0     # ms por pacote → inclinação mínima para LATENCY_TREND
ALERT_COOLDOWN_SECS = 30  # Impede repetição do mesmo alerta dentro desse intervalo


@dataclass
class _HostState:
    """Estado interno de análise para um único host."""
    window: deque = field(default_factory=lambda: deque(maxlen=WINDOW_SIZE))
    # Controle de cooldown: kind → último datetime emitido
    last_alert_time: dict[str, datetime] = field(default_factory=dict)


class NetworkAnalyzer:
    """
    Motor de análise de rede sem dependências externas.

    Uso:
        analyzer = NetworkAnalyzer()
        alerts = analyzer.feed("8.8.8.8", ping_result)
        for alert in alerts:
            # emitir via sinal Qt, logar, etc.
    """

    def __init__(self) -> None:
        self._hosts: dict[str, _HostState] = {}

    def feed(self, host: str, result: PingResult) -> list[Alert]:
        """
        Processa um resultado de ping e retorna alertas gerados (pode ser lista vazia).
        Chamado pelo PingManager a cada pacote recebido. Thread-safe para uso
        a partir da QThread do PingService via signal/slot (executa na main thread).
        """
        if host not in self._hosts:
            self._hosts[host] = _HostState()

        state = self._hosts[host]
        state.window.append(result)

        alerts: list[Alert] = []

        alerts.extend(self._detect_latency_trend(host, state))
        alerts.extend(self._detect_packet_loss(host, state))
        alerts.extend(self._detect_isp_failure(host))

        return alerts

    def reset(self) -> None:
        """Limpa todo o estado acumulado. Chamado no início de nova sessão."""
        self._hosts.clear()

    # ─────────────────────────────────────────────
    # Detectores Privados
    # ─────────────────────────────────────────────

    def _detect_latency_trend(self, host: str, state: _HostState) -> list[Alert]:
        """
        Regressão linear simples (OLS) sobre as latências da janela.
        Gera LATENCY_TREND se o coeficiente angular (slope) exceder SLOPE_THRESHOLD.
        Complexidade: O(N) com N = WINDOW_SIZE (fixo, não cresce com o tempo).
        """
        latencies = [r.latency_ms for r in state.window if r.success and r.latency_ms]
        if len(latencies) < 5:
            return []  # Janela insuficiente para análise estatística

        slope = self._linear_slope(latencies)
        if slope < SLOPE_THRESHOLD:
            return []

        return self._make_alert(
            host=host,
            state=state,
            kind="LATENCY_TREND",
            severity="WARNING",
            message=(
                f"Tendência de aumento de latência detectada em {host}: "
                f"+{slope:.1f} ms/pacote nos últimos {len(latencies)} pings."
            ),
        )

    def _detect_packet_loss(self, host: str, state: _HostState) -> list[Alert]:
        """
        Verifica perda de pacotes na sub-janela mais recente (LOSS_WINDOW pacotes).
        Gera PACKET_LOSS se a proporção exceder LOSS_THRESHOLD.
        """
        recent = list(state.window)[-LOSS_WINDOW:]
        if len(recent) < LOSS_WINDOW:
            return []  # Ainda não há dados suficientes

        failures = sum(1 for r in recent if not r.success)
        loss_ratio = failures / len(recent)

        if loss_ratio < LOSS_THRESHOLD:
            return []

        severity = "CRITICAL" if loss_ratio >= 0.7 else "WARNING"
        return self._make_alert(
            host=host,
            state=state,
            kind="PACKET_LOSS",
            severity=severity,
            message=(
                f"Perda contínua de pacotes em {host}: "
                f"{loss_ratio * 100:.0f}% nos últimos {LOSS_WINDOW} pings."
            ),
        )

    def _detect_isp_failure(self, triggering_host: str) -> list[Alert]:
        """
        Correlaciona degradação entre todos os hosts monitorados.
        Se ≥ ISP_HOSTS_THRESHOLD hosts distintos estiverem em perda > ISP_LOSS_THRESHOLD,
        emite ISP_FAILURE no host que disparou o último pacote (host representativo).
        """
        degraded_hosts = []
        for host, state in self._hosts.items():
            recent = list(state.window)[-LOSS_WINDOW:]
            if len(recent) < LOSS_WINDOW:
                continue
            failures = sum(1 for r in recent if not r.success)
            if failures / len(recent) >= ISP_LOSS_THRESHOLD:
                degraded_hosts.append(host)

        if len(degraded_hosts) < ISP_HOSTS_THRESHOLD:
            return []

        state = self._hosts[triggering_host]
        hosts_str = ", ".join(degraded_hosts)
        return self._make_alert(
            host=triggering_host,
            state=state,
            kind="ISP_FAILURE",
            severity="CRITICAL",
            message=(
                f"Falha sistêmica detectada em {len(degraded_hosts)} hosts simultâneos "
                f"({hosts_str}). Possível falha de ISP ou gateway."
            ),
        )

    # ─────────────────────────────────────────────
    # Utilitários
    # ─────────────────────────────────────────────

    def _make_alert(
        self,
        host: str,
        state: _HostState,
        kind: str,
        severity: str,
        message: str,
    ) -> list[Alert]:
        """
        Cria um alerta respeitando o cooldown por (host, kind).
        Retorna lista vazia se o alerta foi emitido recentemente.
        """
        now = datetime.now()
        last = state.last_alert_time.get(kind)
        if last and (now - last) < timedelta(seconds=ALERT_COOLDOWN_SECS):
            return []  # Dentro do cooldown — silencia repetição

        state.last_alert_time[kind] = now
        return [Alert(host=host, severity=severity, kind=kind, message=message, timestamp=now)]

    @staticmethod
    def _linear_slope(values: list[float]) -> float:
        """
        Calcula o coeficiente angular (slope) via OLS sem dependências externas.
        Formula: slope = (N·Σxy - Σx·Σy) / (N·Σx² - (Σx)²)
        """
        n = len(values)
        if n < 2:
            return 0.0

        x_vals = list(range(n))
        sum_x = sum(x_vals)
        sum_y = sum(values)
        sum_xy = sum(x * y for x, y in zip(x_vals, values))
        sum_x2 = sum(x * x for x in x_vals)

        denom = n * sum_x2 - sum_x ** 2
        if denom == 0:
            return 0.0

        return (n * sum_xy - sum_x * sum_y) / denom
