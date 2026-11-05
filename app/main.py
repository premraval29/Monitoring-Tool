import asyncio
import json
import logging
import os
import time
from collections import deque
from contextlib import asynccontextmanager
from typing import Dict, Any, List, Set, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from app.config import load_config
from app.paths import get_db_path, get_static_dir, is_frozen
from app.storage import MetricsStorage
from app.services.email_service import MailjetEmailService
from app.collectors import (
    SystemCollector,
    PostgresCollector,
    MySQLCollector,
    SQLiteCollector,
)

logger = logging.getLogger("pulsemon.main")

# Load configuration
config = load_config()
email_service = MailjetEmailService(config.get("email", {}))

# Data stores
storage_config = config.get("storage", {})
raw_db_path = storage_config.get("db_path")
resolved_db_path = get_db_path() if (is_frozen() or not raw_db_path) else raw_db_path
metrics_storage = MetricsStorage(
    db_path=resolved_db_path,
    retention_days=storage_config.get("retention_days", 7)
)
history_size = config.get("server", {}).get("history_buffer_size", 1800)
poll_interval: float = float(config.get("server", {}).get("poll_interval", 1.0))
interval_wake_event: asyncio.Event = asyncio.Event()

def set_poll_interval(new_interval: float) -> float:
    global poll_interval
    valid_interval = max(1.0, min(float(new_interval), 600.0))
    poll_interval = valid_interval
    interval_wake_event.set()
    return poll_interval
metrics_history: deque = deque(maxlen=history_size)
latest_metrics: Dict[str, Any] = {}
active_alerts: List[Dict[str, Any]] = []
active_alert_start_times: Dict[str, float] = {}

# Collectors initialization
system_collector = SystemCollector()
static_info = system_collector.get_static_info()

db_configs = config.get("databases", {})
db_collectors = []

if "postgresql" in db_configs and db_configs["postgresql"].get("enabled", True):
    db_collectors.append(PostgresCollector(db_configs["postgresql"]))

if "mysql" in db_configs and db_configs["mysql"].get("enabled", True):
    db_collectors.append(MySQLCollector(db_configs["mysql"]))

if "sqlite" in db_configs and db_configs["sqlite"].get("enabled", False):
    db_collectors.append(SQLiteCollector(db_configs["sqlite"]))

# Connected WebSocket clients
class ConnectionManager:
    def __init__(self):
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)

    async def broadcast(self, data: Dict[str, Any]):
        dead_connections = set()
        for connection in self.active_connections:
            try:
                await connection.send_json(data)
            except Exception:
                dead_connections.add(connection)
        for dead in dead_connections:
            self.active_connections.discard(dead)

manager = ConnectionManager()

