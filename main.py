import sys
from PyQt6.QtWidgets import QApplication
from app.ui.main_window import MainWindow
from app.infra.logger import setup_logger

def main():
    setup_logger()
    app = QApplication(sys.argv)
    
    # Initialize main window
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
