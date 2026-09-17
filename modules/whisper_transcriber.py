"""Isolated local faster-whisper transcription helper for ComfyMax.

Each transcription runs in a separate Python process. This prevents a
faster-whisper/CTranslate2 CUDA model from remaining attached to the long-lived
Streamlit process and makes repeated scene transcription reliable.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


class WhisperTranscriptionError(RuntimeError):
    """Raised when local Whisper transcription cannot be completed."""


def _worker_path() -> Path:
    return Path(__file__).with_name("whisper_worker.py")


def _attempt(path, model_size, language, device, compute_type, timeout_seconds):
    worker = _worker_path()
    if not worker.is_file():
        raise WhisperTranscriptionError(f"Whisper worker is missing: {worker}")

    command = [
        sys.executable, str(worker),
        "--audio", str(path),
        "--model", model_size,
        "--language", language or "",
        "--device", device,
        "--compute-type", compute_type,
    ]
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout_seconds, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise WhisperTranscriptionError(
            f"Whisper transcription timed out after {timeout_seconds} seconds."
        ) from exc
    except OSError as exc:
        raise WhisperTranscriptionError(f"Could not start the Whisper worker: {exc}") from exc

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise WhisperTranscriptionError(
            "Whisper worker failed" + (f": {detail}" if detail else ".")
        )
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise WhisperTranscriptionError("Whisper worker returned an invalid result.") from exc
    if not isinstance(result, dict):
        raise WhisperTranscriptionError("Whisper worker returned an invalid result.")
    return result


def transcribe_audio(
    audio_path: str | Path, *, model_size: str = "small",
    language: str | None = None, prefer_gpu: bool = True,
    timeout_seconds: int = 600,
) -> dict:
    """Transcribe one audio file in an isolated one-shot worker process."""
    path = Path(audio_path).resolve()
    if not path.is_file():
        raise WhisperTranscriptionError(f"Audio file does not exist: {path}")

    gpu_error = None
    if prefer_gpu:
        try:
            result = _attempt(path, model_size, language, "cuda", "float16", timeout_seconds)
            result["gpu_fallback"] = False
            result["gpu_error"] = ""
            return result
        except WhisperTranscriptionError as exc:
            gpu_error = str(exc)

    try:
        result = _attempt(path, model_size, language, "cpu", "int8", timeout_seconds)
        result["gpu_fallback"] = bool(prefer_gpu)
        result["gpu_error"] = gpu_error or ""
        return result
    except WhisperTranscriptionError as cpu_exc:
        if gpu_error:
            raise WhisperTranscriptionError(
                "Whisper could not transcribe this scene. "
                f"GPU attempt failed ({gpu_error}) and CPU fallback also failed ({cpu_exc})."
            ) from cpu_exc
        raise
