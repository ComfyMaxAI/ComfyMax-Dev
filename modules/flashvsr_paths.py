"""FlashVSR paths, independent of Streamlit and the GPU environment."""
import json
from pathlib import Path


def output_directory(root):
    path = Path(root) / "config" / "settings.json"
    try:
        settings = json.loads(path.read_text(encoding="utf-8"))
        value = settings.get("comfyui_output_folder", "").strip()
    except (OSError, ValueError, AttributeError) as exc:
        raise ValueError("Save a ComfyUI output folder in Settings first.") from exc
    if not value:
        raise ValueError("Save a ComfyUI output folder in Settings first.")
    base = Path(value).expanduser()
    if not base.is_absolute() or not base.is_dir():
        raise ValueError("The ComfyUI output folder in Settings must be an existing absolute folder.")
    return base / "videos" / "upscaled"


def reserve_output(folder, name):
    """Atomically reserve a name so uploads and concurrent sessions never overwrite videos."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    name = Path(name).name
    for index in range(10000):
        candidate = folder / (name if index == 0 else f"{Path(name).stem}_{index}{Path(name).suffix}")
        try:
            with candidate.open("xb"):
                pass
            return candidate
        except FileExistsError:
            continue
    raise RuntimeError("Could not reserve an output filename.")
