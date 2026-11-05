import os
import yaml
from typing import Dict, Any, Optional
from app.paths import get_config_path

DEFAULT_CONFIG: Dict[str, Any] = {
    "server": {
        "host": "127.0.0.1",
        "port": 8000,
        "poll_interval": 1.0,
        "history_buffer_size": 3600,
    },
    "databases": {
        "postgresql": {
            "enabled": True,
            "name": "PostgreSQL",
            "host": "127.0.0.1",
            "port": 5432,
            "user": "postgres",
            "password": "password",
            "database": "postgres",
            "timeout": 3.0,
        },
        "mysql": {
            "enabled": True,
            "name": "MySQL",
            "host": "127.0.0.1",
            "port": 3306,
            "user": "root",
            "password": "password",
            "database": "mysql",
            "timeout": 3.0,
        },
    },
    "alerts": {
        "duration_seconds": 90.0,
        "cpu_threshold_percent": 90.0,
        "ram_threshold_percent": 90.0,
        "disk_threshold_percent": 85.0,
        "swap_threshold_percent": 80.0,
        "db_latency_threshold_ms": 200.0,
    },
    "email": {
        "enabled": True,
        "provider": "mailjet",
        "api_key": "29d0b23ae14c1227ac447b6b3f9d7036",
        "secret_key": "cbedbdce0fedb02cc97043fc49262081",
        "sender_email": "vardhakpatel6@gmail.com",
        "sender_name": "PulseMon Alert Manager",
        "recipient_email": "",
        "send_on_resolved": True,
    },
}

def save_alert_thresholds(thresholds: Dict[str, float], config_path: Optional[str] = None) -> Dict[str, float]:
    """Saves updated alert thresholds to config.yaml while preserving comments in the rest of the file."""
    target_path = get_config_path(config_path)
    validated: Dict[str, float] = {}
    if "duration_seconds" in thresholds:
        validated["duration_seconds"] = round(max(5.0, min(600.0, float(thresholds["duration_seconds"]))), 1)
    if "cpu_threshold_percent" in thresholds:
        validated["cpu_threshold_percent"] = round(max(1.0, min(100.0, float(thresholds["cpu_threshold_percent"]))), 1)
    if "ram_threshold_percent" in thresholds:
        validated["ram_threshold_percent"] = round(max(1.0, min(100.0, float(thresholds["ram_threshold_percent"]))), 1)
    if "disk_threshold_percent" in thresholds:
        validated["disk_threshold_percent"] = round(max(1.0, min(100.0, float(thresholds["disk_threshold_percent"]))), 1)
    if "swap_threshold_percent" in thresholds:
        validated["swap_threshold_percent"] = round(max(1.0, min(100.0, float(thresholds["swap_threshold_percent"]))), 1)
    if "db_latency_threshold_ms" in thresholds:
        validated["db_latency_threshold_ms"] = round(max(5.0, min(5000.0, float(thresholds["db_latency_threshold_ms"]))), 1)

    if os.path.exists(target_path):
        try:
            with open(target_path, "r", encoding="utf-8") as f:
                content = f.read()

            # Merge with existing file thresholds so partial updates do not erase other limits
            existing_doc = yaml.safe_load(content) or {}
            merged_alerts = existing_doc.get("alerts", {}) if isinstance(existing_doc.get("alerts"), dict) else {}
            # Fill with defaults if missing
            for def_k, def_v in DEFAULT_CONFIG["alerts"].items():
                if def_k not in merged_alerts:
                    merged_alerts[def_k] = def_v
            merged_alerts.update(validated)

            import re
            alerts_lines = ["alerts:"]
            for k in ["duration_seconds", "cpu_threshold_percent", "ram_threshold_percent", "disk_threshold_percent", "swap_threshold_percent", "db_latency_threshold_ms"]:
                if k in merged_alerts:
                    alerts_lines.append(f"  {k}: {merged_alerts[k]}")
            new_alerts_text = "\n".join(alerts_lines)

            if re.search(r"^alerts:\s*", content, flags=re.MULTILINE):
                content = re.sub(r"^alerts:\s*\n(?:[ \t]+[^\n]*\n)*", new_alerts_text + "\n", content, flags=re.MULTILINE)
            else:
                content = content.rstrip() + "\n\n" + new_alerts_text + "\n"

            with open(target_path, "w", encoding="utf-8") as f:
                f.write(content.rstrip() + "\n")
        except Exception as e:
            print(f"[Warning] Failed to save updated alerts to {target_path}: {e}")

    return validated

