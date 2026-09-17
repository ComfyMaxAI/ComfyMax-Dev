"""Download or verify the optional FlashVSR model files."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import urllib.request

ROOT = Path(__file__).resolve().parent


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def install_models(source: Path | None = None) -> None:
    manifest = json.loads((ROOT / "models.json").read_text(encoding="utf-8"))
    target = ROOT / "models"
    target.mkdir(exist_ok=True)

    for name, spec in manifest.items():
        destination = target / name
        if destination.is_file() and digest(destination) == spec["sha256"]:
            print(f"Model verified: {name}", flush=True)
            continue

        partial = destination.with_suffix(destination.suffix + ".partial")
        partial.unlink(missing_ok=True)
        try:
            if source:
                source_file = source / name
                if not source_file.is_file():
                    raise RuntimeError(f"Model not found in source folder: {source_file}")
                print(f"Copying {name}", flush=True)
                shutil.copyfile(source_file, partial)
            else:
                print(f"Downloading {name}", flush=True)
                with urllib.request.urlopen(spec["url"], timeout=120) as response, partial.open("wb") as stream:
                    shutil.copyfileobj(response, stream, 8 * 1024 * 1024)

            if digest(partial) != spec["sha256"]:
                raise RuntimeError(f"Model checksum mismatch: {name}")
            partial.replace(destination)
            print(f"Installed: {name}", flush=True)
        finally:
            partial.unlink(missing_ok=True)


def verify_models() -> None:
    manifest = json.loads((ROOT / "models.json").read_text(encoding="utf-8"))
    missing = []
    invalid = []
    for name, spec in manifest.items():
        path = ROOT / "models" / name
        if not path.is_file():
            missing.append(name)
        elif digest(path) != spec["sha256"]:
            invalid.append(name)
    if missing or invalid:
        details = []
        if missing:
            details.append("Missing: " + ", ".join(missing))
        if invalid:
            details.append("Checksum mismatch: " + ", ".join(invalid))
        raise RuntimeError("FlashVSR models are incomplete. " + " | ".join(details))
    print("All FlashVSR models verified successfully.", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models-from", type=Path, help="Reuse local model files after SHA-256 verification")
    parser.add_argument("--check", action="store_true", help="Verify model files without downloading")
    args = parser.parse_args()
    if args.check:
        verify_models()
    else:
        install_models(args.models_from)
        verify_models()


if __name__ == "__main__":
    main()
