import os
import shutil
import tempfile
import time
import unittest

from app.storage import MetricsStorage


class TestMetricsStorage(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_metrics.db")
        self.storage = MetricsStorage(db_path=self.db_path, retention_days=7, auto_seed=False)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_record_and_query_raw(self):
        now = time.time()
        for i in range(10):
            payload = {
                "timestamp": now - (10 - i),
                "system": {
                    "cpu": {"total_percent": 10.0 + i, "user_percent": 5.0 + i, "system_percent": 5.0},
                    "ram": {"percent": 50.0 + i, "used_bytes": 4000000000, "swap_percent": 1.0, "swap_used_bytes": 100000},
                    "disk": {"read_bytes_sec": 1000.0 * (i + 1), "write_bytes_sec": 2000.0 * (i + 1)},
                },
                "databases": [
                    {"name": "TestDB", "type": "MySQL", "status": "online", "latency_ms": 0.5 + (i * 0.1), "active_connections": 2}
                ]
            }
            self.storage.record_metric(payload)

        res = self.storage.query_timeline("5m", max_points=60)
        self.assertEqual(res["status"], "success")
        self.assertGreaterEqual(res["count"], 30)
        self.assertAlmostEqual(res["summary"]["cpu"]["peak"], 19.0)
        self.assertAlmostEqual(res["summary"]["cpu"]["low"], 10.0)

    def test_downsampling_large_range(self):
        now = time.time()
        # Insert 300 points across 5 hours (18000s)
        for i in range(300):
            ts = now - 18000 + (i * 60)
            payload = {
                "timestamp": ts,
                "system": {
                    "cpu": {"total_percent": 20.0, "user_percent": 10.0, "system_percent": 10.0},
                    "ram": {"percent": 60.0, "used_bytes": 5000000000, "swap_percent": 0.0, "swap_used_bytes": 0},
                    "disk": {"read_bytes_sec": 500.0, "write_bytes_sec": 500.0},
                },
                "databases": []
            }
            self.storage.record_metric(payload)

        res = self.storage.query_timeline("5h", max_points=72)
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["count"], 72)
        # Check that timestamps span the full 5 hours (approx 17750s)
        span = res["points"][-1]["timestamp"] - res["points"][0]["timestamp"]
        self.assertGreater(span, 17000)

    def test_all_time_query(self):
        now = time.time()
        payload = {
            "timestamp": now - 3600,
            "system": {
                "cpu": {"total_percent": 15.0, "user_percent": 10.0, "system_percent": 5.0},
                "ram": {"percent": 45.0, "used_bytes": 3000000000, "swap_percent": 0.0, "swap_used_bytes": 0},
                "disk": {"read_bytes_sec": 100.0, "write_bytes_sec": 100.0},
            },
            "databases": []
        }
        self.storage.record_metric(payload)

        res = self.storage.query_timeline("all")
        self.assertEqual(res["status"], "success")
        self.assertGreaterEqual(res["count"], 1)

    def test_pruning_old_records(self):
        now = time.time()
        # Old record (10 days ago)
        old_payload = {
            "timestamp": now - (10 * 86400),
            "system": {"cpu": {"total_percent": 5.0}},
            "databases": []
        }
        self.storage.record_metric(old_payload)

        # Fresh record (1 hour ago)
        fresh_payload = {
            "timestamp": now - 3600,
            "system": {"cpu": {"total_percent": 25.0}},
            "databases": []
        }
        self.storage.record_metric(fresh_payload)

        self.storage.prune_old_records()

        res = self.storage.query_timeline("all")
        self.assertEqual(res["count"], 72)
        self.assertAlmostEqual(res["summary"]["cpu"]["peak"], 25.0)

    def test_seeded_timeline_ranges(self):
        # Create storage with auto_seed=True
        seeded_path = os.path.join(self.test_dir, "seeded.db")
        seeded_storage = MetricsStorage(db_path=seeded_path, retention_days=7, auto_seed=True)

        # 15m should span approx 880+ seconds
        r15 = seeded_storage.query_timeline("15m")
        self.assertEqual(r15["count"], 60)
        span15 = r15["points"][-1]["timestamp"] - r15["points"][0]["timestamp"]
        self.assertGreater(span15, 850)

        # 5h should span approx 17500+ seconds
        r5 = seeded_storage.query_timeline("5h")
        self.assertEqual(r5["count"], 72)
        span5 = r5["points"][-1]["timestamp"] - r5["points"][0]["timestamp"]
        self.assertGreater(span5, 17000)

        # 24h should span approx 84000+ seconds
        r24 = seeded_storage.query_timeline("24h")
        self.assertEqual(r24["count"], 72)
        span24 = r24["points"][-1]["timestamp"] - r24["points"][0]["timestamp"]
        self.assertGreater(span24, 84000)


if __name__ == "__main__":
    unittest.main()
