import os
import platform
import re
import time
from typing import Dict, Any, List
import psutil

def format_bytes(bytes_val: int) -> str:
    """Formats bytes into human-readable representation (1 decimal place)."""
    if bytes_val < 0:
        return "0 B"
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if bytes_val < 1024.0:
            return f"{bytes_val:.1f} {unit}"
        bytes_val /= 1024.0
    return f"{bytes_val:.1f} PB"

def format_bytes_2dec(bytes_val: int) -> str:
    """Formats bytes with 2 decimal places matching Apple Activity Monitor (e.g. 8.00 GB, 6.13 GB)."""
    if bytes_val < 0:
        return "0.00 B"
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if bytes_val < 1024.0:
            return f"{bytes_val:.2f} {unit}"
        bytes_val /= 1024.0
    return f"{bytes_val:.2f} PB"

def format_disk_bytes(bytes_val: float, is_mac: bool = False) -> str:
    """Formats disk bytes. On macOS, uses SI decimal (1000-based) to match Activity Monitor & Finder."""
    if bytes_val < 0:
        return "0 B"
    divisor = 1000.0 if is_mac else 1024.0
    for unit in ["B", "KB", "MB", "GB", "TB", "PB"]:
        if bytes_val < divisor or unit == "PB":
            if unit in ["GB", "TB"]:
                return f"{bytes_val:.2f} {unit}"
            elif unit in ["MB", "KB"]:
                return f"{bytes_val:.1f} {unit}"
            else:
                return f"{int(bytes_val)} {unit}"
        bytes_val /= divisor
    return f"{bytes_val:.2f} PB"

def format_disk_rate(bytes_sec: float, is_mac: bool = False) -> str:
    """Formats disk transfer rates matching Activity Monitor (e.g. 0 KB/s, 1.2 MB/s)."""
    if bytes_sec < 0:
        return "0 B/s"
    divisor = 1000.0 if is_mac else 1024.0
    for unit in ["B/s", "KB/s", "MB/s", "GB/s"]:
        if bytes_sec < divisor or unit == "GB/s":
            if unit in ["GB/s", "MB/s"]:
                return f"{bytes_sec:.1f} {unit}"
            elif unit == "KB/s":
                return f"{bytes_sec:.0f} {unit}" if bytes_sec >= 10 else f"{bytes_sec:.1f} {unit}"
            else:
                return f"{int(bytes_sec)} {unit}"
        bytes_sec /= divisor
    return f"{bytes_sec:.1f} GB/s"

