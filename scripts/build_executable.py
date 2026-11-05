#!/usr/bin/env python3
"""
PulseMon Standalone Executable Build Helper
Compiles the application into a standalone desktop application window using PyInstaller.
"""
import os
import sys
import shutil
import subprocess
import platform

def main():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    os.chdir(repo_root)

    print("=" * 65)
    print("  PulseMon Native Desktop Executable Builder")
    print("=" * 65)
    print(f"  • Platform : {platform.system()} ({platform.machine()})")
    print(f"  • Python   : {platform.python_version()}")
    print("=" * 65)

    # 1. Clean previous build output
    for folder in ["build", "dist"]:
        path = os.path.join(repo_root, folder)
        if os.path.exists(path):
            print(f"[*] Cleaning old {folder}/ directory...")
            shutil.rmtree(path, ignore_errors=True)

    # 2. Check for PyInstaller
    try:
        import PyInstaller
        print(f"[*] Found PyInstaller version {PyInstaller.__version__}")
    except ImportError:
        print("[!] PyInstaller is not installed. Installing...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller", "pywebview"])

    # 3. Build executable
    spec_file = os.path.join(repo_root, "pulsemon.spec")
    print(f"[*] Invoking PyInstaller with {spec_file}...")
    cmd = [sys.executable, "-m", "PyInstaller", spec_file, "--clean"]
    res = subprocess.run(cmd)

    if res.returncode != 0:
        print(f"[✖] Compilation failed with return code {res.returncode}")
        return res.returncode

    dist_dir = os.path.join(repo_root, "dist")
    print("\n" + "=" * 65)
    print("  Build Succeeded!")
    print("=" * 65)
    if os.path.exists(dist_dir):
        for item in os.listdir(dist_dir):
            item_path = os.path.join(dist_dir, item)
            size_mb = os.path.getsize(item_path) / (1024 * 1024) if os.path.isfile(item_path) else 0
            if size_mb > 0:
                print(f"  ✔ Generated Artifact: dist/{item} ({size_mb:.1f} MB)")
            else:
                print(f"  ✔ Generated Artifact: dist/{item}")
    print("=" * 65)
    print("Double-click the artifact to launch PulseMon as a native desktop application.")
    print("=" * 65 + "\n")
    return 0

if __name__ == "__main__":
    sys.exit(main())

