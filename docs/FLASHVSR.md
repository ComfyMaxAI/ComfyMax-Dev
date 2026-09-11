# FlashVSR integration

FlashVSR runs as a subprocess in `engines/flashvsr/env_venv`, using Windows x64,
Python 3.11, Torch 2.10.0 CUDA 13 and the pinned packages in requirements.lock.txt.
ComfyMax's Streamlit environment remains separate.

Run Install_FlashVSR.bat, or use Install / repair FlashVSR on the upscaler page.
For migration without downloading the models again:

    py -3.11 engines/flashvsr/installer.py --models-from D:\ComfyMax-FlashVSR\models

Setup is repeatable; model files are verified with SHA-256 before being accepted.
Interrupted downloads are never promoted to model files. A setup lock prevents
two installers running together. If a process was forcibly terminated, remove
engines/flashvsr/.setup.lock before retrying.

In Settings, select the existing ComfyUI output directory. Upscaled videos go to
`<configured output>/videos/upscaled`. The existing Video Gallery scans subfolders.
Repeated filenames receive a numeric suffix. Original audio is copied, with AAC
fallback when the source codec cannot be copied into MP4.

The preserved preset is Tiny-Long, scale 2, MMGP profile 4, TCDecoder tiles 512,
top-k 0 (automatic), seed 0 and Two Pass disabled. The runtime is copied from the
tested standalone installation; only worker FFmpeg discovery and scale validation
change. FFmpeg uses PATH, a local engine binary, or imageio-ffmpeg's bundled binary.

Checks:

    py -3.11 -m unittest discover -s tests
    py -3.11 engines/flashvsr/installer.py --check

The preflight verifies imports, CUDA availability, model hashes and FFmpeg; it is
not an inference benchmark. Validate a representative clip with audio on the GPU
before release and compare frame count, dimensions, duration and audio.

Runtime source and original notices: https://github.com/deepbeepmeep/Wan2GP
(DeepBeepMeep, @deepbeepmeep). Model source:
https://huggingface.co/DeepBeepMeep/Wan2.1/tree/main/FlashVSR .
The attention wheels retain the original release URLs and SHA-256 values recorded
by the tested standalone environment. Environments, models and local settings
must not be committed.
