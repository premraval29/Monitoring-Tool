#!/usr/bin/env python3
import sys
import argparse
import platform
import uvicorn
from app.config import load_config
from app.paths import is_frozen
from app.collectors import PostgresCollector, MySQLCollector
from app.desktop import launch_desktop

def run_db_test(target: str = "all"):
    """Runs a standalone connection probe for configured databases."""
    config = load_config()
    db_configs = config.get("databases", {})

    print("\n" + "=" * 65)
    print("  PulseMon Database Connection Diagnostics")
    print("=" * 65)

    targets_to_test = []
    if target in ("all", "mysql"):
        if "mysql" in db_configs:
            targets_to_test.append(("MySQL", MySQLCollector(db_configs["mysql"])))
    if target in ("all", "postgresql", "postgres"):
        if "postgresql" in db_configs:
            targets_to_test.append(("PostgreSQL", PostgresCollector(db_configs["postgresql"])))

    if not targets_to_test:
        print(f"[!] No database configured matching '{target}'. Check config.yaml.")
        return 1

    overall_success = True

    for label, collector in targets_to_test:
        print(f"\n[*] Probing {label} ({collector.config.get('user')}@{collector.config.get('host')}:{collector.config.get('port')})...")
        res = collector.collect()

        if res["status"] == "online":
            print(f"    ✔ Connection SUCCESSFUL")
            print(f"    • Status        : {res['status'].upper()}")
            print(f"    • Latency       : {res['latency_ms']} ms")
            print(f"    • Server Engine : {res['version']}")
            print(f"    • Active Conns  : {res['active_connections']} / {res['total_connections']}")
            print(f"    • Database Size : {res['database_size_human']}")
        elif res["status"] == "disabled":
            print(f"    - {label} is DISABLED in config.yaml")
        else:
            overall_success = False
            print(f"    ✖ Connection FAILED")
            print(f"    • Status        : {res['status'].upper()}")
            print(f"    • Diagnostic    : {res['error']}")

    print("\n" + "=" * 65 + "\n")
    return 0 if overall_success else 1

def main():
    parser = argparse.ArgumentParser(description="PulseMon — PC & Database Monitoring Application")
    parser.add_argument(
        "--test-db",
        choices=["all", "mysql", "postgresql"],
        nargs="?",
        const="all",
        help="Test database connection without starting the server (e.g. --test-db mysql)",
    )
    parser.add_argument(
        "--cli",
        "--server",
        action="store_true",
        help="Run as headless background server in terminal (without native desktop window)",
    )
    parser.add_argument(
        "--host",
        type=str,
        default=None,
        help="Custom bind host (CLI mode only)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Custom port number",
    )
    args = parser.parse_args()

    if args.test_db:
        sys.exit(run_db_test(args.test_db))

    config = load_config()
    server_cfg = config.get("server", {})
    host = args.host or server_cfg.get("host", "127.0.0.1")
    port = args.port or int(server_cfg.get("port", 8000))

    # If running as a desktop app (default or frozen bundle)
    if not args.cli:
        sys.exit(launch_desktop(host="127.0.0.1", port=args.port))

    # Headless CLI / Server mode
    os_name = platform.system()
    print("=" * 60)
    print("  PulseMon — PC & Database Monitoring Tool (Headless Mode)")
    print("=" * 60)
    print(f"  • Operating System : {os_name} ({platform.release()})")
    print(f"  • Python Version   : {platform.python_version()}")
    print(f"  • Web Dashboard    : http://{host}:{port}")
    print(f"  • API Base         : http://{host}:{port}/api/metrics/current")
    print(f"  • WebSocket Stream : ws://{host}:{port}/ws/live")
    print("=" * 60)
    print("  Press Ctrl+C to terminate the monitoring server.")
    print("=" * 60)

    from app.main import app
    uvicorn.run(
        app,
        host=host,
        port=port,
        reload=False,
        log_level="info",
    )

if __name__ == "__main__":
    main()