class AlertStateManager:
    """Manages continuous threshold breach & recovery hysteresis state machine (default 90s)."""
    def __init__(self):
        self.items: Dict[str, Dict[str, Any]] = {}

    def update_item(
        self,
        key: str,
        source: str,
        is_breached: bool,
        level: str,
        breach_message: str,
        recovery_message: str,
        now: float,
        duration_seconds: float = 90.0,
    ) -> Optional[Dict[str, Any]]:
        item = self.items.get(key)
        if not item:
            item = {
                "key": key,
                "source": source,
                "state": "normal",
                "breach_start_time": 0.0,
                "fired_at": 0.0,
                "recovery_start_time": 0.0,
                "resolved_at": 0.0,
                "level": level if is_breached else "info",
                "message": breach_message if is_breached else "",
                "recovery_message": recovery_message,
                "dismissed": False,
            }
            self.items[key] = item

        if is_breached:
            item["level"] = level
            item["message"] = breach_message
        item["recovery_message"] = recovery_message

        state = item["state"]
        transition_event: Optional[str] = None

        if is_breached:
            if state == "normal":
                item["state"] = "pending_breach"
                item["breach_start_time"] = now
                item["recovery_start_time"] = 0.0
            elif state == "pending_breach":
                if (now - item["breach_start_time"]) >= duration_seconds:
                    item["state"] = "firing"
                    item["fired_at"] = now
                    item["recovery_start_time"] = 0.0
                    item["dismissed"] = False
                    transition_event = "firing"
            elif state == "pending_recovery":
                # Spiked back up before 90s recovery completed -> stay firing!
                item["state"] = "firing"
                item["recovery_start_time"] = 0.0
            elif state == "firing":
                pass
            elif state == "resolved":
                # Breached again after being resolved
                item["state"] = "pending_breach"
                item["breach_start_time"] = now
                item["recovery_start_time"] = 0.0
                item["dismissed"] = False
        else:
            # Healthy (under threshold)
            if state == "pending_breach":
                # Brief spike ended before 90s -> cancel
                item["state"] = "normal"
                item["breach_start_time"] = 0.0
            elif state == "firing":
                # Dropped under limit -> begin 90s recovery window!
                item["state"] = "pending_recovery"
                item["recovery_start_time"] = now
            elif state == "pending_recovery":
                if (now - item["recovery_start_time"]) >= duration_seconds:
                    item["state"] = "resolved"
                    item["resolved_at"] = now
                    item["recovery_start_time"] = 0.0
                    transition_event = "resolved"
            elif state == "resolved":
                pass
            elif state == "normal":
                pass

        return self.get_notification_for_item(item, now, duration_seconds, transition_event)

    def get_notification_for_item(
        self,
        item: Dict[str, Any],
        now: float,
        duration_seconds: float,
        transition_event: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        state = item["state"]
        if state in ("firing", "pending_recovery"):
            fired_at = item["fired_at"] or now
            notif = {
                "key": item["key"],
                "state": "firing",
                "source": item["source"],
                "level": item["level"],
                "message": item["message"],
                "timestamp": fired_at,
                "time_str": time.strftime("%H:%M:%S", time.localtime(fired_at)),
                "is_recovering": (state == "pending_recovery"),
                "recovery_seconds_left": max(0, int(duration_seconds - (now - item["recovery_start_time"]))) if state == "pending_recovery" else 0,
            }
            if transition_event:
                notif["transition_event"] = transition_event
            return notif
        elif state == "resolved" and not item["dismissed"]:
            resolved_at = item["resolved_at"] or now
            fired_at = item["fired_at"] or resolved_at
            active_duration = max(0, int(resolved_at - fired_at))
            notif = {
                "key": item["key"],
                "state": "resolved",
                "source": item["source"],
                "level": "resolved",
                "message": item["recovery_message"] or f"{item['source']} recovered below threshold.",
                "timestamp": resolved_at,
                "time_str": time.strftime("%H:%M:%S", time.localtime(resolved_at)),
                "fired_at": fired_at,
                "active_duration_seconds": active_duration,
            }
            if transition_event:
                notif["transition_event"] = transition_event
            return notif
        return None

    def clear_resolved(self, key: Optional[str] = None):
        for k, item in self.items.items():
            if key is None or k == key:
                if item["state"] == "resolved":
                    item["dismissed"] = True

    def reset_all(self):
        self.items.clear()

alert_state_manager = AlertStateManager()

async def _async_dispatch_email(alert_data: Dict[str, Any], is_resolved: bool, snapshot: Optional[Dict[str, Any]] = None):
    """Dispatches email notification asynchronously in worker thread to prevent blocking event loop."""
    try:
        if is_resolved:
            subject, html, text = email_service.format_resolution_email(alert_data, snapshot)
        else:
            subject, html, text = email_service.format_alert_email(alert_data, snapshot)
        await asyncio.to_thread(email_service.send_message, subject, html, text)
    except Exception as e:
        logger.error(f"Error dispatching email alert: {e}")

def evaluate_alerts(metrics: Dict[str, Any], now: Optional[float] = None) -> List[Dict[str, Any]]:
    """Evaluates threshold violations using 90-second sustained state machine."""
    current_time = time.time() if now is None else now
    alert_rules = config.get("alerts", {})
    duration_sec = float(alert_rules.get("duration_seconds", 90.0))

    cpu_limit = float(alert_rules.get("cpu_threshold_percent", 90.0))
    ram_limit = float(alert_rules.get("ram_threshold_percent", 90.0))
    disk_limit = float(alert_rules.get("disk_threshold_percent", 85.0))
    swap_limit = float(alert_rules.get("swap_threshold_percent", 80.0))
    db_latency_limit = float(alert_rules.get("db_latency_threshold_ms", 200.0))

    notifications = []

    # 1. CPU
    cpu_val = metrics.get("system", {}).get("cpu", {}).get("total_percent", 0.0)
    cpu_breached = cpu_val >= cpu_limit
    notif = alert_state_manager.update_item(
        key="CPU",
        source="CPU",
        is_breached=cpu_breached,
        level="warning" if cpu_val < 95 else "danger",
        breach_message=f"High CPU utilization: {cpu_val}% (Threshold: {cpu_limit}%)",
        recovery_message=f"CPU utilization resolved: {cpu_val}% (under limit {cpu_limit}%)",
        now=current_time,
        duration_seconds=duration_sec,
    )
    if notif:
        notifications.append(notif)

    # 2. RAM
    ram_val = metrics.get("system", {}).get("ram", {}).get("percent", 0.0)
    ram_breached = ram_val >= ram_limit
    notif = alert_state_manager.update_item(
        key="Memory",
        source="Memory",
        is_breached=ram_breached,
        level="warning" if ram_val < 95 else "danger",
        breach_message=f"High RAM usage: {ram_val}% (Threshold: {ram_limit}%)",
        recovery_message=f"RAM usage resolved: {ram_val}% (under limit {ram_limit}%)",
        now=current_time,
        duration_seconds=duration_sec,
    )
    if notif:
        notifications.append(notif)

    # 3. Swap
    swap_val = metrics.get("system", {}).get("ram", {}).get("swap_percent", 0.0)
    swap_breached = swap_val >= swap_limit
    notif = alert_state_manager.update_item(
        key="Swap Memory",
        source="Swap Memory",
        is_breached=swap_breached,
        level="warning" if swap_val < 95 else "danger",
        breach_message=f"High Swap usage: {swap_val}% (Threshold: {swap_limit}%)",
        recovery_message=f"Swap usage resolved: {swap_val}% (under limit {swap_limit}%)",
        now=current_time,
        duration_seconds=duration_sec,
    )
    if notif:
        notifications.append(notif)

    # 4. Disks
    for part in metrics.get("system", {}).get("disk", {}).get("partitions", []):
        d_val = part.get("percent", 0.0)
        mount = part.get("mount", "")
        disk_key = f"Disk ({mount})"
        d_breached = d_val >= disk_limit
        notif = alert_state_manager.update_item(
            key=disk_key,
            source=disk_key,
            is_breached=d_breached,
            level="warning" if d_val < 95 else "danger",
            breach_message=f"Partition space critical: {d_val}% (Threshold: {disk_limit}%)",
            recovery_message=f"Partition space resolved: {d_val}% (under limit {disk_limit}%)",
            now=current_time,
            duration_seconds=duration_sec,
        )
        if notif:
            notifications.append(notif)

    # 5. Databases
    for db in metrics.get("databases", []):
        if db.get("enabled"):
            db_name = db.get("name", "Unknown")
            offline_key = f"Database ({db_name})"
            is_offline = (db.get("status") == "offline")
            notif = alert_state_manager.update_item(
                key=offline_key,
                source=offline_key,
                is_breached=is_offline,
                level="danger",
                breach_message=f"{db.get('type')} connection failed: {db.get('error', 'Unreachable')}",
                recovery_message=f"{db.get('type')} connection resolved: restored to online",
                now=current_time,
                duration_seconds=duration_sec,
            )
            if notif:
                notifications.append(notif)

            latency_key = f"Database Latency ({db_name})"
            lat = db.get("latency_ms")
            is_high_lat = (lat is not None and lat >= db_latency_limit)
            notif = alert_state_manager.update_item(
                key=latency_key,
                source=latency_key,
                is_breached=is_high_lat,
                level="warning",
                breach_message=f"High query latency: {lat} ms (Threshold: {db_latency_limit} ms)",
                recovery_message=f"Query latency resolved: {lat} ms (under limit {db_latency_limit} ms)",
                now=current_time,
                duration_seconds=duration_sec,
            )
            if notif:
                notifications.append(notif)

    # Dispatch email alerts for transition edges (non-blocking)
    for notif in notifications:
        event = notif.get("transition_event")
        if event in ("firing", "resolved"):
            if event == "resolved" and not email_service.send_on_resolved:
                continue
            try:
                loop = asyncio.get_running_loop()
                if loop and loop.is_running():
                    asyncio.create_task(_async_dispatch_email(notif, (event == "resolved"), metrics))
            except RuntimeError:
                pass

    return notifications

async def metrics_poller_task():
    """Background asynchronous task that gathers metrics at dynamic poll_interval with drift correction."""
    global latest_metrics, active_alerts, poll_interval
    import time

    while True:
        try:
            next_tick = time.monotonic() + poll_interval

            # 1. Run system metrics collection in worker thread to prevent event loop blocking
            sys_metrics = await asyncio.to_thread(system_collector.collect)

            # 2. Collect DB metrics concurrently with timeout safeguard
            db_tasks = [asyncio.to_thread(collector.collect) for collector in db_collectors]
            try:
                db_metrics = await asyncio.wait_for(
                    asyncio.gather(*db_tasks, return_exceptions=True),
                    timeout=max(0.8, poll_interval * 0.9)
                )
            except asyncio.TimeoutError:
                db_metrics = [
                    {"name": c.name, "type": getattr(c, "type", "DB"), "status": "offline", "error": "Query timed out (>800ms)"}
                    for c in db_collectors
                ]

            clean_db_metrics = [
                m if isinstance(m, dict) else {"name": "Error", "status": "offline", "error": str(m)}
                for m in db_metrics
            ]

            payload = {
                "timestamp": sys_metrics["timestamp"],
                "system": sys_metrics,
                "databases": clean_db_metrics,
                "poll_interval": poll_interval,
            }

            # Evaluate alerts
            current_alerts = evaluate_alerts(payload)
            payload["alerts"] = current_alerts

            latest_metrics = payload
            active_alerts = current_alerts
            metrics_history.append(payload)

            # Persist to time-series storage non-blockingly
            try:
                await asyncio.to_thread(metrics_storage.record_metric, payload)
            except Exception as se:
                print(f"[Storage error]: {se}")

            # Broadcast to WebSockets
            await manager.broadcast({
                "type": "METRIC_UPDATE",
                "data": payload
            })

        except Exception as e:
            print(f"[Error in poller]: {e}")

        # Sleep with immediate early wake-up if user changes update cadence
        sleep_duration = max(0.0, next_tick - time.monotonic())
        try:
            interval_wake_event.clear()
            await asyncio.wait_for(interval_wake_event.wait(), timeout=sleep_duration)
        except asyncio.TimeoutError:
            pass

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: prune old records and launch poller
    try:
        await asyncio.to_thread(metrics_storage.prune_old_records)
    except Exception:
        pass
    poller = asyncio.create_task(metrics_poller_task())
    yield
    # Shutdown
    poller.cancel()

app = FastAPI(title="PC & Database Monitoring Tool", lifespan=lifespan)

# Static files mounting
static_dir = get_static_dir()
if not os.path.exists(static_dir):
    os.makedirs(static_dir, exist_ok=True)

app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/")
async def get_index():
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return JSONResponse({"status": "Dashboard UI is preparing..."})

@app.get("/.well-known/appspecific/com.chrome.devtools.json", include_in_schema=False)
async def chrome_devtools_endpoint():
    """Silently acknowledge Chrome DevTools auto-discovery probe."""
    return JSONResponse(content={})

@app.get("/favicon.ico", include_in_schema=False)
async def favicon_endpoint():
    """Silently handle browser favicon probe."""
    return Response(status_code=204)

@app.get("/api/system/info")
async def get_system_info():
    return {
        "status": "success",
        "data": static_info
    }

@app.get("/api/metrics/current")
async def get_current_metrics():
    return {
        "status": "success",
        "data": latest_metrics
    }

@app.get("/api/metrics/history")
async def get_metrics_history(limit: int = 100):
    limit = min(max(1, limit), len(metrics_history))
    items = list(metrics_history)[-limit:]
    return {
        "status": "success",
        "count": len(items),
        "data": items
    }

@app.get("/api/metrics/timeline")
async def get_metrics_timeline(range: str = "5m", max_points: int = 120):
    """Returns bucket-downsampled historical metrics for analytics modal."""
    data = await asyncio.to_thread(metrics_storage.query_timeline, range, max_points)
    return data

@app.post("/api/alerts/clear-resolved")
async def clear_resolved_alerts(data: Dict[str, Any] = None):
    key = data.get("key") if data else None
    alert_state_manager.clear_resolved(key)
    global active_alerts, latest_metrics
    if latest_metrics:
        active_alerts = evaluate_alerts(latest_metrics)
        latest_metrics["alerts"] = active_alerts
        await manager.broadcast({
            "type": "ALERTS_CONFIG_UPDATE",
            "alerts": config["alerts"],
            "active_alerts": active_alerts
        })
    return {"status": "success", "alerts": active_alerts}

@app.get("/api/alerts")
async def get_alerts():
    return {
        "status": "success",
        "alerts": active_alerts
    }

@app.get("/api/settings/interval")
async def get_interval():
    return {
        "status": "success",
        "poll_interval": poll_interval
    }

@app.post("/api/settings/interval")
async def update_interval(data: Dict[str, Any]):
    try:
        req_val = float(data.get("interval", 1.0))
        updated = set_poll_interval(req_val)
        await manager.broadcast({
            "type": "INTERVAL_UPDATE",
            "interval": updated,
        })
        return {
            "status": "success",
            "poll_interval": updated
        }
    except Exception as e:
        return JSONResponse(status_code=400, content={"status": "error", "message": str(e)})

@app.get("/api/settings/alerts")
async def get_alert_settings():
    return {
        "status": "success",
        "alerts": config.get("alerts", {})
    }

@app.post("/api/settings/alerts")
async def update_alert_settings(data: Dict[str, Any]):
    global active_alerts, latest_metrics
    try:
        from app.config import save_alert_thresholds
        saved = save_alert_thresholds(data)
        config["alerts"].update(saved)

        # Immediate re-evaluation with latest metrics
        if latest_metrics:
            active_alerts = evaluate_alerts(latest_metrics)
            latest_metrics["alerts"] = active_alerts
        else:
            active_alerts = []

        # Broadcast ALERTS_CONFIG_UPDATE and immediate METRIC_UPDATE to all connected clients
        await manager.broadcast({
            "type": "ALERTS_CONFIG_UPDATE",
            "alerts": config["alerts"],
            "active_alerts": active_alerts
        })
        if latest_metrics:
            await manager.broadcast({
                "type": "METRIC_UPDATE",
                "data": latest_metrics
            })

        return {
            "status": "success",
            "alerts": config["alerts"],
            "active_alerts": active_alerts
        }
    except Exception as e:
        return JSONResponse(status_code=400, content={"status": "error", "message": str(e)})

@app.get("/api/settings/email")
async def get_email_settings():
    return {
        "status": "success",
        "email": {
            "enabled": email_service.enabled,
            "provider": "mailjet",
            "api_key": email_service.api_key,
            "secret_key": email_service.secret_key,
            "sender_email": email_service.sender_email,
            "sender_name": email_service.sender_name,
            "recipient_email": email_service.recipient_email,
            "send_on_resolved": email_service.send_on_resolved,
        }
    }

@app.post("/api/settings/email")
async def update_email_settings(data: Dict[str, Any]):
    try:
        from app.config import save_email_settings
        saved = save_email_settings(data)
        if "email" not in config:
            config["email"] = {}
        config["email"].update(saved)
        email_service.update_config(config["email"])
        return {
            "status": "success",
            "message": "Email notification settings saved successfully.",
            "email": {
                "enabled": email_service.enabled,
                "provider": "mailjet",
                "api_key": email_service.api_key,
                "secret_key": email_service.secret_key,
                "sender_email": email_service.sender_email,
                "sender_name": email_service.sender_name,
                "recipient_email": email_service.recipient_email,
                "send_on_resolved": email_service.send_on_resolved,
            }
        }
    except Exception as e:
        return JSONResponse(status_code=400, content={"status": "error", "message": str(e)})

@app.post("/api/alerts/test-email")
async def send_test_email_endpoint(data: Optional[Dict[str, Any]] = None):
    try:
        recipient = (data or {}).get("recipient_email") if data else None
        res = await asyncio.to_thread(email_service.send_test_email, recipient)
        status_code = 200 if res.get("status") == "success" else 400
        return JSONResponse(status_code=status_code, content=res)
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})

@app.websocket("/ws/live")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    # Immediately send system info and latest metrics on connect
    if latest_metrics:
        # Send up to 300 data points (5 minutes of live history buffer)
        history_pts = list(metrics_history)[-300:]
        if len(history_pts) < 60:
            try:
                tl = metrics_storage.query_timeline("5m", 300)
                if tl and tl.get("points"):
                    history_pts = tl["points"]
            except Exception:
                pass

        await websocket.send_json({
            "type": "INITIAL_STATE",
            "system_info": static_info,
            "latest": latest_metrics,
            "history": history_pts,
            "poll_interval": poll_interval,
            "alert_thresholds": config.get("alerts", {}),
        })
    try:
        while True:
            # Keep connection alive & handle incoming pings or commands
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_json({"type": "PONG"})
            elif data.startswith("{"):
                try:
                    msg = json.loads(data)
                    if msg.get("type") == "SET_INTERVAL":
                        req_val = float(msg.get("interval", 1.0))
                        updated = set_poll_interval(req_val)
                        await manager.broadcast({
                            "type": "INTERVAL_UPDATE",
                            "interval": updated,
                        })
                except Exception:
                    pass
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)