def format_uptime(seconds: float) -> str:
    """Converts seconds into days, hours, minutes."""
    days, rem = divmod(int(seconds), 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0 or days > 0:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    return " ".join(parts)

# Native macOS Mach VM Statistics Reader for 1-to-1 Activity Monitor Parity
if platform.system() == "Darwin":
    import ctypes
    import ctypes.util

    class vm_statistics64(ctypes.Structure):
        _fields_ = [
            ("free_count", ctypes.c_uint32),
            ("active_count", ctypes.c_uint32),
            ("inactive_count", ctypes.c_uint32),
            ("wire_count", ctypes.c_uint32),
            ("zero_fill_count", ctypes.c_uint64),
            ("reactivations", ctypes.c_uint64),
            ("pageins", ctypes.c_uint64),
            ("pageouts", ctypes.c_uint64),
            ("faults", ctypes.c_uint64),
            ("cow_faults", ctypes.c_uint64),
            ("lookups", ctypes.c_uint64),
            ("hits", ctypes.c_uint64),
            ("purges", ctypes.c_uint64),
            ("purgeable_count", ctypes.c_uint32),
            ("speculative_count", ctypes.c_uint32),
            ("decompressions", ctypes.c_uint64),
            ("compressions", ctypes.c_uint64),
            ("swapins", ctypes.c_uint64),
            ("swapouts", ctypes.c_uint64),
            ("compressor_page_count", ctypes.c_uint32),
            ("throttled_count", ctypes.c_uint32),
            ("external_page_count", ctypes.c_uint32),
            ("internal_page_count", ctypes.c_uint32),
            ("total_uncompressed_pages_in_compressor", ctypes.c_uint64),
        ]

    class MacOSMemoryReader:
        def __init__(self):
            try:
                self.libc = ctypes.CDLL(ctypes.util.find_library("c"))
                self.host = self.libc.mach_host_self()
                page_size = ctypes.c_size_t()
                self.libc.host_page_size(self.host, ctypes.byref(page_size))
                self.page_size = page_size.value or 16384
                self.available = True
            except Exception:
                self.available = False

        def get_memory_pressure(self):
            """Returns (pressure_label, pressure_code) from kern.memorystatus_vm_pressure_level."""
            if not self.available:
                return "Normal", 1
            try:
                val = ctypes.c_int()
                size = ctypes.c_size_t(ctypes.sizeof(ctypes.c_int))
                ret = self.libc.sysctlbyname(b"kern.memorystatus_vm_pressure_level", ctypes.byref(val), ctypes.byref(size), None, 0)
                if ret == 0:
                    if val.value == 1:
                        return "Normal", 1
                    elif val.value == 2:
                        return "Warning", 2
                    elif val.value == 4:
                        return "Critical", 4
            except Exception:
                pass
            return "Normal", 1

        def get_memory_stats(self, total_bytes: int):
            if not self.available:
                return None
            try:
                vm_stat = vm_statistics64()
                count = ctypes.c_uint32(ctypes.sizeof(vm_statistics64) // ctypes.sizeof(ctypes.c_int))
                HOST_VM_INFO64 = 4
                ret = self.libc.host_statistics64(self.host, HOST_VM_INFO64, ctypes.byref(vm_stat), ctypes.byref(count))
                if ret != 0:
                    return None

                ps = self.page_size
                # Exact formulas used by Apple macOS Activity Monitor:
                # App Memory = (internal_page_count - purgeable_count) * page_size
                # Wired Memory = wire_count * page_size
                # Compressed Memory = compressor_page_count * page_size
                # Cached Files = (external_page_count + purgeable_count) * page_size
                # Total Memory Used = Total Physical RAM - Free Memory - Cached Files
                # Note: On Apple Silicon unified memory, Activity Monitor considers all non-free,
                # non-cached memory (including hardware/GPU reserved pages) as Memory Used.
                app_mem = max(0, (vm_stat.internal_page_count - vm_stat.purgeable_count) * ps)
                wired_mem = vm_stat.wire_count * ps
                compressed_mem = vm_stat.compressor_page_count * ps
                cached_files = (vm_stat.external_page_count + vm_stat.purgeable_count) * ps
                free_mem = vm_stat.free_count * ps

                memory_used = max(0, total_bytes - free_mem - cached_files)

                percent = round((memory_used / total_bytes) * 100, 1) if total_bytes > 0 else 0.0
                available = max(0, total_bytes - memory_used)
                pressure_label, pressure_code = self.get_memory_pressure()

                return {
                    "used": memory_used,
                    "used_human": format_bytes_2dec(memory_used),
                    "total_human": format_bytes_2dec(total_bytes),
                    "available": available,
                    "available_human": format_bytes_2dec(available),
                    "percent": percent,
                    "memory_pressure": pressure_label,
                    "memory_pressure_level": pressure_code,
                    "app_memory_human": format_bytes_2dec(app_mem),
                    "wired_memory_human": format_bytes_2dec(wired_mem),
                    "compressed_memory_human": format_bytes_2dec(compressed_mem),
                    "cached_memory_human": format_bytes_2dec(cached_files),
                }
            except Exception:
                return None
else:
    MacOSMemoryReader = None

# ---------------------------------------------------------
# Windows Native Performance & Memory API Structures
# ---------------------------------------------------------
class PERFORMANCE_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_ulong),
        ("CommitTotal", ctypes.c_size_t),
        ("CommitLimit", ctypes.c_size_t),
        ("CommitPeak", ctypes.c_size_t),
        ("PhysicalTotal", ctypes.c_size_t),
        ("PhysicalAvailable", ctypes.c_size_t),
        ("SystemCache", ctypes.c_size_t),
        ("KernelTotal", ctypes.c_size_t),
        ("KernelPaged", ctypes.c_size_t),
        ("KernelNonpaged", ctypes.c_size_t),
        ("PageSize", ctypes.c_size_t),
        ("HandleCount", ctypes.c_ulong),
        ("ProcessCount", ctypes.c_ulong),
        ("ThreadCount", ctypes.c_ulong),
    ]

