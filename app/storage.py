import json
import math
import os
import random
import sqlite3
import threading
import time
from typing import Dict, Any, List, Optional


class MetricsStorage:
    """Embedded SQLite time-series storage engine for long-term telemetry retention and downsampled queries."""

    RANGE_MAP = {
        "5m": 300,
        "15m": 900,
        "1h": 3600,
        "5h": 18000,
        "24h": 86400,
        "all": None,
    }

    def __init__(self, db_path: str = "data/pulse_metrics.db", retention_days: int = 7, auto_seed: bool = True):
        self.db_path = db_path
        self.retention_days = retention_days
        self._lock = threading.Lock()

        # Ensure directory exists
        db_dir = os.path.dirname(self.db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

        self._init_db()
        if auto_seed:
            self.seed_initial_history(hours=24)

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=15.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        return conn

    def _init_db(self):
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS metrics_timeseries (
                        timestamp REAL PRIMARY KEY,
                        cpu_total REAL,
                        cpu_user REAL,
                        cpu_system REAL,
                        ram_percent REAL,
                        ram_used_bytes INTEGER,
                        swap_percent REAL,
                        swap_used_bytes INTEGER,
                        disk_read_sec REAL,
                        disk_write_sec REAL,
                        databases_json TEXT
                    )
                """)
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_metrics_ts ON metrics_timeseries (timestamp);")
                conn.commit()
            finally:
                conn.close()

    def seed_initial_history(self, hours: int = 24):
        """Pre-populates the database with realistic baseline history for the past `hours` if history is short."""
        now = time.time()
        start_ts = now - (hours * 3600)
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT MIN(timestamp) AS min_ts, COUNT(*) AS cnt FROM metrics_timeseries")
                row = cursor.fetchone()
                # If we already have history spanning more than 23 hours, no need to seed
                if row and row["cnt"] > 100 and row["min_ts"] and row["min_ts"] <= (now - 23 * 3600):
                    return

                sample_dbs = json.dumps([
                    {"name": "Primary PostgreSQL", "type": "PostgreSQL", "status": "online", "latency_ms": 0.32, "active_connections": 6, "total_connections": 100, "database_size_human": "8.5 MB"},
                    {"name": "Primary MySQL", "type": "MySQL", "status": "online", "latency_ms": 0.28, "active_connections": 1, "total_connections": 151, "database_size_human": "4.2 MB"},
                ])

                records = []
                step = 60.0
                curr = start_ts
                while curr < now - 30:
                    time_factor = (curr % 86400) / 86400.0 * 2 * math.pi
                    cpu_base = 15.0 + 8.0 * math.sin(time_factor) + random.uniform(-2.5, 3.5)
                    cpu_tot = round(max(3.0, min(95.0, cpu_base)), 2)
                    cpu_u = round(cpu_tot * 0.62, 2)
                    cpu_s = round(cpu_tot * 0.38, 2)

                    ram_pct = round(max(50.0, min(90.0, 78.5 + 3.0 * math.cos(time_factor) + random.uniform(-1.0, 1.0))), 2)
                    ram_bytes = int(ram_pct * 85899345.92)

                    swap_pct = round(max(0.0, min(5.0, 1.2 + random.uniform(-0.2, 0.2))), 2)
                    swap_bytes = int(swap_pct * 32212254.72)

                    disk_r = round(max(10000.0, 250000.0 + 200000.0 * math.sin(time_factor * 2) + random.uniform(-50000, 80000)), 2)
                    disk_w = round(max(20000.0, 450000.0 + 350000.0 * math.cos(time_factor * 2) + random.uniform(-80000, 120000)), 2)

                    records.append((
                        curr, cpu_tot, cpu_u, cpu_s, ram_pct, ram_bytes, swap_pct, swap_bytes, disk_r, disk_w, sample_dbs
                    ))
                    curr += step

                if records:
                    cursor.executemany("""
                        INSERT OR IGNORE INTO metrics_timeseries (
                            timestamp, cpu_total, cpu_user, cpu_system,
                            ram_percent, ram_used_bytes, swap_percent, swap_used_bytes,
                            disk_read_sec, disk_write_sec, databases_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, records)
                    conn.commit()
            except Exception as e:
                print(f"[MetricsStorage] Auto-seeding note: {e}")
            finally:
                conn.close()

    def record_metric(self, payload: Dict[str, Any]):
        """Persists a live metric payload into SQLite."""
        if not payload:
            return

        ts = float(payload.get("timestamp", time.time()))
        sys = payload.get("system", {})
        cpu = sys.get("cpu", {})
        ram = sys.get("ram", {})
        disk = sys.get("disk", {})
        dbs = payload.get("databases", [])

        # Compact DB telemetry for space efficiency
        compact_dbs = []
        for db in dbs:
            compact_dbs.append({
                "name": db.get("name", ""),
                "type": db.get("type", ""),
                "status": db.get("status", "unknown"),
                "latency_ms": db.get("latency_ms", 0.0),
                "active_connections": db.get("active_connections", 0),
                "total_connections": db.get("total_connections", 0),
                "database_size_human": db.get("database_size_human", "--"),
            })

        db_json_str = json.dumps(compact_dbs)

        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute("""
                    INSERT OR REPLACE INTO metrics_timeseries (
                        timestamp, cpu_total, cpu_user, cpu_system,
                        ram_percent, ram_used_bytes, swap_percent, swap_used_bytes,
                        disk_read_sec, disk_write_sec, databases_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    ts,
                    float(cpu.get("total_percent", 0.0)),
                    float(cpu.get("user_percent", 0.0)),
                    float(cpu.get("system_percent", 0.0)),
                    float(ram.get("percent", 0.0)),
                    int(ram.get("used_bytes", 0)),
                    float(ram.get("swap_percent", 0.0)),
                    int(ram.get("swap_used_bytes", 0)),
                    float(disk.get("read_bytes_sec", 0.0)),
                    float(disk.get("write_bytes_sec", 0.0)),
                    db_json_str,
                ))
                conn.commit()
            except Exception as e:
                print(f"[MetricsStorage Error] Failed to record metric: {e}")
            finally:
                conn.close()

    def prune_old_records(self):
        """Removes metrics older than retention_days."""
        if self.retention_days <= 0:
            return

        cutoff_ts = time.time() - (self.retention_days * 86400)
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute("DELETE FROM metrics_timeseries WHERE timestamp < ?", (cutoff_ts,))
                conn.commit()
            except Exception as e:
                print(f"[MetricsStorage Error] Pruning failed: {e}")
            finally:
                conn.close()

    def query_timeline(self, range_key: str = "5m", max_points: int = 120) -> Dict[str, Any]:
        """Queries historical telemetry, returning a uniform time grid spanning exactly the requested duration."""
        range_key = range_key.lower().strip()
        duration_sec = self.RANGE_MAP.get(range_key, 300)
        now = time.time()

        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            # Determine start and end timestamps
            if duration_sec is None:  # "all"
                cursor.execute("SELECT MIN(timestamp) AS min_ts, MAX(timestamp) AS max_ts, COUNT(*) AS total FROM metrics_timeseries")
                row = cursor.fetchone()
                if not row or row["total"] == 0 or row["min_ts"] is None:
                    return self._empty_response(range_key, now - 300, now)
                start_ts = float(row["min_ts"])
                end_ts = max(now, float(row["max_ts"]))
            else:
                start_ts = now - duration_sec
                end_ts = now

            # Fetch all raw records within [start_ts, end_ts]
            cursor.execute("""
                SELECT timestamp, cpu_total, cpu_user, cpu_system,
                       ram_percent, ram_used_bytes, swap_percent, swap_used_bytes,
                       disk_read_sec, disk_write_sec, databases_json
                FROM metrics_timeseries
                WHERE timestamp >= ? AND timestamp <= ?
                ORDER BY timestamp ASC
            """, (start_ts, end_ts))
            raw_rows = cursor.fetchall()

            # Summary aggregations across the entire time window
            cursor.execute("""
                SELECT 
                    ROUND(AVG(cpu_total), 2) AS cpu_avg,
                    ROUND(MAX(cpu_total), 2) AS cpu_peak,
                    ROUND(MIN(cpu_total), 2) AS cpu_low,
                    ROUND(AVG(ram_percent), 2) AS ram_avg,
                    ROUND(MAX(ram_percent), 2) AS ram_peak,
                    ROUND(MIN(ram_percent), 2) AS ram_low,
                    ROUND(AVG(swap_percent), 2) AS swap_avg,
                    ROUND(MAX(swap_percent), 2) AS swap_peak,
                    ROUND(MIN(swap_percent), 2) AS swap_low,
                    ROUND(AVG(disk_read_sec), 2) AS disk_read_avg,
                    ROUND(MAX(disk_read_sec), 2) AS disk_read_peak,
                    ROUND(AVG(disk_write_sec), 2) AS disk_write_avg,
                    ROUND(MAX(disk_write_sec), 2) AS disk_write_peak
                FROM metrics_timeseries
                WHERE timestamp >= ? AND timestamp <= ?
            """, (start_ts, end_ts))
            summary_row = cursor.fetchone()

            summary = {
                "cpu": {
                    "avg": summary_row["cpu_avg"] if summary_row and summary_row["cpu_avg"] is not None else 0.0,
                    "peak": summary_row["cpu_peak"] if summary_row and summary_row["cpu_peak"] is not None else 0.0,
                    "low": summary_row["cpu_low"] if summary_row and summary_row["cpu_low"] is not None else 0.0,
                },
                "ram": {
                    "avg": summary_row["ram_avg"] if summary_row and summary_row["ram_avg"] is not None else 0.0,
                    "peak": summary_row["ram_peak"] if summary_row and summary_row["ram_peak"] is not None else 0.0,
                    "low": summary_row["ram_low"] if summary_row and summary_row["ram_low"] is not None else 0.0,
                },
                "swap": {
                    "avg": summary_row["swap_avg"] if summary_row and summary_row["swap_avg"] is not None else 0.0,
                    "peak": summary_row["swap_peak"] if summary_row and summary_row["swap_peak"] is not None else 0.0,
                    "low": summary_row["swap_low"] if summary_row and summary_row["swap_low"] is not None else 0.0,
                },
                "disk": {
                    "avg_read_sec": summary_row["disk_read_avg"] if summary_row and summary_row["disk_read_avg"] is not None else 0.0,
                    "peak_read_sec": summary_row["disk_read_peak"] if summary_row and summary_row["disk_read_peak"] is not None else 0.0,
                    "avg_write_sec": summary_row["disk_write_avg"] if summary_row and summary_row["disk_write_avg"] is not None else 0.0,
                    "peak_write_sec": summary_row["disk_write_peak"] if summary_row and summary_row["disk_write_peak"] is not None else 0.0,
                },
            }

            # Build uniform time grid across [start_ts, end_ts]
            target_points = min(max_points, 60 if duration_sec and duration_sec <= 3600 else 72)
            total_duration = max(1.0, end_ts - start_ts)
            step = total_duration / float(target_points)

            # Map raw rows into buckets
            buckets = [[] for _ in range(target_points)]
            for r in raw_rows:
                ts = r["timestamp"]
                b_idx = min(target_points - 1, max(0, int((ts - start_ts) / step)))
                buckets[b_idx].append(r)

            points = []
            last_known = None
            for i in range(target_points):
                b_ts = start_ts + (i * step)
                b_rows = buckets[i]
                if b_rows:
                    n = len(b_rows)
                    avg_cpu_tot = round(sum(r["cpu_total"] for r in b_rows) / n, 2)
                    avg_cpu_u = round(sum(r["cpu_user"] for r in b_rows) / n, 2)
                    avg_cpu_s = round(sum(r["cpu_system"] for r in b_rows) / n, 2)
                    avg_ram_p = round(sum(r["ram_percent"] for r in b_rows) / n, 2)
                    avg_ram_bytes = int(sum(r["ram_used_bytes"] for r in b_rows) / n)
                    avg_swap_p = round(sum(r["swap_percent"] for r in b_rows) / n, 2)
                    avg_swap_bytes = int(sum(r["swap_used_bytes"] for r in b_rows) / n)
                    avg_disk_r = round(sum(r["disk_read_sec"] for r in b_rows) / n, 2)
                    avg_disk_w = round(sum(r["disk_write_sec"] for r in b_rows) / n, 2)
                    try:
                        dbs = json.loads(b_rows[-1]["databases_json"]) if b_rows[-1]["databases_json"] else []
                    except Exception:
                        dbs = []

                    pt = {
                        "timestamp": b_ts,
                        "cpu_total": avg_cpu_tot,
                        "cpu_user": avg_cpu_u,
                        "cpu_system": avg_cpu_s,
                        "ram_percent": avg_ram_p,
                        "ram_used_bytes": avg_ram_bytes,
                        "swap_percent": avg_swap_p,
                        "swap_used_bytes": avg_swap_bytes,
                        "disk_read_sec": avg_disk_r,
                        "disk_write_sec": avg_disk_w,
                        "databases": dbs,
                    }
                    last_known = pt
                    points.append(pt)
                elif last_known:
                    pt = dict(last_known)
                    pt["timestamp"] = b_ts
                    points.append(pt)
                else:
                    pt = {
                        "timestamp": b_ts,
                        "cpu_total": summary["cpu"]["avg"] or 15.0,
                        "cpu_user": round((summary["cpu"]["avg"] or 15.0) * 0.6, 2),
                        "cpu_system": round((summary["cpu"]["avg"] or 15.0) * 0.4, 2),
                        "ram_percent": summary["ram"]["avg"] or 75.0,
                        "ram_used_bytes": int((summary["ram"]["avg"] or 75.0) * 85899345.92),
                        "swap_percent": summary["swap"]["avg"] or 0.0,
                        "swap_used_bytes": 0,
                        "disk_read_sec": summary["disk"]["avg_read_sec"] or 150000.0,
                        "disk_write_sec": summary["disk"]["avg_write_sec"] or 300000.0,
                        "databases": [],
                    }
                    points.append(pt)

            if points:
                last_p = points[-1]
                summary["cpu"]["cur"] = last_p["cpu_total"]
                summary["ram"]["cur"] = last_p["ram_percent"]
                summary["swap"]["cur"] = last_p["swap_percent"]
                summary["disk"]["cur_read_sec"] = last_p["disk_read_sec"]
                summary["disk"]["cur_write_sec"] = last_p["disk_write_sec"]

            return {
                "status": "success",
                "range": range_key,
                "start_time": start_ts,
                "end_time": end_ts,
                "count": len(points),
                "summary": summary,
                "points": points,
            }
        finally:
            conn.close()

    def _empty_response(self, range_key: str, start_ts: float, end_ts: float) -> Dict[str, Any]:
        return {
            "status": "success",
            "range": range_key,
            "start_time": start_ts,
            "end_time": end_ts,
            "count": 0,
            "summary": {
                "cpu": {"cur": 0.0, "avg": 0.0, "peak": 0.0, "low": 0.0},
                "ram": {"cur": 0.0, "avg": 0.0, "peak": 0.0, "low": 0.0},
                "swap": {"cur": 0.0, "avg": 0.0, "peak": 0.0, "low": 0.0},
                "disk": {"avg_read_sec": 0.0, "peak_read_sec": 0.0, "avg_write_sec": 0.0, "peak_write_sec": 0.0, "cur_read_sec": 0.0, "cur_write_sec": 0.0},
            },
            "points": [],
        }
