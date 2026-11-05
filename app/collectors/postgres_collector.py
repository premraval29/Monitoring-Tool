import time
from typing import Dict, Any
from app.collectors.base_db import BaseDatabaseCollector
from app.collectors.system_collector import format_bytes

try:
    import psycopg2
except ImportError:
    psycopg2 = None

class PostgresCollector(BaseDatabaseCollector):
    def __init__(self, config: Dict[str, Any]):
        super().__init__(name=config.get("name", "PostgreSQL"), config=config)
        self.conn = None

    def _get_connection(self, host: str, port: int, user: str, password: str, database: str, timeout: int):
        """Ensures an active, healthy PostgreSQL connection, reconnecting if disconnected."""
        if self.conn is not None:
            try:
                if self.conn.closed == 0:
                    with self.conn.cursor() as cur:
                        cur.execute("/* ping */")
                    return self.conn
            except Exception:
                try:
                    self.conn.close()
                except Exception:
                    pass
                self.conn = None

        self.conn = psycopg2.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            dbname=database,
            connect_timeout=timeout,
        )
        self.conn.autocommit = True
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
        port = int(self.config.get("port", 5432))
        user = self.config.get("user", "postgres")
        password = self.config.get("password", "")
        database = self.config.get("database", "postgres")
        timeout = int(self.timeout)

        result: Dict[str, Any] = {
            "name": self.name,
            "type": "PostgreSQL",
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
            "error": None,
        }

        if not self.enabled:
            result["status"] = "disabled"
            return result

        if psycopg2 is None:
            result["error"] = "psycopg2 library not installed"
            return result

        try:
            conn = self._get_connection(host, port, user, password, database, timeout)
            with conn.cursor() as cur:
                # Measure true query execution latency
                t0 = time.perf_counter()
                cur.execute("SELECT 1;")
                cur.fetchone()
                latency_ms = round((time.perf_counter() - t0) * 1000, 2)

                # Database size
                try:
                    cur.execute("SELECT pg_database_size(current_database());")
                    size_row = cur.fetchone()
                    db_size = size_row[0] if size_row else 0
                except Exception:
                    db_size = 0

                # Connection stats & Max connections limit
                active_conn = 1
                total_conn = 100
                try:
                    cur.execute("SELECT count(*) FROM pg_stat_activity;")
                    conn_row = cur.fetchone()
                    if conn_row:
                        active_conn = int(conn_row[0])
                except Exception:
                    pass

                try:
                    cur.execute("SHOW max_connections;")
                    max_row = cur.fetchone()
                    if max_row:
                        total_conn = int(max_row[0])
                except Exception:
                    pass

                # Version
                try:
                    cur.execute("SHOW server_version;")
                    ver_row = cur.fetchone()
                    version = f"PostgreSQL {ver_row[0]}" if ver_row else "PostgreSQL"
                except Exception:
                    version = "PostgreSQL"

            result.update({
                "status": "online",
                "latency_ms": latency_ms,
                "active_connections": active_conn,
                "total_connections": total_conn,
                "database_size_bytes": db_size,
                "database_size_human": format_bytes(db_size),
                "version": version,
                "error": None,
            })
        except Exception as e:
            self.close()
            result["status"] = "offline"
            err_msg = str(e).strip()
            if "password authentication failed" in err_msg:
                result["error"] = (
                    f"Authentication Failed: Invalid password for '{user}'@{host}. "
                    "Check config.yaml or set POSTGRES_PASSWORD."
                )
            elif "Connection refused" in err_msg or "Is the server running" in err_msg or "Operation not permitted" in err_msg:
                result["error"] = (
                    f"Connection Refused: Cannot reach PostgreSQL on {host}:{port}. "
                    "Ensure PostgreSQL server is running and accepting TCP connections."
                )
            elif "does not exist" in err_msg and "database" in err_msg:
                result["error"] = (
                    f"Unknown Database: Database '{database}' does not exist on PostgreSQL server."
                )
            else:
                result["error"] = err_msg

        return result