class ENUM_PAGE_FILE_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_ulong),
        ("Reserved", ctypes.c_ulong),
        ("TotalSize", ctypes.c_size_t),
        ("TotalInUse", ctypes.c_size_t),
        ("PeakUsage", ctypes.c_size_t),
    ]

class WindowsMemoryReader:
    """Native Windows memory and pagefile reader using psapi.dll & kernel32.dll."""
    def __init__(self):
        self.available = False
        try:
            if hasattr(ctypes, "windll"):
                self.psapi = getattr(ctypes.windll, "psapi", None)
                self.kernel32 = getattr(ctypes.windll, "kernel32", None)
                if self.psapi and self.kernel32:
                    self.available = True
        except Exception:
            self.available = False

    def get_performance_info(self):
        if not self.available:
            return None
        try:
            perf = PERFORMANCE_INFORMATION()
            perf.cb = ctypes.sizeof(PERFORMANCE_INFORMATION)
            if self.psapi.GetPerformanceInfo(ctypes.byref(perf), perf.cb):
                return perf
        except Exception:
            pass
        return None

    def get_pagefile_info(self, page_size: int = 4096):
        """Returns (total_bytes, used_bytes, percent) for actual on-disk pagefile(s)."""
        if not self.available:
            return None
        try:
            total_pages = [0]
            used_pages = [0]

            PENUM_PAGE_FILE_CALLBACKW = ctypes.WINFUNCTYPE(
                ctypes.c_bool,
                ctypes.c_void_p,
                ctypes.POINTER(ENUM_PAGE_FILE_INFORMATION),
                ctypes.c_wchar_p,
            )

            def enum_cb(p_context, p_page_info, lp_filename):
                if p_page_info:
                    info = p_page_info.contents
                    total_pages[0] += info.TotalSize
                    used_pages[0] += info.TotalInUse
                return True

            cb_func = PENUM_PAGE_FILE_CALLBACKW(enum_cb)
            if self.psapi.EnumPageFilesW(cb_func, None):
                tot = total_pages[0] * page_size
                usd = used_pages[0] * page_size
                pct = round((used_pages[0] / total_pages[0]) * 100, 1) if total_pages[0] > 0 else 0.0
                return tot, usd, pct
        except Exception:
            pass
        return None

    def get_memory_stats(self, total_bytes: int):
        perf = self.get_performance_info()
        if not perf:
            return None
        ps = perf.PageSize or 4096

        # Physical RAM calculation
        ram_total = (perf.PhysicalTotal * ps) if perf.PhysicalTotal > 0 else total_bytes
        ram_available = perf.PhysicalAvailable * ps
        ram_used = max(0, ram_total - ram_available)
        ram_percent = round((ram_used / ram_total) * 100, 1) if ram_total > 0 else 0.0

        if ram_percent < 85:
            pressure_label, pressure_code = "Normal", 1
        elif ram_percent < 95:
            pressure_label, pressure_code = "Warning", 2
        else:
            pressure_label, pressure_code = "Critical", 4

        # Memory breakdown aligned with Windows Task Manager:
        # SystemCache = Cached standby & modified file cache
        # KernelNonpaged = Non-paged pool (pinned kernel memory, identical role to Wired memory)
        # KernelPaged = Paged pool memory
        # App Memory = Active working set (ram_used - Non-paged pool)
        cached_bytes = perf.SystemCache * ps
        nonpaged_bytes = perf.KernelNonpaged * ps
        paged_bytes = perf.KernelPaged * ps
        app_bytes = max(0, ram_used - nonpaged_bytes)

        # Pagefile usage on disk (replaces Commit Charge swap false-positive alerts)
        pf_info = self.get_pagefile_info(ps)
        if pf_info:
            swap_total, swap_used, swap_pct = pf_info
        else:
            swap_total, swap_used, swap_pct = 0, 0, 0.0

        # Commit Charge (Virtual memory allocations)
        commit_total = perf.CommitTotal * ps
        commit_limit = perf.CommitLimit * ps
        commit_pct = round((commit_total / commit_limit) * 100, 1) if commit_limit > 0 else 0.0

        return {
            "total": ram_total,
            "total_human": format_bytes_2dec(ram_total),
            "used": ram_used,
            "used_human": format_bytes_2dec(ram_used),
            "available": ram_available,
            "available_human": format_bytes_2dec(ram_available),
            "percent": ram_percent,
            "memory_pressure": pressure_label,
            "memory_pressure_level": pressure_code,
            "app_memory_human": format_bytes_2dec(app_bytes),
            "wired_memory_human": format_bytes_2dec(nonpaged_bytes),
            "compressed_memory_human": format_bytes_2dec(paged_bytes),
            "cached_memory_human": format_bytes_2dec(cached_bytes),
            "swap_total": swap_total,
            "swap_total_human": format_bytes_2dec(swap_total),
            "swap_used": swap_used,
            "swap_used_human": format_bytes_2dec(swap_used),
            "swap_percent": swap_pct,
            "commit_total": commit_total,
            "commit_total_human": format_bytes_2dec(commit_total),
            "commit_limit": commit_limit,
            "commit_limit_human": format_bytes_2dec(commit_limit),
            "commit_percent": commit_pct,
            "process_count": perf.ProcessCount,
            "thread_count": perf.ThreadCount,
            "handle_count": perf.HandleCount,
        }

