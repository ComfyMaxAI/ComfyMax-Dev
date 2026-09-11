from __future__ import annotations

import json
import queue
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import streamlit as st

from modules.flashvsr_client import (
    FlashVSRError,
    FlashVSRProgress,
    run_flashvsr,
    validate_flashvsr_install,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config"
CONFIG_PATH = CONFIG_DIR / "flashvsr.json"
APP_CONFIG_PATH = CONFIG_DIR / "app.json"
APP_CONFIG_EXAMPLE_PATH = CONFIG_DIR / "app.example.json"

DEFAULT_ENGINE_DIR = r"D:\ComfyMax-FlashVSR"
DEFAULT_LM_URL = "http://127.0.0.1:1234/v1"
DEFAULT_COMFY_URL = "http://127.0.0.1:8188"


def load_config() -> dict:
    if not CONFIG_PATH.is_file():
        return {"engine_dir": DEFAULT_ENGINE_DIR}
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"engine_dir": DEFAULT_ENGINE_DIR}
    if not isinstance(data, dict):
        return {"engine_dir": DEFAULT_ENGINE_DIR}
    return {"engine_dir": str(data.get("engine_dir") or DEFAULT_ENGINE_DIR)}


def save_config(data: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def load_app_config() -> dict:
    path = APP_CONFIG_PATH if APP_CONFIG_PATH.is_file() else APP_CONFIG_EXAMPLE_PATH
    if not path.is_file():
        return {"lmstudio_url": DEFAULT_LM_URL, "comfyui_url": DEFAULT_COMFY_URL}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"lmstudio_url": DEFAULT_LM_URL, "comfyui_url": DEFAULT_COMFY_URL}
    return {
        "lmstudio_url": str(data.get("lmstudio_url") or DEFAULT_LM_URL),
        "comfyui_url": str(data.get("comfyui_url") or DEFAULT_COMFY_URL),
    }


def safe_output_name(input_name: str) -> str:
    stem = Path(input_name).stem.strip() or "video"
    stem = "".join(
        character if character.isalnum() or character in "-_ " else "_"
        for character in stem
    ).strip()
    return f"{stem or 'video'}_flashvsr_2x.mp4"


def _to_float(value: str):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def read_nvidia_gpu_stats() -> dict:
    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        fallback = Path(r"C:\Windows\System32\nvidia-smi.exe")
        if fallback.exists():
            nvidia_smi = str(fallback)
    if not nvidia_smi:
        raise RuntimeError("nvidia-smi was not found.")

    query = ",".join(
        ["name", "utilization.gpu", "memory.used", "memory.total",
         "temperature.gpu", "power.draw"]
    )
    result = subprocess.run(
        [nvidia_smi, f"--query-gpu={query}", "--format=csv,noheader,nounits"],
        capture_output=True,
        text=True,
        timeout=5,
        check=True,
    )
    first_line = next(
        (line.strip() for line in result.stdout.splitlines() if line.strip()), ""
    )
    if not first_line:
        raise RuntimeError("nvidia-smi returned no GPU information.")
    parts = [part.strip() for part in first_line.split(",")]
    if len(parts) < 6:
        raise RuntimeError("Unexpected response from nvidia-smi.")
    return {
        "name": parts[0],
        "gpu_util": _to_float(parts[1]),
        "memory_used_mb": _to_float(parts[2]),
        "memory_total_mb": _to_float(parts[3]),
        "temperature_c": _to_float(parts[4]),
        "power_w": _to_float(parts[5]),
    }


