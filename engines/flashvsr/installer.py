"""Install the tested Windows/Python 3.11 FlashVSR stack in its own venv."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parent


def digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def install_models(root, source=None):
    manifest = json.loads((root / "models.json").read_text())
    target = root / "models"
    target.mkdir(exist_ok=True)
    for name, spec in manifest.items():
        destination = target / name
        if destination.is_file() and digest(destination) == spec["sha256"]:
            print(f"Model verified: {name}", flush=True)
            continue
        partial = destination.with_suffix(".partial")
        try:
            if source:
                shutil.copyfile(Path(source) / name, partial)
            else:
                print(f"Downloading {name}", flush=True)
                with urllib.request.urlopen(spec["url"], timeout=120) as response, open(partial, "wb") as stream:
                    shutil.copyfileobj(response, stream, 8 * 1024 * 1024)
            if digest(partial) != spec["sha256"]:
                raise RuntimeError(f"Model checksum mismatch: {name}")
            partial.replace(destination)
        finally:
            partial.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models-from", type=Path, help="Reuse existing model files after checksum verification")
    parser.add_argument("--check", action="store_true", help="Verify installed dependencies, GPU and models without installing")
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
            install_models(ROOT, args.models_from)
        subprocess.run([str(python), "-m", "pip", "check"], check=True)
        subprocess.run([str(python), str(ROOT / "check_install.py")], cwd=ROOT, check=True)
        print("FlashVSR setup verified.", flush=True)
    finally:
        lock.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
