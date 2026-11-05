import unittest
import asyncio
from app.config import load_config
from app.collectors.system_collector import (
    SystemCollector,
    format_bytes,
    format_uptime,
    format_disk_bytes,
    format_disk_rate,
)
from app.collectors.postgres_collector import PostgresCollector
from app.collectors.mysql_collector import MySQLCollector
from app.main import (
    evaluate_alerts,
    get_system_info,
    get_current_metrics,
    get_alerts,
    get_index,
    chrome_devtools_endpoint,
    favicon_endpoint,
    get_interval,
    update_interval,
    set_poll_interval,
    get_metrics_timeline,
    get_alert_settings,
    update_alert_settings,
    clear_resolved_alerts,
    alert_state_manager,
)

class TestMonitoringTool(unittest.TestCase):
    def test_config_loader(self):
        cfg = load_config("config.yaml")
        self.assertIn("server", cfg)
        self.assertIn("databases", cfg)
        self.assertIn("alerts", cfg)
        self.assertEqual(cfg["server"]["port"], 8000)
        self.assertEqual(cfg["server"]["poll_interval"], 1.0)

    def test_format_helpers(self):
        self.assertEqual(format_bytes(1024), "1.0 KB")
        self.assertEqual(format_bytes(1024 * 1024 * 5), "5.0 MB")
        self.assertEqual(format_bytes(1024 * 1024 * 1024 * 2), "2.0 GB")
        self.assertIn("m", format_uptime(125))

        # Disk helpers: SI base-1000 for macOS vs binary base-1024 for Linux/Windows
        self.assertEqual(format_disk_bytes(1000 * 1000 * 1000 * 361.94, is_mac=True), "361.94 GB")
        self.assertEqual(format_disk_bytes(1000 * 1000 * 1000 * 1000 * 1.06, is_mac=True), "1.06 TB")
        self.assertEqual(format_disk_bytes(1024 * 1024 * 1024 * 256, is_mac=False), "256.00 GB")
        self.assertEqual(format_disk_rate(1500000, is_mac=True), "1.5 MB/s")
        self.assertEqual(format_disk_rate(1024 * 1024 * 2, is_mac=False), "2.0 MB/s")

    def test_system_collector(self):
        collector = SystemCollector()
        info = collector.get_static_info()
        self.assertIn("hostname", info)
        self.assertIn("os", info)
        self.assertIn("architecture", info)
        self.assertIn("cpu_brand", info)
        self.assertIsInstance(info["cpu_brand"], str)
        self.assertGreater(len(info["cpu_brand"]), 0)
        self.assertGreater(info["cpu_logical_cores"], 0)

        metrics = collector.collect()
        self.assertIn("timestamp", metrics)
        self.assertIn("cpu", metrics)
        self.assertIn("ram", metrics)
        self.assertIn("disk", metrics)

        # CPU Activity Monitor fields
        self.assertIn("user_percent", metrics["cpu"])
        self.assertIn("system_percent", metrics["cpu"])
        self.assertIn("idle_percent", metrics["cpu"])
        self.assertIsInstance(metrics["cpu"]["total_percent"], (int, float))

        # RAM Activity Monitor fields
        self.assertIn("app_memory_human", metrics["ram"])
        self.assertIn("wired_memory_human", metrics["ram"])
        self.assertIn("compressed_memory_human", metrics["ram"])
        self.assertIn("cached_memory_human", metrics["ram"])
        self.assertIn("memory_pressure", metrics["ram"])
        self.assertIn("swap_used_human", metrics["ram"])
        self.assertIsInstance(metrics["ram"]["percent"], (int, float))

        # Disks & I/O
        self.assertIn("read_iops", metrics["disk"])
        self.assertIn("write_iops", metrics["disk"])
        self.assertIn("total_read_human", metrics["disk"])
        self.assertIn("total_write_human", metrics["disk"])
        self.assertGreaterEqual(len(metrics["disk"]["partitions"]), 0)
        if metrics["disk"]["partitions"]:
            self.assertIn("name", metrics["disk"]["partitions"][0])

    def test_database_collectors_graceful_offline(self):
        pg = PostgresCollector({"enabled": True, "host": "invalid-host-9999.local", "port": 5432, "timeout": 1})
        res_pg = pg.collect()
        self.assertEqual(res_pg["status"], "offline")
        self.assertIsNotNone(res_pg["error"])
        pg.close()
        self.assertIsNone(pg.conn)

        my = MySQLCollector({"enabled": True, "host": "invalid-host-9999.local", "port": 3306, "timeout": 1})
        res_my = my.collect()
        self.assertEqual(res_my["status"], "offline")
        self.assertIsNotNone(res_my["error"])
        my.close()
        self.assertIsNone(my.conn)

    def test_alert_evaluation(self):
        alert_state_manager.reset_all()

        high_cpu_payload = {
            "system": {
                "cpu": {"total_percent": 96.5},
                "ram": {"percent": 40.0},
                "disk": {"partitions": []}
            },
            "databases": []
        }

        # 1. T = 1000s: Initial breach detection (Pending, should not fire yet!)
        alerts_t0 = evaluate_alerts(high_cpu_payload, now=1000.0)
        self.assertEqual(len(alerts_t0), 0)

        # 2. T = 1040s: 40s elapsed (< 90s, still pending breach)
        alerts_t40 = evaluate_alerts(high_cpu_payload, now=1040.0)
        self.assertEqual(len(alerts_t40), 0)

        # 3. T = 1095s: 95s elapsed (>= 90s continuous breach -> FIRES!)
        alerts_t95 = evaluate_alerts(high_cpu_payload, now=1095.0)
        self.assertTrue(any("CPU" in a["source"] and a["state"] == "firing" for a in alerts_t95))
        cpu_alert = next(a for a in alerts_t95 if "CPU" in a["source"])
        self.assertEqual(cpu_alert["state"], "firing")
        self.assertIn("timestamp", cpu_alert)
        self.assertIn("time_str", cpu_alert)
        self.assertRegex(cpu_alert["time_str"], r"^\d{2}:\d{2}:\d{2}$")

        # 4. Metric drops under threshold at T = 1100s:
        # Must STAY visible in notification bar during 90s recovery window
        low_cpu_payload = {
            "system": {
                "cpu": {"total_percent": 25.0},
                "ram": {"percent": 40.0},
                "disk": {"partitions": []}
            },
            "databases": []
        }
        alerts_t100 = evaluate_alerts(low_cpu_payload, now=1100.0)
        self.assertTrue(any("CPU" in a["source"] and a["state"] == "firing" and a["is_recovering"] for a in alerts_t100))

        # 5. Spikes back up at T = 1130s before 90s recovery completes:
        # Anti-flapping: recovery cancels and alert remains firing
        alerts_t130 = evaluate_alerts(high_cpu_payload, now=1130.0)
        self.assertTrue(any("CPU" in a["source"] and a["state"] == "firing" and not a["is_recovering"] for a in alerts_t130))

        # 6. Drops back down at T = 1140s and stays down for >= 90s (until T = 1235s):
        # Successfully transitions to RESOLVED!
        evaluate_alerts(low_cpu_payload, now=1140.0)
        alerts_t235 = evaluate_alerts(low_cpu_payload, now=1235.0)
        resolved_alert = next(a for a in alerts_t235 if "CPU" in a["source"])
        self.assertEqual(resolved_alert["state"], "resolved")
        self.assertEqual(resolved_alert["level"], "resolved")
        self.assertIn("resolved", resolved_alert["message"].lower())

    def test_api_endpoint_handlers(self):
        # 1. System info endpoint
        info_res = asyncio.run(get_system_info())
        self.assertEqual(info_res["status"], "success")
        self.assertIn("os", info_res["data"])

        # 2. Current metrics endpoint
        metrics_res = asyncio.run(get_current_metrics())
        self.assertEqual(metrics_res["status"], "success")

        # 3. Alerts endpoint
        alerts_res = asyncio.run(get_alerts())
        self.assertEqual(alerts_res["status"], "success")

        # 4. Root HTML endpoint
        root_res = asyncio.run(get_index())
        self.assertTrue(hasattr(root_res, "path"))
        self.assertTrue(root_res.path.endswith("index.html"))

        # 5. Chrome DevTools & Favicon endpoints
        dev_res = asyncio.run(chrome_devtools_endpoint())
        self.assertEqual(dev_res.status_code, 200)

        fav_res = asyncio.run(favicon_endpoint())
        self.assertEqual(fav_res.status_code, 204)

        # 6. Dynamic update interval endpoints
        int_get = asyncio.run(get_interval())
        self.assertEqual(int_get["status"], "success")
        self.assertIn("poll_interval", int_get)

        int_post = asyncio.run(update_interval({"interval": 10.0}))
        self.assertEqual(int_post["status"], "success")
        self.assertEqual(int_post["poll_interval"], 10.0)

        # 7. Timeline historical endpoint
        tl_res = asyncio.run(get_metrics_timeline("5m", 120))
        self.assertEqual(tl_res["status"], "success")
        self.assertEqual(tl_res["range"], "5m")
        self.assertIn("summary", tl_res)
        self.assertIn("points", tl_res)

        # 8. Alert warning limits configuration endpoints
        alerts_get = asyncio.run(get_alert_settings())
        self.assertEqual(alerts_get["status"], "success")
        self.assertIn("cpu_threshold_percent", alerts_get["alerts"])
        self.assertIn("disk_threshold_percent", alerts_get["alerts"])
        self.assertIn("swap_threshold_percent", alerts_get["alerts"])

        # Update disk threshold to 92.0%
        alerts_post = asyncio.run(update_alert_settings({"disk_threshold_percent": 92.0}))
        self.assertEqual(alerts_post["status"], "success")
        self.assertEqual(alerts_post["alerts"]["disk_threshold_percent"], 92.0)

        # Restore default 85.0%
        asyncio.run(update_alert_settings({"disk_threshold_percent": 85.0}))

        # 9. Clear resolved alerts endpoint
        clear_res = asyncio.run(clear_resolved_alerts({"key": "CPU"}))
        self.assertEqual(clear_res["status"], "success")

        # 10. Email settings endpoints
        from app.main import get_email_settings, update_email_settings
        em_get = asyncio.run(get_email_settings())
        self.assertEqual(em_get["status"], "success")
        self.assertEqual(em_get["email"]["sender_email"], "vardhakpatel6@gmail.com")

        em_post = asyncio.run(update_email_settings({"recipient_email": "ops@test.com"}))
        self.assertEqual(em_post["status"], "success")
        self.assertEqual(em_post["email"]["recipient_email"], "ops@test.com")
        asyncio.run(update_email_settings({"recipient_email": ""}))

        # Restore default 1.0s interval
        set_poll_interval(1.0)
        int_restored = asyncio.run(get_interval())
        self.assertEqual(int_restored["poll_interval"], 1.0)

if __name__ == "__main__":
    unittest.main()
