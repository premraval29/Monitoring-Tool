import unittest
import os
import sys
from pathlib import Path
from unittest.mock import patch

from app.paths import (
    is_frozen,
    get_bundled_dir,
    get_app_data_dir,
    get_config_path,
    get_db_path,
    get_static_dir,
)
from app.desktop import find_free_port, wait_for_server

class TestPathsAndDesktop(unittest.TestCase):
    def test_default_development_paths(self):
        self.assertFalse(is_frozen())
        bundled = get_bundled_dir()
        self.assertTrue(bundled.exists())
        self.assertTrue((bundled / "app" / "static").exists())

        static_dir = Path(get_static_dir())
        self.assertTrue(static_dir.exists())
        self.assertTrue((static_dir / "index.html").exists())
        self.assertTrue((static_dir / "app.js").exists())

    def test_config_path_resolution(self):
        cfg_path = Path(get_config_path())
        self.assertTrue(cfg_path.exists())
        self.assertTrue(cfg_path.name.endswith(".yaml"))

    def test_db_path_resolution(self):
        db_path = Path(get_db_path())
        self.assertEqual(db_path.name, "pulse_metrics.db")

    @patch.object(sys, "frozen", True, create=True)
    def test_frozen_app_data_darwin(self):
        with patch.object(sys, "_MEIPASS", "/tmp/_MEI12345", create=True):
            with patch("platform.system", return_value="Darwin"):
                with patch("pathlib.Path.home", return_value=Path("/tmp/testuser")):
                    app_data = get_app_data_dir()
                    expected = Path("/tmp/testuser/Library/Application Support/PulseMon")
                    self.assertEqual(app_data, expected)

    @patch.object(sys, "frozen", True, create=True)
    def test_frozen_app_data_windows(self):
        with patch.object(sys, "_MEIPASS", "/tmp/_MEI12345", create=True):
            with patch("platform.system", return_value="Windows"):
                with patch.dict(os.environ, {"APPDATA": "/tmp/testappdata"}):
                    app_data = get_app_data_dir()
                    expected = Path("/tmp/testappdata/PulseMon")
                    self.assertEqual(app_data, expected)

    def test_find_free_port(self):
        port = find_free_port()
        self.assertIsInstance(port, int)
        self.assertGreater(port, 1024)
        self.assertLess(port, 65536)

    def test_windowed_uvicorn_config_resilience(self):
        """Tests that uvicorn server config initializes without error when stdout/stderr are None."""
        import uvicorn
        from app.main import app
        from hooks.pyinstaller_runtime_hook import NullWriter

        old_stdout, old_stderr = sys.stdout, sys.stderr
        try:
            # Simulate Windows windowed mode
            sys.stdout = None
            sys.stderr = None

            # Runtime hook behavior
            if sys.stdout is None:
                sys.stdout = NullWriter()
            if sys.stderr is None:
                sys.stderr = NullWriter()

            cfg = uvicorn.Config(
                app,
                host="127.0.0.1",
                port=54321,
                log_level="error",
                log_config=None,
                access_log=False,
                reload=False,
            )
            server = uvicorn.Server(cfg)
            self.assertIsNotNone(server)
            self.assertIsNone(cfg.log_config)
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr

if __name__ == "__main__":
    unittest.main()
