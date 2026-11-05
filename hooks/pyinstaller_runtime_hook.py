# PyInstaller Runtime Hook for PulseMon
# Executed before any application code loads in the frozen executable.
import sys

class NullWriter:
    """Safe fallback stream when running in PyInstaller windowed mode (console=False)."""
    def write(self, *args, **kwargs):
        pass

    def flush(self, *args, **kwargs):
        pass

    def isatty(self):
        return False

# In Windows/macOS windowed mode (console=False), standard streams are None.
# Provide dummy streams so libraries checking .isatty() or calling write() do not crash.
if sys.stdout is None or not hasattr(sys.stdout, "isatty"):
    sys.stdout = NullWriter()

if sys.stderr is None or not hasattr(sys.stderr, "isatty"):
    sys.stderr = NullWriter()

if sys.stdin is None:
    sys.stdin = NullWriter()

