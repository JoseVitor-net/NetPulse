"""Verificacao direta da v0.6 — roda como script separado."""
import sys
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer

app = QApplication(sys.argv)

from app.infra.storage import Storage
from app.core.session_manager import SessionManager
from app.core.replay_engine import ReplayEngine
from app.services.ping_manager import PingManager
from app.services.report_service import ReportService
from app.ui.main_window import MainWindow

storage = Storage()
sm  = SessionManager(storage)
mgr = PingManager(storage=storage, session_manager=sm)
rs  = ReportService()
re  = ReplayEngine(storage)
w   = MainWindow(manager=mgr, report_service=rs, replay_engine=re)

w.host_input.setPlainText("8.8.8.8")
w.mode_combo.setCurrentIndex(0)
w.btn_start.click()
print("[PASS] Sessao LIVE iniciada.")


def run_checks():
    print("[PASS] is_running =", mgr.is_running)

    # 1. list_sessions
    sessions = storage.list_sessions()
    assert len(sessions) > 0, "list_sessions vazio"
    print("[PASS] list_sessions:", len(sessions), "sessoes")
    sid = sessions[0]["session_id"]

    # 2. get_session_summary
    s = storage.get_session_summary(sid)
    assert s and s["total_pings"] > 0, "summary invalido"
    print("[PASS] get_session_summary: total_pings =", s["total_pings"], "avg =", s["avg_latency"], "MOS =", s["avg_mos"])

    # 3. get_session_results
    res = storage.get_session_results(sid)
    assert len(res) > 0, "get_session_results vazio"
    print("[PASS] get_session_results:", len(res), "resultados")

    res_h = storage.get_session_results(sid, host="8.8.8.8")
    assert len(res_h) > 0, "get_session_results(host) vazio"
    print("[PASS] get_session_results(host=8.8.8.8):", len(res_h), "resultados")

    # 4. ReplayEngine.load_session
    count = re.load_session(sid)
    assert count > 0, "load_session retornou 0 eventos"
    print("[PASS] ReplayEngine.load_session:", count, "eventos")

    count_h = re.load_session(sid, host_filter="8.8.8.8")
    assert count_h > 0, "load_session filtrado retornou 0"
    print("[PASS] ReplayEngine.load_session(host_filter):", count_h, "eventos")

    # 5. play / pause / resume / stop
    states = []
    re.state_changed.connect(lambda st: states.append(st))
    re.set_speed(10.0)
    re.load_session(sid)
    re.play()
    assert states and states[-1] == "playing", states
    print("[PASS] play(): playing")

    re.pause()
    assert states[-1] == "paused", states
    print("[PASS] pause(): paused")

    re.resume()
    assert states[-1] == "playing", states
    print("[PASS] resume(): playing")

    re.stop()
    assert states[-1] == "stopped", states
    print("[PASS] stop(): stopped — sem crash")

    # 6. Export historico
    from app.core.models import PingStats
    hosts = storage.get_session_hosts(sid)
    stats_list = []
    for host in hosts:
        st = PingStats(host=host)
        for p in storage.get_session_results(sid, host):
            if p["success"] and p["latency_ms"]:
                st.add_latency(p["latency_ms"])
            else:
                st.add_failure()
        stats_list.append(st)
    html = rs.generate_html_report(stats_list)
    csv  = rs.generate_csv_report(stats_list)
    assert html and csv, "export falhou"
    print("[PASS] Export HTML+CSV gerados")

    # 7. HistoryPanel.populate
    w.history_panel.populate(sessions)
    assert w.history_panel.table.rowCount() > 0
    print("[PASS] HistoryPanel.populate:", w.history_panel.table.rowCount(), "linhas")

    # 8. SessionDetailPanel.load_summary
    w.session_detail.load_summary(s)
    print("[PASS] SessionDetailPanel.load_summary: sem erro")

    # 9. Modo LIVE/REPLAY
    w.tabs.setCurrentIndex(1)
    assert w._mode == "REPLAY", w._mode
    print("[PASS] Aba Replay -> modo REPLAY")

    w.tabs.setCurrentIndex(0)
    assert w._mode == "LIVE", w._mode
    print("[PASS] Aba Live -> modo LIVE")

    # 10. Filtro de historico
    filt = storage.list_sessions(host_filter="8.8.8.8")
    assert len(filt) > 0
    print("[PASS] list_sessions(host_filter=8.8.8.8):", len(filt), "sessoes")

    print("")
    print("=" * 56)
    print("  v0.6 APROVADA - todos os criterios de aceite passaram.")
    print("=" * 56)
    app.quit()


QTimer.singleShot(7000, run_checks)
sys.exit(app.exec())
