"""Local faster-whisper transcription helper for ComfyMax Music Video Director.

GPU acceleration is attempted first. If the CUDA runtime is unavailable or fails,
ComfyMax automatically retries on CPU so transcription remains usable.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path


class WhisperTranscriptionError(RuntimeError):
    """Raised when local Whisper transcription cannot be completed."""


@lru_cache(maxsize=4)
def _load_model(model_size: str, device: str, compute_type: str):
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise WhisperTranscriptionError(
            "faster-whisper is not installed in the ComfyMax environment."
        ) from exc

    return WhisperModel(model_size, device=device, compute_type=compute_type)


def _run_transcription(model, path: Path, language: str | None):
    segments, info = model.transcribe(
        str(path),
        language=language or None,
        beam_size=5,
        vad_filter=True,
        condition_on_previous_text=True,
    )
    parts = []
    segment_data = []
    for segment in segments:
        text = (segment.text or "").strip()
        if not text:
            continue
        parts.append(text)
        segment_data.append({
            "start": float(segment.start),
            "end": float(segment.end),
            "text": text,
        })
    return " ".join(parts).strip(), segment_data, info


def _attempt(path: Path, model_size: str, language: str | None, device: str, compute_type: str):
    model = _load_model(model_size, device, compute_type)
    text, segments, info = _run_transcription(model, path, language)
    return {
        "text": text,
        "segments": segments,
        "language": getattr(info, "language", language),
        "language_probability": float(getattr(info, "language_probability", 0.0) or 0.0),
        "model": model_size,
        "device": device,
        "compute_type": compute_type,
    }


def transcribe_audio(
    audio_path: str | Path,
    *,
    model_size: str = "small",
    language: str | None = None,
    prefer_gpu: bool = True,
) -> dict:
    """Transcribe scene audio, automatically falling back from CUDA to CPU.

    Returns transcription metadata including ``device`` and ``gpu_fallback`` so
    the UI can tell the user which backend was actually used.
    """
    path = Path(audio_path)
    if not path.is_file():
        raise WhisperTranscriptionError(f"Audio file does not exist: {path}")

    gpu_error = None
    if prefer_gpu:
        try:
            result = _attempt(path, model_size, language, "cuda", "float16")
            result["gpu_fallback"] = False
            result["gpu_error"] = ""
            return result
        except Exception as exc:
            gpu_error = str(exc)
            # A failed CUDA model may remain cached only if construction succeeded;
            # clear the cache before retrying on CPU to keep recovery predictable.
            _load_model.cache_clear()

    try:
        result = _attempt(path, model_size, language, "cpu", "int8")
        result["gpu_fallback"] = bool(prefer_gpu)
        result["gpu_error"] = gpu_error or ""
        return result
    except Exception as cpu_exc:
        if gpu_error:
            raise WhisperTranscriptionError(
                "Whisper could not transcribe this scene. GPU acceleration was unavailable "
                f"({gpu_error}) and the CPU fallback also failed ({cpu_exc})."
            ) from cpu_exc
        raise WhisperTranscriptionError(
            f"Whisper CPU transcription failed: {cpu_exc}"
        ) from cpu_exc
