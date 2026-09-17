"""Install or verify the tested Windows/Python 3.11 FlashVSR runtime."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Verify the runtime without installing anything")
    args = parser.parse_args()

    if os.name != "nt" or sys.version_info[:2] != (3, 11):
        raise RuntimeError("Run setup using 64-bit Python 3.11 on Windows (py -3.11).")

    python = ROOT / "env_venv" / "Scripts" / "python.exe"
    lock = ROOT / ".setup.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise RuntimeError("Another setup is running. If it was interrupted, remove .setup.lock and retry.")
    os.close(fd)

    try:
        if not args.check:
            if not python.exists():
                subprocess.run([sys.executable, "-m", "venv", str(ROOT / "env_venv")], check=True)
            subprocess.run([str(python), "-m", "pip", "install", "-r", str(ROOT / "requirements.lock.txt")], check=True)

        if not python.exists():
            raise RuntimeError("FlashVSR runtime is not installed. Run Install_FlashVSR.bat first.")

        subprocess.run([str(python), "-m", "pip", "check"], check=True)
        subprocess.run([str(python), str(ROOT / "check_install.py")], cwd=ROOT, check=True)
        print("FlashVSR runtime verified.", flush=True)
        print("Models are installed separately with Download_FlashVSR_Models.bat.", flush=True)
    finally:
        lock.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
