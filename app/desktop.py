import sys
import time
import socket
import logging
import threading
import urllib.request
import urllib.error
from typing import Optional

from app.main import app

logger = logging.getLogger("pulsemon.desktop")

def find_free_port(preferred_port: Optional[int] = None) -> int:
    """Finds an available local port on 127.0.0.1. Tries preferred_port first if given."""
    if preferred_port:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", preferred_port))
                return preferred_port
        except OSError:
            pass

    # Pick an ephemeral OS-assigned port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]

def wait_for_server(url: str, timeout: float = 12.0) -> bool:
    """Waits until the internal loopback server is ready to accept requests."""
    start_time = time.monotonic()
    probe_url = f"{url.rstrip('/')}/api/metrics/current"
    while time.monotonic() - start_time < timeout:
        try:
            with urllib.request.urlopen(probe_url, timeout=0.8) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(0.1)
    return False

def launch_desktop(host: str = "127.0.0.1", port: Optional[int] = None) -> int:
    """
    Launches PulseMon as a native desktop application window.
    Runs internal server silently on loopback without exposing localhost to the user.
    """
    import uvicorn

    active_port = find_free_port(port)
    server_url = f"http://{host}:{active_port}"

    # Suppress verbose Uvicorn access logging in desktop app mode
    server_config = uvicorn.Config(
        app,
        host=host,
        port=active_port,
        log_level="error",
        log_config=None,  # Bypasses Uvicorn colourized stream formatters in windowed GUI mode
        access_log=False,
        reload=False,
    )
    server = uvicorn.Server(server_config)

    server_thread = threading.Thread(target=server.run, daemon=True, name="PulseMon-Server")
    server_thread.start()

    # Wait for server readiness
    if not wait_for_server(server_url):
        logger.error("Internal server failed to initialize within timeout.")
        server.should_exit = True
        return 1

    # Native desktop GUI window presentation
    try:
        import webview
        # Create native OS desktop window (Edge WebView2 on Windows, WKWebView on Mac, WebKitGTK on Linux)
        window = webview.create_window(
            title="PulseMon — System & Database Monitor",
            url=server_url,
            width=1280,
            height=820,
            min_size=(960, 640),
            resizable=True,
            text_select=True,
            background_color="#0b0f19",
        )
        # Blocks until the user closes the window
        webview.start(debug=False)
    except ImportError:
        # Fallback if pywebview is not installed in the current environment
        print("[PulseMon Desktop] Note: 'pywebview' is not installed.")
        print(f"[PulseMon Desktop] Serving monitoring dashboard at {server_url}")
        import webbrowser
        webbrowser.open(server_url)
        try:
            while server_thread.is_alive():
                time.sleep(1)
        except KeyboardInterrupt:
            pass
    finally:
        # User closed window: clean shutdown of background server and metric collectors
        server.should_exit = True
        server_thread.join(timeout=2.0)

    return 0

if __name__ == "__main__":
    sys.exit(launch_desktop())

