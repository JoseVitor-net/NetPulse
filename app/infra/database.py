import sqlite3
import os
from loguru import logger
from datetime import datetime
from app.core.models import PingResult

class DatabaseSetup:
    def __init__(self, db_path="data/netpulse.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    def _init_db(self):
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS ping_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        host TEXT NOT NULL,
                        timestamp TEXT NOT NULL,
                        success BOOLEAN NOT NULL,
                        latency_ms REAL,
                        error_msg TEXT
                    )
                ''')
                conn.commit()
            logger.info("Database initialized successfully.")
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")

    def save_result(self, result: PingResult):
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO ping_history (host, timestamp, success, latency_ms, error_msg)
                    VALUES (?, ?, ?, ?, ?)
                ''', (
                    result.host,
                    result.timestamp.isoformat(),
                    result.success,
                    result.latency_ms,
                    result.error_msg
                ))
                conn.commit()
        except Exception as e:
            logger.error(f"Error saving ping result: {e}")