def get_windows_volume_label(mount_point: str) -> Optional[str]:
    """Retrieves friendly volume label for a Windows drive letter."""
    try:
        if not hasattr(ctypes, "windll"):
            return None
        m = mount_point.rstrip("\\/") + "\\"
        vol_name_buf = ctypes.create_unicode_buffer(261)
        fs_name_buf = ctypes.create_unicode_buffer(261)
        ret = ctypes.windll.kernel32.GetVolumeInformationW(
            ctypes.c_wchar_p(m),
            vol_name_buf,
            ctypes.sizeof(vol_name_buf),
            None,
            None,
            None,
            fs_name_buf,
            ctypes.sizeof(fs_name_buf)
        )
        if ret and vol_name_buf.value.strip():
            return vol_name_buf.value.strip()
    except Exception:
        pass
    return None

def is_windows_drive_ready(mount_point: str) -> bool:
    """Checks if a drive is ready and not an empty optical or disconnected drive."""
    try:
        if not hasattr(ctypes, "windll"):
            return True
        m = mount_point.rstrip("\\/") + "\\"
        drive_type = ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(m))
        # DRIVE_CDROM is 5. Calling psutil.disk_usage on empty CD-ROM raises WinError 21
        if drive_type == 5:
            return False
    except Exception:
        pass
    return True

