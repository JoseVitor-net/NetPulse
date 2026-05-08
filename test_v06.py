"""
test_v06.py — Teste automatizado da v0.6: Session History + Replay UI.

Valida:
1. Storage.list_sessions() / get_session_summary() / get_session_results()
2. ReplayEngine.load_session() / play() / pause() / resume() / stop() / set_speed()
3. Replay por host (filtro parcial)
4. Replay da sessão inteira
5. Pause/Stop sem crash
6. Export HTML/CSV a partir de sessão histórica
7. Modo LIVE/REPLAY na MainWindow sem conflito
"""
import sys
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer
from app.infra.logger import setup_logger
from app.infra.storage import Storage
from app.core.session_manager import SessionManager
from app.core.replay_engine import ReplayEngine
from app.services.ping_manager import PingManager
from app.services.report_service import ReportService
from app.ui.main_window import MainWindow


PASS = "[PASS]"
FAIL = "[FAIL]"


def run_tests():
    setup_logger()
    app = QApplication(sys.argv)

    storage         = Storage()
    session_manager = SessionManager(storage)
    manager         = PingManager(storage=storage, session_manager=session_manager)
    report_service  = ReportService()
    replay_engine   = ReplayEngine(storage)
    window          = MainWindow(manager=manager, report_service=report_service, replay_engine=replay_engine)

    print(f"{PASS} Application instantiated without exception.")

    # ── Passo 1: Gerar uma sessão com dados reais ───────────────────────────
    from app.core.models import SessionConfig
    window.host_input.setPlainText("8.8.8.8")
    window.mode_combo.setCurrentIndex(0)   # Standard (4)
    window.btn_start.click()
    print(f"{PASS} Live session started.")

    def after_live_session():
        # Valida que a sessão terminou
        assert not manager.is_running, "Manager still running after session"
        print(f"{PASS} Live session finished (is_running=False).")

        # ── Passo 2: Storage.list_sessions ─────────────────────────────────
        sessions = storage.list_sessions()
        assert len(sessions) > 0, "list_sessions returned empty"
        print(f"{PASS} list_sessions: {len(sessions)} sessao(es) encontradas.")

        latest_id = sessions[0]["session_id"]
        assert sessions[0]["ping_count"] > 0, "ping_count deve ser > 0"
        print(f"{PASS} ping_count={sessions[0]['ping_count']} na sessao mais recente.")

        # ── Passo 3: Storage.get_session_summary ───────────────────────────
        summary = storage.get_session_summary(latest_id)
        assert summary, "get_session_summary retornou vazio"
        assert summary["total_pings"] > 0, "total_pings deve ser > 0"
        assert "avg_latency" in summary, "avg_latency ausente no summary"
        print(f"{PASS} get_session_summary: total_pings={summary['total_pings']}, avg={summary['avg_latency']}ms, MOS={summary['avg_mos']}.")

        # ── Passo 4: Storage.get_session_results ───────────────────────────
        results = storage.get_session_results(latest_id)
        assert len(results) > 0, "get_session_results retornou vazio"
        assert "host" in results[0], "campo 'host' ausente no resultado"
        print(f"{PASS} get_session_results: {len(results)} resultados.")

        results_filtered = storage.get_session_results(latest_id, host="8.8.8.8")
        assert len(results_filtered) > 0, "get_session_results filtrado por host retornou vazio"
        print(f"{PASS} get_session_results(host='8.8.8.8'): {len(results_filtered)} resultados.")

        # ── Passo 5: ReplayEngine.load_session ─────────────────────────────
        count = replay_engine.load_session(latest_id)
        assert count > 0, f"load_session retornou 0 eventos para {latest_id}"
        print(f"{PASS} ReplayEngine.load_session: {count} eventos carregados.")

        # load_session filtrado por host
        count_host = replay_engine.load_session(latest_id, host_filter="8.8.8.8")
        assert count_host > 0, "load_session filtrado por host retornou 0 eventos"
        print(f"{PASS} ReplayEngine.load_session(host='8.8.8.8'): {count_host} eventos.")

        # ── Passo 6: set_speed ──────────────────────────────────────────────
        replay_engine.load_session(latest_id)
        replay_engine.set_speed(5.0)
        print(f"{PASS} set_speed(5.0) sem erro.")

        # ── Passo 7: play / pause / resume / stop ──────────────────────────
        states_received: list[str] = []
        replay_engine.state_changed.connect(lambda s: states_received.append(s))

        replay_engine.play()
        assert states_received and states_received[-1] == "playing", f"Estado esperado 'playing', recebido: {states_received}"
        print(f"{PASS} play(): estado='playing'.")

        replay_engine.pause()
        assert states_received[-1] == "paused", f"Estado esperado 'paused', recebido: {states_received}"
        print(f"{PASS} pause(): estado='paused'.")

        replay_engine.resume()
        assert states_received[-1] == "playing", f"Estado esperado 'playing' após resume, recebido: {states_received}"
        print(f"{PASS} resume(): estado='playing'.")

        replay_engine.stop()
        assert states_received[-1] == "stopped", f"Estado esperado 'stopped', recebido: {states_received}"
        print(f"{PASS} stop(): estado='stopped'. Nenhum crash.")

        # ── Passo 8: Replay via UI (SessionDetailPanel) ────────────────────
        window.tabs.setCurrentIndex(1)    # muda para aba Replay
        assert window._mode == "REPLAY", "Modo deveria ser REPLAY na aba 1"
        print(f"{PASS} Tab switch: modo={window._mode}.")

        window.session_detail.load_summary(summary)
        window.session_detail._on_play()
        QTimer.singleShot(300, lambda: replay_engine.stop())
        print(f"{PASS} Replay via SessionDetailPanel iniciado e parado sem crash.")

        # ── Passo 9: Export HTML/CSV a partir de sessão histórica ──────────
        QTimer.singleShot(600, lambda: check_export(latest_id))

    def check_export(session_id: str):
        from app.core.models import PingStats
        hosts = storage.get_session_hosts(session_id)
        stats_list = []
        for host in hosts:
            st = PingStats(host=host)
            pings = storage.get_session_results(session_id, host)
            for p in pings:
                if p["success"] and p["latency_ms"] is not None:
                    st.add_latency(p["latency_ms"])
                else:
                    st.add_failure()
            stats_list.append(st)

        html_path = report_service.generate_html_report(stats_list)
        csv_path  = report_service.generate_csv_report(stats_list)
        assert html_path, "HTML report nao gerado"
        assert csv_path,  "CSV report nao gerado"
        print(f"{PASS} Export HTML: {html_path}")
        print(f"{PASS} Export CSV:  {csv_path}")

        # ── Passo 10: HistoryPanel.populate ────────────────────────────────
        sessions = storage.list_sessions()
        window.history_panel.populate(sessions)
        assert window.history_panel.table.rowCount() > 0, "HistoryPanel vazio apos populate"
        print(f"{PASS} HistoryPanel.populate: {window.history_panel.table.rowCount()} linhas.")

        # ── Passo 11: Filtro de histórico ───────────────────────────────────
        filtered = storage.list_sessions(host_filter="8.8.8.8")
        assert len(filtered) > 0, "list_sessions com host_filter retornou vazio"
        print(f"{PASS} list_sessions(host_filter='8.8.8.8'): {len(filtered)} sessao(es).")

        print("\n" + "=" * 60)
        print("  v0.6 VALIDADA — todos os criterios de aceite passaram.")
        print("=" * 60)
        app.quit()

    # Timer para aguardar o ping de 4 pacotes (~4s) + margem
    QTimer.singleShot(7000, after_live_session)
    sys.exit(app.exec())


if __name__ == "__main__":
    run_tests()