def draw_gpu_monitor_values() -> None:
    try:
        gpu = read_nvidia_gpu_stats()
    except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
        st.caption(f"GPU status unavailable: {exc}")
        return

    used_mb = gpu.get("memory_used_mb")
    total_mb = gpu.get("memory_total_mb")
    memory_fraction = 0.0
    if used_mb is not None and total_mb:
        memory_fraction = max(0.0, min(used_mb / total_mb, 1.0))

    gpu_name = gpu.get("name", "NVIDIA GPU").replace("NVIDIA GeForce ", "")
    st.caption(gpu_name)

    status = []
    if gpu.get("gpu_util") is not None:
        status.append(f"GPU **{gpu['gpu_util']:.0f}%**")
    if gpu.get("temperature_c") is not None:
        status.append(f"**{gpu['temperature_c']:.0f} °C**")
    if gpu.get("power_w") is not None:
        status.append(f"**{gpu['power_w']:.0f} W**")
    if status:
        st.markdown(" · ".join(status))

    memory_text = "VRAM"
    if used_mb is not None and total_mb:
        memory_text += (
            f" · {used_mb / 1024.0:.1f} / {total_mb / 1024.0:.1f} GB"
            f" · {memory_fraction * 100:.0f}%"
        )
    st.progress(memory_fraction, text=memory_text)


def refresh_gpu_monitor_now() -> None:
    slot = globals().get("GPU_MONITOR_SLOT")
    if slot is None:
        return
    with slot.container():
        draw_gpu_monitor_values()


def run_with_live_gpu(
    func,
    *,
    event_queue: queue.Queue | None = None,
    event_handler=None,
    interval: float = 1.0,
):
    """
    Run a blocking task in a worker thread while ALL Streamlit UI updates
    stay on the main Streamlit thread.

    The worker may put plain Python events into event_queue. event_handler
    is called only from the main thread.
    """
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(func)

        while not future.done():
            if event_queue is not None and event_handler is not None:
                while True:
                    try:
                        event = event_queue.get_nowait()
                    except queue.Empty:
                        break
                    event_handler(event)

            refresh_gpu_monitor_now()
            time.sleep(interval)

        # Drain any events produced just before the worker finished.
        if event_queue is not None and event_handler is not None:
            while True:
                try:
                    event = event_queue.get_nowait()
                except queue.Empty:
                    break
                event_handler(event)

        refresh_gpu_monitor_now()
        return future.result()


def unload_comfyui_models(comfy_url: str) -> None:
    url = comfy_url.rstrip("/") + "/free"
    payload = json.dumps(
        {"unload_models": True, "free_memory": True}
    ).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            if not 200 <= response.status < 300:
                raise RuntimeError(f"ComfyUI returned HTTP status {response.status}.")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"ComfyUI returned HTTP {exc.code}.") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"ComfyUI is unreachable: {exc.reason}") from exc