def save_email_settings(settings: Dict[str, Any], config_path: Optional[str] = None) -> Dict[str, Any]:
    """Saves updated email notification settings to config.yaml."""
    target_path = get_config_path(config_path)
    validated: Dict[str, Any] = {}
    if "enabled" in settings:
        validated["enabled"] = bool(settings["enabled"])
    if "provider" in settings:
        validated["provider"] = str(settings["provider"]).strip()
    if "api_key" in settings and settings["api_key"]:
        validated["api_key"] = str(settings["api_key"]).strip()
    if "secret_key" in settings and settings["secret_key"]:
        validated["secret_key"] = str(settings["secret_key"]).strip()
    if "sender_email" in settings and settings["sender_email"]:
        validated["sender_email"] = str(settings["sender_email"]).strip()
    if "sender_name" in settings and settings["sender_name"]:
        validated["sender_name"] = str(settings["sender_name"]).strip()
    if "recipient_email" in settings:
        validated["recipient_email"] = str(settings["recipient_email"]).strip()
    if "send_on_resolved" in settings:
        validated["send_on_resolved"] = bool(settings["send_on_resolved"])

    if os.path.exists(target_path):
        try:
            with open(target_path, "r", encoding="utf-8") as f:
                content = f.read()

            existing_doc = yaml.safe_load(content) or {}
            merged_email = existing_doc.get("email", {}) if isinstance(existing_doc.get("email"), dict) else {}
            for def_k, def_v in DEFAULT_CONFIG["email"].items():
                if def_k not in merged_email:
                    merged_email[def_k] = def_v
            merged_email.update(validated)

            import re
            email_lines = ["email:"]
            for k in ["enabled", "provider", "api_key", "secret_key", "sender_email", "sender_name", "recipient_email", "send_on_resolved"]:
                if k in merged_email:
                    val = merged_email[k]
                    if isinstance(val, bool):
                        email_lines.append(f"  {k}: {'true' if val else 'false'}")
                    elif isinstance(val, (int, float)):
                        email_lines.append(f"  {k}: {val}")
                    else:
                        email_lines.append(f'  {k}: "{val}"')
            new_email_text = "\n".join(email_lines)

            if re.search(r"^email:\s*", content, flags=re.MULTILINE):
                content = re.sub(r"^email:\s*\n(?:[ \t]+[^\n]*\n)*", new_email_text + "\n", content, flags=re.MULTILINE)
            else:
                content = content.rstrip() + "\n\n" + new_email_text + "\n"

            with open(target_path, "w", encoding="utf-8") as f:
                f.write(content.rstrip() + "\n")
        except Exception as e:
            print(f"[Warning] Failed to save updated email settings to {target_path}: {e}")

    return validated

def load_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """Loads configuration from YAML file and applies environment variable overrides."""
    target_path = get_config_path(config_path)
    merged = {
        "server": DEFAULT_CONFIG["server"].copy(),
        "databases": {
            "postgresql": DEFAULT_CONFIG["databases"]["postgresql"].copy(),
            "mysql": DEFAULT_CONFIG["databases"]["mysql"].copy(),
        },
        "alerts": DEFAULT_CONFIG["alerts"].copy(),
        "email": DEFAULT_CONFIG["email"].copy(),
    }

    if os.path.exists(target_path):
        try:
            with open(target_path, "r", encoding="utf-8") as f:
                user_config = yaml.safe_load(f) or {}
                
            for key, value in user_config.items():
                if isinstance(value, dict) and key in merged and isinstance(merged[key], dict):
                    merged[key] = {**merged[key], **value}
                else:
                    merged[key] = value
        except Exception as e:
            print(f"[Warning] Failed to parse {target_path}: {e}. Falling back to default settings.")

    # Apply Environment Variable Overrides
    server_cfg = merged["server"]
    if "MONITOR_PORT" in os.environ:
        server_cfg["port"] = int(os.environ["MONITOR_PORT"])
    if "MONITOR_HOST" in os.environ:
        server_cfg["host"] = os.environ["MONITOR_HOST"]

    # MySQL overrides
    mysql_cfg = merged["databases"].get("mysql", {})
    if "MYSQL_HOST" in os.environ:
        mysql_cfg["host"] = os.environ["MYSQL_HOST"]
    if "MYSQL_PORT" in os.environ:
        mysql_cfg["port"] = int(os.environ["MYSQL_PORT"])
    if "MYSQL_USER" in os.environ:
        mysql_cfg["user"] = os.environ["MYSQL_USER"]
    if "MYSQL_PASSWORD" in os.environ:
        mysql_cfg["password"] = os.environ["MYSQL_PASSWORD"]
    if "MYSQL_DATABASE" in os.environ:
        mysql_cfg["database"] = os.environ["MYSQL_DATABASE"]
    if "MYSQL_ENABLED" in os.environ:
        mysql_cfg["enabled"] = os.environ["MYSQL_ENABLED"].lower() in ("true", "1", "yes")

    # PostgreSQL overrides
    pg_cfg = merged["databases"].get("postgresql", {})
    if "POSTGRES_HOST" in os.environ:
        pg_cfg["host"] = os.environ["POSTGRES_HOST"]
    if "POSTGRES_PORT" in os.environ:
        pg_cfg["port"] = int(os.environ["POSTGRES_PORT"])
    if "POSTGRES_USER" in os.environ:
        pg_cfg["user"] = os.environ["POSTGRES_USER"]
    if "POSTGRES_PASSWORD" in os.environ:
        pg_cfg["password"] = os.environ["POSTGRES_PASSWORD"]
    if "POSTGRES_DATABASE" in os.environ:
        pg_cfg["database"] = os.environ["POSTGRES_DATABASE"]
    if "POSTGRES_ENABLED" in os.environ:
        pg_cfg["enabled"] = os.environ["POSTGRES_ENABLED"].lower() in ("true", "1", "yes")

    # Email overrides
    email_cfg = merged.get("email", {})
    if "ALERT_RECIPIENT_EMAIL" in os.environ:
        email_cfg["recipient_email"] = os.environ["ALERT_RECIPIENT_EMAIL"]
    if "MAILJET_API_KEY" in os.environ:
        email_cfg["api_key"] = os.environ["MAILJET_API_KEY"]
    if "MAILJET_SECRET_KEY" in os.environ:
        email_cfg["secret_key"] = os.environ["MAILJET_SECRET_KEY"]
    if "ALERT_SENDER_EMAIL" in os.environ:
        email_cfg["sender_email"] = os.environ["ALERT_SENDER_EMAIL"]
    if "EMAIL_ALERTS_ENABLED" in os.environ:
        email_cfg["enabled"] = os.environ["EMAIL_ALERTS_ENABLED"].lower() in ("true", "1", "yes")

    return merged
