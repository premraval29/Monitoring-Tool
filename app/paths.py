import os
import sys
import shutil
import platform
from pathlib import Path

def is_frozen() -> bool:
    """Returns True if the application is running inside a PyInstaller frozen bundle."""
    return getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")

def get_bundled_dir() -> Path:
    """Returns the base directory for bundled static assets and templates."""
    if is_frozen():
        return Path(sys._MEIPASS)
    # Repository root during local development
    return Path(__file__).resolve().parent.parent

def get_app_data_dir() -> Path:
    """
    Returns the persistent application data directory for the current OS.
    When running in development (not frozen) and PULSEMON_USE_APPDATA is not set,
    falls back to the current repository directory for developer convenience.
    """
    if not is_frozen() and os.environ.get("PULSEMON_USE_APPDATA") != "1":
        # Development mode: use repository root
        dev_dir = Path(__file__).resolve().parent.parent
        (dev_dir / "data").mkdir(parents=True, exist_ok=True)
        return dev_dir

    system = platform.system()
    if system == "Windows":
        app_data = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
        if app_data:
            base_dir = Path(app_data) / "PulseMon"
        else:
            base_dir = Path.home() / "AppData" / "Roaming" / "PulseMon"
    elif system == "Darwin":
        base_dir = Path.home() / "Library" / "Application Support" / "PulseMon"
    else:
        # Linux and other Unixes: XDG compliant
        xdg_data = os.environ.get("XDG_DATA_HOME")
        if xdg_data:
            base_dir = Path(xdg_data) / "PulseMon"
        else:
            base_dir = Path.home() / ".local" / "share" / "PulseMon"

    try:
        base_dir.mkdir(parents=True, exist_ok=True)
        (base_dir / "data").mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return base_dir

def get_config_path(custom_path: str = None) -> str:
    """
    Resolves the persistent config.yaml path.
    If running as a frozen app and no user config exists in AppData, copies the bundled default config.yaml.
    """
    if custom_path:
        return str(Path(custom_path).resolve())

    app_data = get_app_data_dir()
    user_config_path = app_data / "config.yaml"

    if not user_config_path.exists():
        # Copy bundled default config if available
        bundled_config = get_bundled_dir() / "config.yaml"
        if bundled_config.exists():
            try:
                shutil.copy2(bundled_config, user_config_path)
            except Exception:
                pass

    return str(user_config_path)

def get_db_path() -> str:
    """Returns the persistent SQLite telemetry database path."""
    app_data = get_app_data_dir()
    db_file = app_data / "data" / "pulse_metrics.db"
    return str(db_file)

def get_static_dir() -> str:
    """Returns the absolute path to the static web dashboard assets."""
    static_path = get_bundled_dir() / "app" / "static"
    return str(static_path)
