"""One-shot faster-whisper worker for ComfyMax."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio", required=True)
    parser.add_argument("--model", default="small")
    parser.add_argument("--language", default="")
    parser.add_argument("--device", choices=("cuda", "cpu"), required=True)
    parser.add_argument("--compute-type", required=True)
    args = parser.parse_args()

    path = Path(args.audio)
    if not path.is_file():
        raise FileNotFoundError(f"Audio file does not exist: {path}")

    from faster_whisper import WhisperModel

    model = WhisperModel(args.model, device=args.device, compute_type=args.compute_type)
    segments, info = model.transcribe(
        str(path), language=args.language or None, beam_size=5,
        vad_filter=True, condition_on_previous_text=True,
    )

    parts, segment_data = [], []
    for segment in segments:
        text = (segment.text or "").strip()
        if not text:
            continue
        parts.append(text)
        segment_data.append({
            "start": float(segment.start), "end": float(segment.end), "text": text
        })

    result = {
        "text": " ".join(parts).strip(),
        "segments": segment_data,
        "language": getattr(info, "language", args.language or None),
        "language_probability": float(getattr(info, "language_probability", 0.0) or 0.0),
        "model": args.model,
        "device": args.device,
        "compute_type": args.compute_type,
    }
    sys.stdout.write(json.dumps(result, ensure_ascii=False))
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
