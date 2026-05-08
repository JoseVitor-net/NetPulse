import sys
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer
from app.infra.logger import setup_logger
from app.infra.storage import Storage
from app.core.session_manager import SessionManager
from app.services.ping_manager import PingManager
from app.services.report_service import ReportService
from app.ui.main_window import MainWindow

def test_multihost_load():
    setup_logger()
    app = QApplication(sys.argv)
    
    storage = Storage()
    session_manager = SessionManager(storage)
    manager = PingManager(storage=storage, session_manager=session_manager)
    report_service = ReportService()
    
    window = MainWindow(manager=manager, report_service=report_service)
    
    print("[TEST] Application started.")
    
    # Generate 50 dummy IP addresses to simulate load
    # Many will fail, but that's a good test of network timeout handling
    hosts = [f"127.0.0.{i}" for i in range(1, 51)]
    
    # Input 50 hosts using newlines
    window.host_input.setPlainText("\n".join(hosts))
    window.mode_combo.setCurrentIndex(2) # Continuous
    
    print(f"[TEST] Starting ping load test with {len(hosts)} hosts...")
    window.btn_start.click()
    
    def check_finished():
        print("[TEST] 6 seconds elapsed, checking state...")
        active_threads = sum(1 for w in manager._threads.values() if w.isRunning())
        print(f"[TEST] Active threads running: {active_threads}")
        
        # We test the stop button while they are running to test graceful teardown
        print("[TEST] Forcing stop during massive concurrent ping...")
        window.btn_start.click() # Stop
        print(f"[TEST] manager.is_running is {manager.is_running}")
        
        QTimer.singleShot(1000, finish_test)
        
    def finish_test():
        remaining = sum(1 for w in manager._threads.values() if w.isRunning())
        print(f"[TEST] Zombie threads after 1s stop: {remaining}")
        print("[TEST] Load test complete. Closing app.")
        app.quit()
        
    # Wait enough time for 50 threads to spin up and do some work
    QTimer.singleShot(6000, check_finished)
    sys.exit(app.exec())

if __name__ == "__main__":
    test_multihost_load()