def unload_all_lmstudio_models(lm_url: str) -> int:
    base_url = lm_url.rstrip("/")
    if base_url.endswith("/v1"):
        base_url = base_url[:-3]

    models_url = base_url + "/api/v1/models"
    try:
        request = urllib.request.Request(models_url, method="GET")
        with urllib.request.urlopen(request, timeout=10) as response:
            if not 200 <= response.status < 300:
                raise RuntimeError(f"LM Studio returned HTTP status {response.status}.")
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"LM Studio returned HTTP {exc.code}.") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"LM Studio is unreachable: {exc.reason}") from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RuntimeError("LM Studio returned an invalid model list.") from exc

    instance_ids = []
    for model in data.get("models", []):
        for instance in model.get("loaded_instances", []) or []:
            instance_id = instance.get("id")
            if instance_id:
                instance_ids.append(str(instance_id))

    if not instance_ids:
        return 0

    unload_url = base_url + "/api/v1/models/unload"
    unloaded_count = 0

    for instance_id in instance_ids:
        payload = json.dumps({"instance_id": instance_id}).encode("utf-8")
        request = urllib.request.Request(
            unload_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                if not 200 <= response.status < 300:
                    raise RuntimeError(
                        f"LM Studio returned HTTP status {response.status} "
                        f"while unloading {instance_id}."
                    )
            unloaded_count += 1
        except urllib.error.HTTPError as exc:
            raise RuntimeError(
                f"LM Studio returned HTTP {exc.code} while unloading {instance_id}."
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"LM Studio became unreachable while unloading {instance_id}: "
                f"{exc.reason}"
            ) from exc

    return unloaded_count


st.set_page_config(
    page_title="FlashVSR Upscaler - ComfyMax",
    page_icon="🔎",
    layout="wide",
)

st.title("FlashVSR Video Upscaler")
st.caption(
    "Upscale a finished MiniMax video locally with FlashVSR Tiny-Long. "
    "The current integration uses 2× upscale and preserves the original audio."
)

config = load_config()
app_config = load_app_config()

with st.sidebar:
    st.header("FlashVSR")

    engine_dir = st.text_input(
        "FlashVSR engine folder",
        value=config.get("engine_dir", DEFAULT_ENGINE_DIR),
        help="Folder containing env_venv, flashvsr, models and flashvsr_worker.py.",
    )

    save_col, test_col = st.columns(2)

    with save_col:
        if st.button("Save path", use_container_width=True):
            try:
                save_config({"engine_dir": engine_dir.strip()})
                st.success("Saved.")
            except OSError as exc:
                st.error(f"Could not save configuration: {exc}")

    with test_col:
        if st.button("Test", use_container_width=True):
            try:
                validate_flashvsr_install(engine_dir)
                st.success("FlashVSR is ready.")
            except FlashVSRError as exc:
                st.error(str(exc))

    st.divider()

    with st.container(border=True):
        st.markdown("##### GPU monitor")
        GPU_MONITOR_SLOT = st.empty()

        if hasattr(st, "fragment"):
            @st.fragment(run_every="1s")
            def render_gpu_monitor_fragment() -> None:
                with GPU_MONITOR_SLOT.container():
                    draw_gpu_monitor_values()

            render_gpu_monitor_fragment()
        else:
            with GPU_MONITOR_SLOT.container():
                draw_gpu_monitor_values()

        unload_comfy_clicked = st.button(
            "Unload model from ComfyUI",
            use_container_width=True,
            key="flashvsr_unload_comfyui_models",
        )
        unload_lmstudio_clicked = st.button(
            "Unload all models from LM Studio",
            use_container_width=True,
            key="flashvsr_unload_all_lmstudio_models",
        )

    if unload_comfy_clicked:
        try:
            unload_comfyui_models(app_config["comfyui_url"])
            time.sleep(0.75)
            refresh_gpu_monitor_now()
            st.success("ComfyUI model unload requested.")
        except RuntimeError as exc:
            st.error(str(exc))

    if unload_lmstudio_clicked:
        try:
            unloaded_count = unload_all_lmstudio_models(app_config["lmstudio_url"])
            time.sleep(0.75)
            refresh_gpu_monitor_now()
            if unloaded_count == 0:
                st.info("No models are currently loaded in LM Studio.")
            elif unloaded_count == 1:
                st.success("1 LM Studio model was unloaded.")
            else:
                st.success(f"{unloaded_count} LM Studio models were unloaded.")
        except RuntimeError as exc:
            st.error(str(exc))

    st.info(
        "For maximum available VRAM, unload ComfyUI and LM Studio models "
        "before starting an upscale."
    )


left, right = st.columns([1.1, 1.0], gap="large")

with left:
    st.subheader("1. Select video")

    uploaded = st.file_uploader(
        "Video",
        type=["mp4", "mov", "mkv", "webm", "avi"],
        accept_multiple_files=False,
    )

    if uploaded is not None:
        st.video(uploaded.getvalue())
        st.caption(f"Input: {uploaded.name}")

    st.subheader("2. Upscale settings")

    setting_col1, setting_col2 = st.columns(2)

    with setting_col1:
        st.text_input("Upscale", value="2×", disabled=True)

    with setting_col2:
        st.text_input("Model", value="FlashVSR Tiny-Long", disabled=True)

    st.caption(
        "This first ComfyMax integration keeps the proven settings: "
        "2×, Tiny-Long, automatic sparse top-k and 512 px TCDecoder tiling."
    )

    can_start = uploaded is not None and bool(engine_dir.strip())

    start_clicked = st.button(
        "Start FlashVSR upscale",
        type="primary",
        use_container_width=True,
        disabled=not can_start,
    )

with right:
    st.subheader("Upscale result")

    if st.session_state.get("flashvsr_output_bytes"):
        result_bytes = st.session_state["flashvsr_output_bytes"]
        result_name = st.session_state.get(
            "flashvsr_output_name",
            "flashvsr_upscaled.mp4",
        )

        st.video(result_bytes)
        st.success("FlashVSR upscale complete.")

        st.download_button(
            "Download upscaled video",
            data=result_bytes,
            file_name=result_name,
            mime="video/mp4",
            use_container_width=True,
        )

        output_path = st.session_state.get("flashvsr_output_path")
        if output_path:
            st.caption(f"Saved locally: {output_path}")

        elapsed = st.session_state.get("flashvsr_elapsed_seconds")
        if elapsed is not None:
            st.caption(f"Total time: {elapsed:.2f} seconds")
    else:
        st.info("The upscaled video will appear here after processing.")


if start_clicked and uploaded is not None:
    try:
        validate_flashvsr_install(engine_dir)
    except FlashVSRError as exc:
        st.error(str(exc))
        st.stop()

    engine_root = Path(engine_dir).expanduser().resolve()
    engine_output_dir = engine_root / "output"
    engine_output_dir.mkdir(parents=True, exist_ok=True)

    output_name = safe_output_name(uploaded.name)
    final_output = engine_output_dir / output_name

    suffix = Path(uploaded.name).suffix or ".mp4"
    temp_input_path = None

    progress_slot = st.empty()
    status_slot = st.empty()
    log_slot = st.empty()
    log_lines: list[str] = []
    ui_events: queue.Queue = queue.Queue()

    # IMPORTANT:
    # These callbacks run inside the FlashVSR worker thread.
    # They must never call Streamlit directly. They only place plain
    # Python data on a queue; the main Streamlit thread renders it.
    def on_progress(progress: FlashVSRProgress) -> None:
        ui_events.put(("progress", progress))

    def on_log(line: str) -> None:
        if line:
            ui_events.put(("log", line))

    def handle_ui_event(event) -> None:
        event_type, payload = event

        if event_type == "progress":
            progress = payload
            progress_slot.progress(
                progress.percent,
                text=f"{progress.percent}% · {progress.message}",
            )
            status_slot.info(progress.message)
            return

        if event_type == "log":
            log_lines.append(str(payload))
            del log_lines[:-30]
            log_slot.code("\\n".join(log_lines), language="text")

    try:
        with tempfile.NamedTemporaryFile(
            delete=False,
            suffix=suffix,
            prefix="comfymax_flashvsr_",
        ) as temp_file:
            temp_file.write(uploaded.getvalue())
            temp_input_path = Path(temp_file.name)

        st.session_state.pop("flashvsr_output_bytes", None)
        st.session_state.pop("flashvsr_output_name", None)
        st.session_state.pop("flashvsr_output_path", None)
        st.session_state.pop("flashvsr_elapsed_seconds", None)

        started = time.perf_counter()

        def do_upscale():
            return run_flashvsr(
                engine_dir=engine_dir,
                input_path=temp_input_path,
                output_path=final_output,
                scale=2.0,
                progress_callback=on_progress,
                log_callback=on_log,
            )

        result = run_with_live_gpu(
            do_upscale,
            event_queue=ui_events,
            event_handler=handle_ui_event,
            interval=1.0,
        )

        elapsed = time.perf_counter() - started
        result_bytes = result.output_path.read_bytes()

        st.session_state["flashvsr_output_bytes"] = result_bytes
        st.session_state["flashvsr_output_name"] = result.output_path.name
        st.session_state["flashvsr_output_path"] = str(result.output_path)
        st.session_state["flashvsr_elapsed_seconds"] = elapsed

        progress_slot.progress(100, text="100% · Complete")
        status_slot.success("FlashVSR upscale complete.")
        refresh_gpu_monitor_now()
        st.rerun()

    except (FlashVSRError, OSError, RuntimeError) as exc:
        status_slot.error("FlashVSR upscale failed.")
        st.error(str(exc))

    finally:
        if temp_input_path is not None:
            try:
                temp_input_path.unlink(missing_ok=True)
            except OSError:
                pass
