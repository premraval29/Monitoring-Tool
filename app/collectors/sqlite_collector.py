import os
import time
import sqlite3
from typing import Dict, Any
from app.collectors.base_db import BaseDatabaseCollector
from app.collectors.system_collector import format_bytes

class SQLiteCollector(BaseDatabaseCollector):
    def __init__(self, config: Dict[str, Any]):
        super().__init__(name=config.get("name", "SQLite"), config=config)

    def collect(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "name": self.name,
            "type": "SQLite",
            "enabled": self.enabled,
            "status": "offline",
            "latency_ms": None,
            "active_connections": 0,
            "total_connections": 0,
            "database_size_bytes": 0,
            "database_size_human": "0 B",
            "version": f"SQLite {sqlite3.sqlite_version}",
            "error": None,
        }

        if not self.enabled:
            result["status"] = "disabled"
            return result

        db_path = self.config.get("database_path", "monitoring.db")
        
        try:
            start_time = time.perf_counter()
            conn = sqlite3.connect(db_path, timeout=self.timeout)
            with conn:
                cur = conn.cursor()
                cur.execute("SELECT 1;")
                cur.fetchone()
            latency_ms = round((time.perf_counter() - start_time) * 1000, 2)

            file_size = os.path.getsize(db_path) if os.path.exists(db_path) else 0

            result.update({
                "status": "online",
                "latency_ms": latency_ms,
                "active_connections": 1,
                "total_connections": 1,
                "database_size_bytes": file_size,
                "database_size_human": format_bytes(file_size),
                "error": None,
            })
            conn.close()
        except Exception as e:
            result["status"] = "offline"
            result["error"] = str(e).strip()

        return result

