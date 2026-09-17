"""Preflight the isolated FlashVSR runtime without requiring model files."""
from pathlib import Path
import subprocess
import sys


def main():
    import torch
    import av
    import triton
    import sageattention
    import spas_sage_attn
    from flashvsr.runtime import load_models  # noqa: F401
    from flashvsr_worker import find_ffmpeg

    root = Path(__file__).resolve().parent
    if Path(sys.prefix).resolve() != (root / "env_venv").resolve():
        raise RuntimeError("FlashVSR must use its own env_venv.")
    if torch.__version__ != "2.10.0+cu130" or not torch.cuda.is_available():
        raise RuntimeError("Expected Torch 2.10.0+cu130 and an available NVIDIA CUDA GPU.")
    subprocess.run([find_ffmpeg(), "-version"], check=True, stdout=subprocess.DEVNULL)
    print(f"Verified isolated FlashVSR runtime: {torch.cuda.get_device_name(0)}")


if __name__ == "__main__":
    main()
