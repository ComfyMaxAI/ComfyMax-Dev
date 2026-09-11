from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass
class FlashVSRProgress:
    percent: int
    message: str


@dataclass
class FlashVSRResult:
    output_path: Path
    return_code: int
    log_text: str


class FlashVSRError(RuntimeError):
    pass


def _parse_progress_line(line: str) -> FlashVSRProgress | None:
    prefix = "COMFYMAX_PROGRESS|"
    if not line.startswith(prefix):
        return None

    parts = line.rstrip("\r\n").split("|", 2)
    if len(parts) != 3:
        return None

    try:
        percent = max(0, min(100, int(parts[1])))
    except ValueError:
        return None

    return FlashVSRProgress(percent=percent, message=parts[2].strip())


def _parse_result_line(line: str) -> Path | None:
    prefix = "COMFYMAX_RESULT|"
    if not line.startswith(prefix):
        return None

    value = line[len(prefix):].strip()
    return Path(value) if value else None


def validate_flashvsr_install(engine_dir: str | Path) -> dict[str, Path]:
    root = Path(engine_dir).expanduser().resolve()
    python_exe = root / "env_venv" / "Scripts" / "python.exe"
    worker = root / "flashvsr_worker.py"
    model_dir = root / "models"

    required_models = [
        "FlashVSR_v1.1_transformer_bf16.safetensors",
        "FlashVSR_v1.1_lq_proj_bf16.safetensors",
        "FlashVSR_v1.1_posi_prompt_bf16.safetensors",
        "FlashVSR_v1.1_tcdecoder_bf16.safetensors",
    ]

    missing: list[str] = []

    if not root.is_dir():
        missing.append(f"Engine folder: {root}")
    if not python_exe.is_file():
        missing.append(f"Python environment: {python_exe}")
    if not worker.is_file():
        missing.append(f"Worker script: {worker}")

    for model_name in required_models:
        model_path = model_dir / model_name
        if not model_path.is_file():
            missing.append(f"Model: {model_path}")

    if missing:
        details = "\n".join(f"- {item}" for item in missing)
        raise FlashVSRError(
            "FlashVSR installation is incomplete.\n\n"
            f"{details}"
        )

    return {
        "root": root,
        "python": python_exe,
        "worker": worker,
        "models": model_dir,
    }


def run_flashvsr(
    engine_dir: str | Path,
    input_path: str | Path,
    output_path: str | Path,
    *,
    scale: float = 2.0,
    progress_callback: Callable[[FlashVSRProgress], None] | None = None,
    log_callback: Callable[[str], None] | None = None,
) -> FlashVSRResult:
    install = validate_flashvsr_install(engine_dir)

    input_path = Path(input_path).resolve()
    output_path = Path(output_path).resolve()

    if not input_path.is_file():
        raise FlashVSRError(f"Input video does not exist: {input_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    command = [
        str(install["python"]),
        "-u",
        str(install["worker"]),
        "--input",
        str(input_path),
        "--output",
        str(output_path),
        "--scale",
        str(float(scale)),
    ]

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    process = subprocess.Popen(
        command,
        cwd=str(install["root"]),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        env=env,
    )

    log_lines: list[str] = []
    reported_output: Path | None = None

    assert process.stdout is not None

    for raw_line in process.stdout:
        line = raw_line.rstrip("\r\n")
        log_lines.append(line)

        progress = _parse_progress_line(line)
        if progress is not None:
            if progress_callback:
                progress_callback(progress)
            continue

        result_path = _parse_result_line(line)
        if result_path is not None:
            reported_output = result_path
            continue

        if log_callback:
            log_callback(line)

    return_code = process.wait()
    log_text = "\n".join(log_lines)

    if return_code != 0:
        raise FlashVSRError(
            "FlashVSR worker stopped with an error.\n\n"
            + (log_text[-8000:] if log_text else "No worker log was returned.")
        )

    final_output = reported_output or output_path

    if not final_output.is_file() or final_output.stat().st_size <= 0:
        raise FlashVSRError(
            "FlashVSR finished without creating a valid output video.\n\n"
            f"Expected: {final_output}"
        )

    return FlashVSRResult(
        output_path=final_output,
        return_code=return_code,
        log_text=log_text,
    )
