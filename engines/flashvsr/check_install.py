"""Preflight the isolated environment without loading the large models."""
import json
from pathlib import Path
import subprocess
import sys

from installer import digest


def main():
    import torch
    import av
    import triton
    import sageattention
    import spas_sage_attn
    from flashvsr.runtime import load_models
    from flashvsr_worker import find_ffmpeg

    root = Path(__file__).resolve().parent
    if Path(sys.prefix).resolve() != (root / "env_venv").resolve():
        raise RuntimeError("FlashVSR must use its own env_venv.")
    if torch.__version__ != "2.10.0+cu130" or not torch.cuda.is_available():
        raise RuntimeError("Expected Torch 2.10.0+cu130 and an available NVIDIA CUDA GPU.")
    subprocess.run([find_ffmpeg(), "-version"], check=True, stdout=subprocess.DEVNULL)
    for name, spec in json.loads((root / "models.json").read_text()).items():
        if digest(root / "models" / name) != spec["sha256"]:
            raise RuntimeError(f"Model checksum mismatch: {name}")
    print(f"Verified isolated FlashVSR environment: {torch.cuda.get_device_name(0)}")


if __name__ == "__main__":
    main()
