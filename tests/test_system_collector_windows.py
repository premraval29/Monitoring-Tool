import collections
import ctypes
import unittest
from unittest.mock import MagicMock, patch

from app.collectors.system_collector import (
    PERFORMANCE_INFORMATION,
    ENUM_PAGE_FILE_INFORMATION,
    SystemCollector,
    WindowsMemoryReader,
    get_windows_volume_label,
    is_windows_drive_ready,
)

# Simulated Windows CPU times namedtuple
WinCpuTimes = collections.namedtuple(
    "WinCpuTimes", ["user", "system", "idle", "interrupt", "dpc"]
)


class TestSystemCollectorWindows(unittest.TestCase):
    def setUp(self):
        self.collector = SystemCollector()
        self.collector.is_windows = True
        self.collector.is_mac = False
        self.collector.is_linux = False

    def test_windows_cpu_calculation_includes_interrupt_and_dpc(self):
        """Tests that Windows CPU % calculation matches Windows Task Manager (100 - idle%)."""
        t1 = WinCpuTimes(user=100.0, system=50.0, idle=800.0, interrupt=20.0, dpc=30.0)
        t2 = WinCpuTimes(user=120.0, system=60.0, idle=850.0, interrupt=30.0, dpc=40.0)

        # Delta:
        # d_user = 20, d_sys = 10, d_idle = 50, d_interrupt = 10, d_dpc = 10
        # d_total = 20 + 10 + 50 + 10 + 10 = 100 ticks
        # idle_pct = 50.0%
        # total_cpu = 100.0 - 50.0 = 50.0%
        # system_pct = (10 + 10 + 10) / 100 = 30.0%
        # user_pct = 20.0%

        self.collector.last_cpu_times = t1
        self.collector.last_cpu_times_percpu = [t1]

        def mock_cpu_times(percpu=False):
            if percpu:
                return [t2]
            return t2

        with patch("psutil.cpu_times", side_effect=mock_cpu_times), \
             patch("psutil.disk_partitions", return_value=[]), \
             patch("psutil.disk_io_counters", return_value=None):
            data = self.collector.collect()

        cpu = data["cpu"]
        self.assertEqual(cpu["total_percent"], 50.0)
        self.assertEqual(cpu["user_percent"], 20.0)
        self.assertEqual(cpu["system_percent"], 30.0)
        self.assertEqual(cpu["idle_percent"], 50.0)
        self.assertEqual(cpu["per_core_percent"], [50.0])

    def test_windows_memory_reader_performance_info(self):
        """Tests that WindowsMemoryReader correctly extracts Task Manager memory metrics."""
        reader = WindowsMemoryReader()
        reader.available = True

        mock_perf = PERFORMANCE_INFORMATION()
        mock_perf.PageSize = 4096
        # 16 GB Physical Total (4,194,304 pages)
        mock_perf.PhysicalTotal = 4194304
        # 8 GB Available (2,097,152 pages)
        mock_perf.PhysicalAvailable = 2097152
        # 2 GB System Cache (524,288 pages)
        mock_perf.SystemCache = 524288
        # 512 MB Non-paged pool (131,072 pages)
        mock_perf.KernelNonpaged = 131072
        # 1 GB Paged pool (262,144 pages)
        mock_perf.KernelPaged = 262144
        # 12 GB Commit Total (3,145,728 pages)
        mock_perf.CommitTotal = 3145728
        # 18 GB Commit Limit (4,718,592 pages)
        mock_perf.CommitLimit = 4718592
        mock_perf.ProcessCount = 185
        mock_perf.ThreadCount = 2650
        mock_perf.HandleCount = 92000

        with patch.object(reader, "get_performance_info", return_value=mock_perf), \
             patch.object(reader, "get_pagefile_info", return_value=(2 * 1024**3, 200 * 1024**2, 9.8)):
            stats = reader.get_memory_stats(total_bytes=16 * 1024**3)

        self.assertIsNotNone(stats)
        self.assertEqual(stats["percent"], 50.0)
        self.assertEqual(stats["total_human"], "16.00 GB")
        self.assertEqual(stats["used_human"], "8.00 GB")
        self.assertEqual(stats["available_human"], "8.00 GB")
        self.assertEqual(stats["cached_memory_human"], "2.00 GB")
        self.assertEqual(stats["wired_memory_human"], "512.00 MB")  # Non-paged pool
        self.assertEqual(stats["compressed_memory_human"], "1.00 GB")  # Paged pool
        self.assertEqual(stats["app_memory_human"], "7.50 GB")  # 8GB used - 512MB non-paged
        self.assertEqual(stats["swap_total_human"], "2.00 GB")  # On-disk pagefile
        self.assertEqual(stats["swap_percent"], 9.8)
        self.assertEqual(stats["commit_total_human"], "12.00 GB")
        self.assertEqual(stats["commit_limit_human"], "18.00 GB")
        self.assertEqual(stats["process_count"], 185)
        self.assertEqual(stats["thread_count"], 2650)
        self.assertEqual(stats["handle_count"], 92000)

    def test_windows_swap_alert_avoidance_with_real_pagefile(self):
        """Verifies that high virtual commit charge does NOT trigger false swap alert on Windows."""
        reader = WindowsMemoryReader()
        reader.available = True

        mock_perf = PERFORMANCE_INFORMATION()
        mock_perf.PageSize = 4096
        mock_perf.PhysicalTotal = 4194304
        mock_perf.PhysicalAvailable = 2097152
        mock_perf.SystemCache = 524288
        mock_perf.KernelNonpaged = 131072
        mock_perf.KernelPaged = 262144
        # High commit charge: 16GB committed out of 18GB (88.9%)
        mock_perf.CommitTotal = 4194304
        mock_perf.CommitLimit = 4718592
        mock_perf.ProcessCount = 200
        mock_perf.ThreadCount = 3000
        mock_perf.HandleCount = 95000

        # But real disk pagefile is only 5% used!
        with patch.object(reader, "get_performance_info", return_value=mock_perf), \
             patch.object(reader, "get_pagefile_info", return_value=(4 * 1024**3, 200 * 1024**2, 4.9)):
            stats = reader.get_memory_stats(total_bytes=16 * 1024**3)

        self.assertEqual(stats["swap_percent"], 4.9)
        self.assertLess(stats["swap_percent"], 80.0, "Real pagefile usage is safe under threshold")
        self.assertEqual(stats["commit_percent"], 88.9)

    def test_windows_optical_drive_handling(self):
        """Verifies that empty optical / CD-ROM drives (DRIVE_CDROM == 5) are ignored."""
        mock_windll = MagicMock()
        mock_windll.kernel32.GetDriveTypeW.return_value = 5  # DRIVE_CDROM

        with patch.object(ctypes, "windll", mock_windll, create=True):
            ready = is_windows_drive_ready("D:\\")
            self.assertFalse(ready)

        mock_windll.kernel32.GetDriveTypeW.return_value = 3  # DRIVE_FIXED
        with patch.object(ctypes, "windll", mock_windll, create=True):
            ready = is_windows_drive_ready("C:\\")
            self.assertTrue(ready)

    def test_windows_volume_label_resolution(self):
        """Verifies that friendly volume labels format correctly."""
        mock_windll = MagicMock()
        def mock_get_vol_info(root, vol_buf, vol_size, *args):
            vol_buf.value = "System_OS"
            return 1

        mock_windll.kernel32.GetVolumeInformationW.side_effect = mock_get_vol_info

        with patch.object(ctypes, "windll", mock_windll, create=True):
            label = get_windows_volume_label("C:\\")
            self.assertEqual(label, "System_OS")


if __name__ == "__main__":
    unittest.main()
