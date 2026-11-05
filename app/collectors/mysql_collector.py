import time
from typing import Dict, Any
from app.collectors.base_db import BaseDatabaseCollector
from app.collectors.system_collector import format_bytes

try:
    import pymysql
except ImportError:
    pymysql = None

class MySQLCollector(BaseDatabaseCollector):
    def __init__(self, config: Dict[str, Any]):
        super().__init__(name=config.get("name", "MySQL"), config=config)
        self.conn = None

    def _get_connection(self, host: str, port: int, user: str, password: str, database: str, timeout: int):
        """Ensures an active, healthy MySQL connection, reconnecting if disconnected."""
        if self.conn is not None:
            try:
                self.conn.ping(reconnect=False)
                return self.conn
            except Exception:
                try:
                    self.conn.close()
                except Exception:
                    pass
                self.conn = None

        self.conn = pymysql.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            connect_timeout=timeout,
            read_timeout=timeout,
            write_timeout=timeout,
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=True,
        )
        return self.conn

    def close(self):
        """Safely closes persistent connection."""
        if self.conn:
            try:
                self.conn.close()
            except Exception:
                pass
            self.conn = None

    def collect(self) -> Dict[str, Any]:
        host = self.config.get("host", "127.0.0.1")
        port = int(self.config.get("port", 3306))
        user = self.config.get("user", "root")
        password = self.config.get("password", "")
        database = self.config.get("database", "mysql")
        timeout = int(self.timeout)

        result: Dict[str, Any] = {
            "name": self.name,
            "type": "MySQL",
            "host": host,
            "port": port,
            "user": user,
            "database": database,
            "enabled": self.enabled,
            "status": "offline",
            "latency_ms": None,
            "active_connections": 0,
            "total_connections": 0,
            "database_size_bytes": 0,
            "database_size_human": "0 B",
            "version": "",
            "uptime_seconds": 0,
            "error": None,
        }

        if not self.enabled:
            result["status"] = "disabled"
            return result

        if pymysql is None:
            result["error"] = "pymysql library not installed"
            return result

        try:
            conn = self._get_connection(host, port, user, password, database, timeout)
            with conn.cursor() as cur:
                # Measure true query execution latency
                t0 = time.perf_counter()
                cur.execute("SELECT 1;")
                cur.fetchone()
                latency_ms = round((time.perf_counter() - t0) * 1000, 2)

                # Fetch global status variables
                status_dict = {}
                try:
                    cur.execute("""
                        SHOW GLOBAL STATUS WHERE Variable_name IN 
                        ('Threads_connected', 'Uptime', 'Queries');
                    """)
                    for row in cur.fetchall():
                        status_dict[row["Variable_name"]] = row["Value"]
                except Exception:
                    pass

                # Fetch max_connections server capacity
                max_conn = 151
                try:
                    cur.execute("SHOW VARIABLES LIKE 'max_connections';")
                    max_row = cur.fetchone()
                    if max_row and "Value" in max_row:
                        max_conn = int(max_row["Value"])
                except Exception:
                    pass

                connected_conn = int(status_dict.get("Threads_connected", 1))
                uptime = int(status_dict.get("Uptime", 0))

                # Database size from information_schema
                db_size = 0
                try:
                    cur.execute("""
                        SELECT COALESCE(SUM(data_length + index_length), 0) AS size 
                        FROM information_schema.tables 
                        WHERE table_schema = %s;
                    """, (database,))
                    size_row = cur.fetchone()
                    if size_row and "size" in size_row:
                        db_size = int(size_row["size"])
                except Exception:
                    pass

                # Version
                try:
                    cur.execute("SELECT VERSION() AS ver;")
                    ver_row = cur.fetchone()
                    version = f"MySQL {ver_row['ver']}" if ver_row else "MySQL"
                except Exception:
                    version = "MySQL"

            result.update({
                "status": "online",
                "latency_ms": latency_ms,
                "active_connections": connected_conn,
                "total_connections": max_conn,
                "database_size_bytes": db_size,
                "database_size_human": format_bytes(db_size),
                "version": version,
                "uptime_seconds": uptime,
                "error": None,
            })
        except Exception as e:
            self.close()
            result["status"] = "offline"
            err_msg = str(e).strip()
            if "1045" in err_msg:
                result["error"] = (
                    f"Access Denied (Error 1045): Invalid password for '{user}'@{host}. "
                    "Update config.yaml or set MYSQL_PASSWORD. "
                    "Also verify that the user has grants for '127.0.0.1'."
                )
            elif "2003" in err_msg:
                result["error"] = (
                    f"Connection Refused (Error 2003): Cannot reach MySQL on {host}:{port}. "
                    "Verify that MySQL service is running."
                )
            elif "1049" in err_msg:
                result["error"] = (
                    f"Unknown Database (Error 1049): Database '{database}' does not exist on MySQL server."
                )
            else:
                result["error"] = err_msg

        return result
