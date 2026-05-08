"""
Composition Root do NetPulse.

Este é o ÚNICO ponto onde as dependências são criadas e injetadas.
Nenhuma outra camada deve instanciar serviços diretamente.
"""
import sys
from PyQt6.QtWidgets import QApplication

from app.infra.logger import setup_logger
from app.infra.database import DatabaseSetup
from app.infra.storage import Storage
from app.core.session_manager import SessionManager
from app.core.replay_engine import ReplayEngine
from app.services.ping_manager import PingManager
from app.services.report_service import ReportService
from app.ui.main_window import MainWindow


def main():
    setup_logger()
    app = QApplication(sys.argv)

    # Composição de dependências — ordem importa (infra → services → ui)
    db = DatabaseSetup()          # Legado mantido
    storage = Storage()
    session_manager = SessionManager(storage)

    manager        = PingManager(storage=storage, session_manager=session_manager)
    report_service = ReportService()
    replay_engine  = ReplayEngine(storage)

    window = MainWindow(
        manager=manager,
        report_service=report_service,
        replay_engine=replay_engine,
    )
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
