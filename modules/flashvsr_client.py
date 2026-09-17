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


def flashvsr_install_status(engine_dir: str | Path) -> dict:
    root = Path(engine_dir).expanduser().resolve()
    python_exe = root / "env_venv" / "Scripts" / "python.exe"
    worker = root / "flashvsr_worker.py"
    manifest_path = root / "models.json"
    model_dir = root / "models"

    runtime_missing = []
    if not root.is_dir():
        runtime_missing.append(f"Engine folder: {root}")
    if not python_exe.is_file():
        runtime_missing.append(f"Python environment: {python_exe}")
    if not worker.is_file():
        runtime_missing.append(f"Worker script: {worker}")

    required_models = [
        "FlashVSR_v1.1_transformer_bf16.safetensors",
        "FlashVSR_v1.1_lq_proj_bf16.safetensors",
        "FlashVSR_v1.1_posi_prompt_bf16.safetensors",
        "FlashVSR_v1.1_tcdecoder_bf16.safetensors",
    ]
    if manifest_path.is_file():
        try:
            import json
            required_models = list(json.loads(manifest_path.read_text(encoding="utf-8")).keys())
        except (OSError, ValueError, TypeError):
            pass

    missing_models = [name for name in required_models if not (model_dir / name).is_file()]

    return {
        "root": root,
        "python": python_exe,
        "worker": worker,
        "models": model_dir,
        "runtime_ready": not runtime_missing,
        "models_ready": not missing_models,
        "runtime_missing": runtime_missing,
        "missing_models": missing_models,
    }


def validate_flashvsr_runtime(engine_dir: str | Path) -> dict[str, Path]:
    status = flashvsr_install_status(engine_dir)
    if not status["runtime_ready"]:
        details = "\n".join(f"- {item}" for item in status["runtime_missing"])
        raise FlashVSRError("FlashVSR runtime is not installed.\n\n" + details)
    return {
        "root": status["root"],
        "python": status["python"],
        "worker": status["worker"],
        "models": status["models"],
    }


def validate_flashvsr_install(engine_dir: str | Path) -> dict[str, Path]:
    install = validate_flashvsr_runtime(engine_dir)
    status = flashvsr_install_status(engine_dir)
    if not status["models_ready"]:
        details = "\n".join(f"- {name}" for name in status["missing_models"])
        raise FlashVSRError(
            "FlashVSR runtime is ready, but the optional models are not installed.\n\n"
            "Run Download_FlashVSR_Models.bat from the ComfyMax folder.\n\n"
            "Missing models:\n" + details
        )
    return install

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
