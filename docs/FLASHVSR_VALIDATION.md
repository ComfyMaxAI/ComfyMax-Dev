# FlashVSR integration validation — 2026-09-11

Development checkout: D:\ComfyMax-Dev. Based on the working D:\ComfyMax-EN,
including its previously untracked FlashVSR page and client. The stable source
installation and standalone engine were not modified.

## Verified

- Fresh isolated Python 3.11 venv created at engines/flashvsr/env_venv.
- All pinned dependencies installed; pip check reports no conflicts.
- Four existing models copied and verified against recorded SHA-256 checksums.
- Real download of the 4.19 MB prompt model passed SHA-256 verification.
- Preflight passed on NVIDIA GeForce RTX 5060 Ti with Torch 2.10.0+cu130.
- Four unit tests pass: configured output and filename collisions, progress
  parsing, worker error reporting, and rejection of corrupt model copies.
- Syntax checks pass for App.py, pages, modules and the engine.
- Streamlit AppTest rendered all six pages without exceptions: App, FlashVSR
  Upscaler, Scene Builder, Settings, Video Gallery and Workflow Mapper.
- A real upscale was initiated from the ComfyMax UI venv through its client,
  which launched the new engine venv. Total time: 113.657 seconds.
- Input: 640x640, 124 frames, 24 fps, AAC, duration 5.167 seconds.
- Output: 1280x1280, 124 frames, 24 fps, AAC, duration 5.166667 seconds.
- Output audio packets match the source byte-for-byte through the video end.
  The existing -shortest mux behavior retains 162 of 163 source audio packets.
- Output saved to the configured ComfyUI output/videos/upscaled directory.

## Scope of validation

Existing pages were tested for rendering; new image/video generation through
ComfyUI, LM Studio unloading, and every workflow were not exercised. The real
GPU test used the integrated client, not the browser upload widget. A complete
multi-gigabyte model download was not repeated; all four local model checksums
and one real network download were checked. No GitHub remote is configured and
no changes were published.

## Start

Run D:\ComfyMax-Dev\Start_ComfyMax.bat. The UI uses its own .venv. On a new
checkout, Setup_ComfyMax.bat installs the UI dependencies; Install_FlashVSR.bat
installs the independent engine. Both environments are excluded from Git.

The settings currently point to D:\ComfyUI\ComfyUI\output. Configure another
existing absolute output directory in Settings when needed.