class SystemCollector:
    def __init__(self):
        self.is_mac = platform.system() == "Darwin"
        self.is_windows = platform.system() == "Windows"
        self.is_linux = platform.system() == "Linux"
        self.mac_mem_reader = MacOSMemoryReader() if (self.is_mac and MacOSMemoryReader) else None
        self.win_mem_reader = WindowsMemoryReader() if (self.is_windows and WindowsMemoryReader) else None
        self.cpu_brand = self._get_cpu_brand()
        self.last_cpu_times = psutil.cpu_times()
        self.last_cpu_times_percpu = psutil.cpu_times(percpu=True)
        self.last_disk_io = None
        self.last_disk_io_time = None

    def _get_cpu_brand(self) -> str:
        """Discovers CPU model brand name dynamically across macOS, Linux, and Windows."""
        try:
            if self.is_mac:
                import subprocess
                out = subprocess.check_output(["sysctl", "-n", "machdep.cpu.brand_string"], stderr=subprocess.DEVNULL)
                brand = out.decode("utf-8", errors="ignore").strip()
                if brand:
                    return brand
            elif self.is_linux:
                if os.path.exists("/proc/cpuinfo"):
                    with open("/proc/cpuinfo", "r", encoding="utf-8", errors="ignore") as f:
                        for line in f:
                            if "model name" in line:
                                brand = line.split(":", 1)[1].strip()
                                if brand:
                                    return brand
            elif self.is_windows:
                try:
                    import winreg
                    key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
                    brand, _ = winreg.QueryValueEx(key, "ProcessorNameString")
                    winreg.CloseKey(key)
                    if brand and brand.strip():
                        return brand.strip()
                except Exception:
                    pass
        except Exception:
            pass
        return platform.processor() or platform.machine() or "Generic CPU"

    def get_static_info(self) -> Dict[str, Any]:
        """Returns static host information."""
        boot_time = psutil.boot_time()
        return {
            "hostname": platform.node(),
            "os": platform.system(),
            "os_release": platform.release(),
            "os_version": platform.version(),
            "architecture": platform.machine(),
            "cpu_brand": self.cpu_brand,
            "cpu_physical_cores": psutil.cpu_count(logical=False) or psutil.cpu_count(logical=True),
            "cpu_logical_cores": psutil.cpu_count(logical=True),
            "boot_time": boot_time,
        }

    def collect(self) -> Dict[str, Any]:
        """Collects dynamic real-time system metrics aligned with OS-native tools."""
        now = time.time()
        
        # 1. CPU Metrics (Synchronized Delta Measurement)
        curr_cpu_times = psutil.cpu_times()
        curr_cpu_times_percpu = psutil.cpu_times(percpu=True)

        user_pct = 0.0
        sys_pct = 0.0
        idle_pct = 100.0
        total_cpu = 0.0

        if self.last_cpu_times:
            d_user = curr_cpu_times.user - self.last_cpu_times.user
            d_sys = curr_cpu_times.system - self.last_cpu_times.system
            d_idle = curr_cpu_times.idle - self.last_cpu_times.idle
            d_nice = getattr(curr_cpu_times, "nice", 0) - getattr(self.last_cpu_times, "nice", 0)
            d_irq = getattr(curr_cpu_times, "interrupt", 0) - getattr(self.last_cpu_times, "interrupt", 0)
            d_dpc = getattr(curr_cpu_times, "dpc", 0) - getattr(self.last_cpu_times, "dpc", 0)

            # Sum all CPU time fields so denominator correctly captures Windows Interrupt/DPC cycles
            d_total = sum(curr_cpu_times) - sum(self.last_cpu_times)

            if d_total > 0:
                user_pct = round((d_user / d_total) * 100, 1)
                idle_pct = round((d_idle / d_total) * 100, 1)
                if self.is_windows:
                    # Windows kernel includes Interrupts and DPCs in system activity
                    sys_pct = round(((d_sys + d_irq + d_dpc) / d_total) * 100, 1)
                    # Task Manager parity: Total CPU % = 100.0 - idle%
                    total_cpu = max(0.0, min(100.0, round(100.0 - idle_pct, 1)))
                else:
                    sys_pct = round((d_sys / d_total) * 100, 1)
                    # Aligned with Activity Monitor / top: Total Load = User + System
                    total_cpu = max(0.0, min(100.0, round(user_pct + sys_pct, 1)))

        self.last_cpu_times = curr_cpu_times

        # Per-core breakdown
        per_core = []
        if self.last_cpu_times_percpu and len(self.last_cpu_times_percpu) == len(curr_cpu_times_percpu):
            for t1, t2 in zip(self.last_cpu_times_percpu, curr_cpu_times_percpu):
                cd_total = sum(t2) - sum(t1)
                if cd_total > 0:
                    if self.is_windows:
                        core_idle = t2.idle - t1.idle
                        core_pct = max(0.0, min(100.0, round(100.0 - (core_idle / cd_total * 100), 1)))
                    else:
                        cd_user = t2.user - t1.user
                        cd_sys = t2.system - t1.system
                        core_pct = round(((cd_user + cd_sys) / cd_total) * 100, 1)
                else:
                    core_pct = 0.0
                per_core.append(core_pct)
        else:
            per_core = [0.0] * (psutil.cpu_count(logical=True) or 1)

        self.last_cpu_times_percpu = curr_cpu_times_percpu

        # Load averages (Unix only)
        try:
            load_avg = list(psutil.getloadavg())
        except (AttributeError, OSError):
            load_avg = [0.0, 0.0, 0.0]

        # 2. RAM & Swap Metrics (100% OS-Native Parity with 2-Decimal Precision)
        vm = psutil.virtual_memory()
        swap = psutil.swap_memory()

        mac_stats = self.mac_mem_reader.get_memory_stats(vm.total) if self.mac_mem_reader else None
        win_stats = self.win_mem_reader.get_memory_stats(vm.total) if self.win_mem_reader else None

        if mac_stats:
            ram_metrics = {
                "total": vm.total,
                "total_human": mac_stats["total_human"],
                "used": mac_stats["used"],
                "used_human": mac_stats["used_human"],
                "available": mac_stats["available"],
                "available_human": mac_stats["available_human"],
                "percent": mac_stats["percent"],
                "memory_pressure": mac_stats["memory_pressure"],
                "memory_pressure_level": mac_stats["memory_pressure_level"],
                "app_memory_human": mac_stats["app_memory_human"],
                "wired_memory_human": mac_stats["wired_memory_human"],
                "compressed_memory_human": mac_stats["compressed_memory_human"],
                "cached_memory_human": mac_stats["cached_memory_human"],
                "swap_total": swap.total,
                "swap_total_human": format_bytes_2dec(swap.total),
                "swap_used": swap.used,
                "swap_used_human": format_bytes_2dec(swap.used),
                "swap_percent": round(swap.percent, 1),
            }
        elif win_stats:
            ram_metrics = {
                "total": win_stats["total"],
                "total_human": win_stats["total_human"],
                "used": win_stats["used"],
                "used_human": win_stats["used_human"],
                "available": win_stats["available"],
                "available_human": win_stats["available_human"],
                "percent": win_stats["percent"],
                "memory_pressure": win_stats["memory_pressure"],
                "memory_pressure_level": win_stats["memory_pressure_level"],
                "app_memory_human": win_stats["app_memory_human"],
                "wired_memory_human": win_stats["wired_memory_human"],
                "compressed_memory_human": win_stats["compressed_memory_human"],
                "cached_memory_human": win_stats["cached_memory_human"],
                "swap_total": win_stats["swap_total"],
                "swap_total_human": win_stats["swap_total_human"],
                "swap_used": win_stats["swap_used"],
                "swap_used_human": win_stats["swap_used_human"],
                "swap_percent": win_stats["swap_percent"],
                "commit_total_human": win_stats.get("commit_total_human"),
                "commit_limit_human": win_stats.get("commit_limit_human"),
                "commit_percent": win_stats.get("commit_percent", 0.0),
            }
        else:
            memory_used = vm.used
            ram_percent = round(vm.percent, 1)
            available = vm.available
            ram_metrics = {
                "total": vm.total,
                "total_human": format_bytes_2dec(vm.total),
                "used": memory_used,
                "used_human": format_bytes_2dec(memory_used),
                "available": available,
                "available_human": format_bytes_2dec(available),
                "percent": ram_percent,
                "memory_pressure": "Normal" if ram_percent < 85 else ("Warning" if ram_percent < 95 else "Critical"),
                "memory_pressure_level": 1 if ram_percent < 85 else (2 if ram_percent < 95 else 4),
                "app_memory_human": format_bytes_2dec(getattr(vm, "active", vm.used)),
                "wired_memory_human": format_bytes_2dec(getattr(vm, "buffers", 0)) if getattr(vm, "buffers", 0) else "0.00 B",
                "compressed_memory_human": "0.00 B",
                "cached_memory_human": format_bytes_2dec(getattr(vm, "cached", 0)),
                "swap_total": swap.total,
                "swap_total_human": format_bytes_2dec(swap.total),
                "swap_used": swap.used,
                "swap_used_human": format_bytes_2dec(swap.used),
                "swap_percent": round(swap.percent, 1),
            }

        # 3. Disk Metrics (Clean Volume Filtering & APFS Volume Group Unification)
        disks: List[Dict[str, Any]] = []
        seen_mounts = set()

        if self.is_mac:
            # On macOS, unify the APFS Volume Group (Macintosh HD + Macintosh HD - Data)
            # matching Apple Disk Utility and System Settings standard.
            # Total Used is strictly equal to Data + System.
            try:
                s = os.statvfs("/")
                total_bytes = s.f_blocks * s.f_frsize
                free_bytes = s.f_bavail * s.f_frsize

                data_used = 0
                sys_used = 0
                data_str = None
                sys_str = None
                try:
                    data_used = psutil.disk_usage("/System/Volumes/Data").used
                    data_str = format_disk_bytes(data_used, is_mac=True)
                except Exception:
                    pass
                try:
                    sys_used = psutil.disk_usage("/").used
                    sys_str = format_disk_bytes(sys_used, is_mac=True)
                except Exception:
                    pass

                # Approach 2: Used strictly equals Data + System
                if data_used > 0 or sys_used > 0:
                    used_bytes = data_used + sys_used
                else:
                    used_bytes = max(0, total_bytes - free_bytes)

                percent = round((used_bytes / total_bytes) * 100, 1) if total_bytes > 0 else 0.0

                breakdown_parts = []
                if data_str:
                    breakdown_parts.append(f"Data: {data_str}")
                if sys_str:
                    breakdown_parts.append(f"System: {sys_str}")
                breakdown = " • ".join(breakdown_parts) if breakdown_parts else None

                root_device = "/dev/disk3"
                for p in psutil.disk_partitions(all=False):
                    if p.mountpoint == "/":
                        m = re.match(r"^(/dev/disk\d+)", p.device)
                        root_device = m.group(1) if m else p.device
                        break

                disks.append({
                    "name": "Macintosh HD",
                    "device": root_device,
                    "mount": "/",
                    "fstype": "apfs",
                    "total": total_bytes,
                    "total_human": format_disk_bytes(total_bytes, is_mac=True),
                    "used": used_bytes,
                    "used_human": format_disk_bytes(used_bytes, is_mac=True),
                    "free": free_bytes,
                    "free_human": format_disk_bytes(free_bytes, is_mac=True),
                    "percent": percent,
                    "breakdown": breakdown,
                })
                seen_mounts.add("/")
                seen_mounts.add("/System/Volumes/Data")
            except Exception:
                pass

        for part in psutil.disk_partitions(all=False):
            mount = part.mountpoint
            if mount in seen_mounts:
                continue
            seen_mounts.add(mount)

            if self.is_mac:
                if mount.startswith("/System/Volumes/") or mount == "/":
                    continue
            elif self.is_windows:
                if not is_windows_drive_ready(mount):
                    continue

            try:
                if hasattr(os, "statvfs"):
                    s = os.statvfs(mount)
                    p_total = s.f_blocks * s.f_frsize
                    if p_total == 0:
                        continue
                    p_free = s.f_bavail * s.f_frsize
                    p_used = max(0, p_total - p_free)
                    p_percent = round((p_used / p_total) * 100, 1) if p_total > 0 else 0.0
                else:
                    usage = psutil.disk_usage(mount)
                    p_total = usage.total
                    if p_total == 0:
                        continue
                    p_free = usage.free
                    p_used = usage.used
                    p_percent = round(usage.percent, 1)

                if self.is_windows and re.match(r"^[a-zA-Z]:", mount):
                    clean_drv = mount.rstrip(r"\/")
                    vol_label = get_windows_volume_label(mount)
                    if vol_label:
                        display_name = f"{vol_label} ({clean_drv})"
                    else:
                        display_name = f"Local Disk ({clean_drv})"
                else:
                    display_name = mount.split("/")[-1] if "/" in mount else mount
                    if not display_name:
                        display_name = mount

                disks.append({
                    "name": display_name,
                    "device": part.device,
                    "mount": mount,
                    "fstype": part.fstype,
                    "total": p_total,
                    "total_human": format_disk_bytes(p_total, is_mac=self.is_mac),
                    "used": p_used,
                    "used_human": format_disk_bytes(p_used, is_mac=self.is_mac),
                    "free": p_free,
                    "free_human": format_disk_bytes(p_free, is_mac=self.is_mac),
                    "percent": p_percent,
                    "breakdown": None,
                })
            except (PermissionError, OSError):
                continue

        # Sort primary mounts first
        disks.sort(key=lambda d: (0 if "Macintosh" in d["name"] or d["mount"] in ("/", "C:\\", "C:", "c:\\", "c:") else 1, d["name"]))

        # 4. Disk Throughput, IOPS & Lifetime Totals (Matching Activity Monitor)
        read_rate = 0.0
        write_rate = 0.0
        read_iops = 0
        write_iops = 0
        total_read_bytes = 0
        total_write_bytes = 0
        total_read_count = 0
        total_write_count = 0

        try:
            current_io = psutil.disk_io_counters()
            if current_io:
                total_read_bytes = current_io.read_bytes
                total_write_bytes = current_io.write_bytes
                total_read_count = current_io.read_count
                total_write_count = current_io.write_count

                if self.last_disk_io and self.last_disk_io_time:
                    dt = now - self.last_disk_io_time
                    if dt > 0.1:
                        read_rate = max(0.0, (current_io.read_bytes - self.last_disk_io.read_bytes) / dt)
                        write_rate = max(0.0, (current_io.write_bytes - self.last_disk_io.write_bytes) / dt)
                        read_iops = int(max(0, (current_io.read_count - self.last_disk_io.read_count) / dt))
                        write_iops = int(max(0, (current_io.write_count - self.last_disk_io.write_count) / dt))
                self.last_disk_io = current_io
                self.last_disk_io_time = now
        except Exception:
            pass

        # 5. Uptime
        boot_time = psutil.boot_time()
        uptime_seconds = max(0.0, now - boot_time)

        return {
            "timestamp": now,
            "uptime_seconds": uptime_seconds,
            "uptime_human": format_uptime(uptime_seconds),
            "cpu": {
                "total_percent": total_cpu,
                "user_percent": user_pct,
                "system_percent": sys_pct,
                "idle_percent": idle_pct,
                "per_core_percent": per_core,
                "load_avg": load_avg,
                "process_count": win_stats.get("process_count") if win_stats else None,
                "thread_count": win_stats.get("thread_count") if win_stats else None,
                "handle_count": win_stats.get("handle_count") if win_stats else None,
            },
            "ram": ram_metrics,
            "disk": {
                "partitions": disks,
                "read_bytes_sec": round(read_rate, 1),
                "read_rate_human": format_disk_rate(read_rate, is_mac=self.is_mac),
                "write_bytes_sec": round(write_rate, 1),
                "write_rate_human": format_disk_rate(write_rate, is_mac=self.is_mac),
                "read_iops": read_iops,
                "write_iops": write_iops,
                "total_read_bytes": total_read_bytes,
                "total_read_human": format_disk_bytes(total_read_bytes, is_mac=self.is_mac),
                "total_write_bytes": total_write_bytes,
                "total_write_human": format_disk_bytes(total_write_bytes, is_mac=self.is_mac),
                "total_read_count": total_read_count,
                "total_read_count_formatted": f"{total_read_count:,}",
                "total_write_count": total_write_count,
                "total_write_count_formatted": f"{total_write_count:,}",
            },
        }
