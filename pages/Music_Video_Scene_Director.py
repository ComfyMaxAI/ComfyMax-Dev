"""Selected-scene directing, generation and rendering using ComfyMax services."""
import json
import hashlib
import re
import sqlite3
import subprocess
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import streamlit as st

from modules.comfyui import ComfyUIClient, ComfyUIError, ComfyRenderError
from modules.lmstudio import LMStudioClient, LMStudioError, ModelLoadConfirmationRequired
from modules.music_video_director import (
    KEY, ProjectStore, approve_scene, compose_prompt, export_project, import_project,
    scene_info, scene_status, signature, timeline, title, validate_project,
)
from modules.h3_music_prompt_builder import build_h3_music_prompt
from modules.music_video_ui import (
    duration_matches, lyrics_transcription_ui, mapped_inputs, preset,
    store_project_audio, read_project_audio,
)
from modules.scene_workflow import (
    check_render, render_asset_path, load_mapped_workflow, mapped_workflows, prompt_system, submit_mapped_workflow, video_output_node_id,
)

ROOT = Path(__file__).resolve().parents[1]


def _to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def read_nvidia_gpu_stats():
    nvidia_smi = __import__("shutil").which("nvidia-smi")
    if not nvidia_smi:
        fallback = Path(r"C:\Windows\System32\nvidia-smi.exe")
        if fallback.exists():
            nvidia_smi = str(fallback)
    if not nvidia_smi:
        raise RuntimeError("nvidia-smi was not found.")

    query = ",".join([
        "name", "utilization.gpu", "memory.used", "memory.total",
        "temperature.gpu", "power.draw",
    ])
    result = subprocess.run(
        [nvidia_smi, f"--query-gpu={query}", "--format=csv,noheader,nounits"],
        capture_output=True, text=True, timeout=5, check=True,
    )
    line = next((line.strip() for line in result.stdout.splitlines() if line.strip()), "")
    parts = [part.strip() for part in line.split(",")]
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


def draw_gpu_monitor():
    try:
        gpu = read_nvidia_gpu_stats()
    except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
        st.caption(f"GPU status unavailable: {exc}")
        return

    used = gpu.get("memory_used_mb")
    total = gpu.get("memory_total_mb")
    fraction = max(0.0, min(used / total, 1.0)) if used is not None and total else 0.0
    name = gpu.get("name", "NVIDIA GPU").replace("NVIDIA GeForce ", "")
    st.caption(name)

    status = []
    if gpu.get("gpu_util") is not None:
        status.append(f"GPU **{gpu['gpu_util']:.0f}%**")
    if gpu.get("temperature_c") is not None:
        status.append(f"**{gpu['temperature_c']:.0f} °C**")
    if gpu.get("power_w") is not None:
        status.append(f"**{gpu['power_w']:.0f} W**")
    if status:
        st.markdown(" · ".join(status))

    text = "VRAM"
    if used is not None and total:
        text += f" · {used / 1024:.1f} / {total / 1024:.1f} GB · {fraction * 100:.0f}%"
    st.progress(fraction, text=text)


def unload_comfyui_models(comfy_url):
    url = comfy_url.rstrip("/") + "/free"
    payload = json.dumps({"unload_models": True, "free_memory": True}).encode("utf-8")
    request = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            if not 200 <= response.status < 300:
                raise RuntimeError(f"ComfyUI returned HTTP status {response.status}.")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"ComfyUI returned HTTP {exc.code}.") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"ComfyUI is unreachable: {exc.reason}") from exc


def comfyui_unet_models(comfy_url):
    """Return UNET/diffusion model filenames reported by ComfyUI."""
    url = comfy_url.rstrip("/") + "/object_info/UNETLoader"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, method="GET"), timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RuntimeError(f"Could not read ComfyUI video model list: {exc}") from exc

    try:
        spec = data["UNETLoader"]["input"]["required"]["unet_name"]
        options = spec[0] if isinstance(spec, list) and spec else []
    except (KeyError, TypeError, IndexError):
        options = []
    return [str(value) for value in options if value]


def unload_all_lmstudio_models(lm_url):
    base_url = lm_url.rstrip("/")
    if base_url.endswith("/v1"):
        base_url = base_url[:-3]

    try:
        with urllib.request.urlopen(
            urllib.request.Request(base_url + "/api/v1/models", method="GET"), timeout=10
        ) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RuntimeError(f"Could not read LM Studio model list: {exc}") from exc

    ids = [
        str(instance["id"])
        for model in data.get("models", [])
        for instance in (model.get("loaded_instances", []) or [])
        if instance.get("id")
    ]
    for instance_id in ids:
        payload = json.dumps({"instance_id": instance_id}).encode("utf-8")
        request = urllib.request.Request(
            base_url + "/api/v1/models/unload",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                if not 200 <= response.status < 300:
                    raise RuntimeError(f"LM Studio returned HTTP status {response.status}.")
        except (urllib.error.HTTPError, urllib.error.URLError) as exc:
            raise RuntimeError(f"Could not unload LM Studio model: {exc}") from exc
    return len(ids)

st.set_page_config(page_title="Music Video Scene Director · ComfyMax", page_icon="🎵", layout="wide")
st.markdown(
    """
    <style>
    .st-key-mvd_generate_prompt button {
        background-color: #16a34a !important;
        border-color: #16a34a !important;
        color: white !important;
        font-weight: 600 !important;
    }
    .st-key-mvd_generate_prompt button:hover {
        background-color: #15803d !important;
        border-color: #15803d !important;
        color: white !important;
    }
    .st-key-mvd_generate_prompt button:disabled {
        background-color: #166534 !important;
        border-color: #166534 !important;
        color: rgba(255, 255, 255, 0.65) !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)
st.title("Music Video Scene Director")
st.caption("Import Scene Builder scenes.json, direct one scene at a time, and review every prompt before rendering.")
st.page_link("App.py", label="Main ComfyMax generator", icon="🎬")
store = ProjectStore(ROOT / "data" / "music_video_projects.sqlite3")


with st.sidebar:
    st.header("Local services")
    director_lm_url = st.text_input("LM Studio", value="http://127.0.0.1:1234", key="mvd_lm_url")
    director_comfy_url = st.text_input("ComfyUI", value="http://127.0.0.1:8188", key="mvd_comfy_url")
    st.caption("Use LM Studio or the local H3 builder for prompts. ComfyUI is required for rendering.")
    st.divider()

    with st.container(border=True):
        st.markdown("##### GPU monitor")
        gpu_slot = st.empty()
        with gpu_slot.container():
            draw_gpu_monitor()

        unload_comfy_clicked = st.button(
            "Unload model from ComfyUI", use_container_width=True, key="mvd_unload_comfy"
        )
        st.caption(
            "Unloads the currently loaded ComfyUI model and frees the VRAM cache. "
            "Use this when you no longer need the model."
        )

        unload_lm_clicked = st.button(
            "Unload all models from LM Studio", use_container_width=True, key="mvd_unload_lm"
        )
        st.caption(
            "Unloads every model currently loaded in LM Studio and frees the memory used by those models."
        )




def choose_scenes_folder(initial_folder=""):
    """Open a folder picker on the computer running ComfyMax."""
    try:
        import tkinter as tk
        from tkinter import filedialog
        window = tk.Tk()
        window.withdraw()
        try:
            window.attributes("-topmost", True)
        except tk.TclError:
            pass
        selected = filedialog.askdirectory(
            title="Select scenes folder",
            initialdir=initial_folder if initial_folder and Path(initial_folder).is_dir() else None,
            mustexist=True,
        )
        window.destroy()
        return selected or ""
    except Exception as exc:
        raise RuntimeError(f"Could not open the folder picker: {exc}") from exc


def extract_last_frame(video_path, output_path):
    """Extract the final usable video frame to a PNG with FFmpeg."""
    video_path = Path(video_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    command = [
        "ffmpeg",
        "-y",
        "-sseof",
        "-0.05",
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        "-update",
        "1",
        str(output_path),
    ]
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=30, check=False
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "FFmpeg was not found. Add ffmpeg.exe to PATH before using automatic last-frame extraction."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("FFmpeg timed out while extracting the last frame.") from exc

    if result.returncode != 0 or not output_path.is_file():
        details = (result.stderr or result.stdout or "Unknown FFmpeg error").strip()
        raise RuntimeError(f"Could not extract the last frame with FFmpeg: {details}")
    return output_path


def scene_audio_from_folder(folder, scene):
    """Find the exported scene WAV for the selected scene."""
    if not folder:
        return None
    base = Path(folder)
    if not base.is_dir():
        return None

    for key in ("audio_file", "audio", "audio_path", "file"):
        value = scene.get(key)
        if value:
            candidate = Path(str(value))
            if not candidate.is_absolute():
                candidate = base / candidate
            if candidate.is_file():
                return candidate

    numbers = []
    for key in ("number", "scene_number", "index"):
        if scene.get(key) is not None:
            try:
                numbers.append(int(scene[key]))
            except (TypeError, ValueError):
                pass
    match = re.search(r"(\d+)", str(scene.get("id", "")))
    if match:
        numbers.append(int(match.group(1)))

    for number in dict.fromkeys(numbers):
        for filename in (
            f"scene_{number:03d}.wav", f"scene_{number:02d}.wav", f"scene_{number}.wav",
            f"scene-{number:03d}.wav", f"scene-{number:02d}.wav", f"scene-{number}.wav",
        ):
            candidate = base / filename
            if candidate.is_file():
                return candidate
    return None

def read_config(name, fallback=None):
    path = ROOT / "config" / name
    if not path.exists():
        return fallback or {}
    return json.loads(path.read_text(encoding="utf-8"))


def replace_project(project):
    for key in list(st.session_state):
        if key.startswith("mvd_widget_") or key in ("mvd_pending_load", "mvd_remove"):
            del st.session_state[key]
    st.session_state.mvd_project = project
    st.session_state.mvd_saved = ""


def persist(project):
    try:
        content = export_project(project)
        if content != st.session_state.get("mvd_saved"):
            store.save(project)
            st.session_state.mvd_saved = content
        return True
    except (OSError, sqlite3.Error, ValueError) as exc:
        st.error(f"Could not save changes. Keep this page open and download the project JSON. {exc}")
        return False


try:
    presets = read_config("music_video_presets.json")
    app_config = read_config("app.json", read_config("app.example.json"))
    settings = read_config("settings.json")
    saved = store.list()
    if unload_comfy_clicked:
        try:
            unload_comfyui_models(st.session_state.mvd_comfy_url)
            st.success("ComfyUI model unload requested.")
        except RuntimeError as exc:
            st.error(str(exc))

    if unload_lm_clicked:
        try:
            count = unload_all_lmstudio_models(st.session_state.mvd_lm_url)
            st.info("No models are currently loaded in LM Studio." if count == 0
                    else f"{count} LM Studio model{'s' if count != 1 else ''} unloaded.")
        except RuntimeError as exc:
            st.error(str(exc))
except (OSError, ValueError, sqlite3.Error) as exc:
    st.error(f"Could not load Director configuration or projects: {exc}")
    st.stop()

with st.expander("Open or import a project", expanded="mvd_project" not in st.session_state):
    uploaded = st.file_uploader("Scene Builder scenes.json or a saved Director JSON", type=["json"], key="mvd_import")
    if st.button("Import scenes.json", disabled=uploaded is None):
        try:
            imported = import_project(uploaded.getvalue())
            store.save(imported)
            replace_project(imported)
            st.rerun()
        except (OSError, ValueError, sqlite3.Error) as exc:
            st.error(f"Import failed; the current project was kept. {exc}")
    selected_project = st.selectbox("Saved projects", [r["id"] for r in saved],
        format_func=lambda value: next(f"{r['title']} · {r['updated']}" for r in saved if r["id"] == value))
    if st.button("Open project", disabled=not selected_project):
        try:
            replace_project(store.load(selected_project))
            st.rerun()
        except (OSError, ValueError, sqlite3.Error) as exc:
            st.error(str(exc))

if "mvd_project" not in st.session_state:
    # A browser/page restart creates a fresh Streamlit session. Reopen the most
    # recently saved Director project automatically so scene progress is not lost.
    if saved:
        try:
            replace_project(store.load(saved[0]["id"]))
            st.info("Reopened the most recently used Director project automatically.")
        except (OSError, ValueError, sqlite3.Error) as exc:
            st.error(f"Could not reopen the most recent Director project: {exc}")
            st.stop()
    else:
        st.info("Import scenes.json from the music Scene Builder to start a Director project.")
        st.stop()
try:
    project = validate_project(st.session_state.mvd_project)
except ValueError as exc:
    st.error(str(exc))
    st.stop()
st.session_state.mvd_project = project
global_settings = project[KEY]["settings"]
project_key = "mvd_widget_" + project[KEY]["id"]

st.subheader(title(project))
stats = st.empty()
progress = st.empty()
with st.expander("Global music video settings", expanded=True):
    global_settings["video_style"] = preset("Video style / type", global_settings["video_style"], presets["video_style"], project_key + "_style")

    st.markdown("**H3 master song**")
    master_upload = st.file_uploader(
        "Full original song",
        type=["wav", "mp3", "flac", "ogg", "m4a", "aac", "opus"],
        key=project_key + "_master_song",
        help=(
            "Upload the complete original song when the chosen workflow has a master-audio input. It uses this "
            "master song; the scene start time selects the required section."
        ),
    )
    if master_upload is not None:
        try:
            new_master = store_project_audio(
                ROOT, master_upload.getvalue(), master_upload.name, master_upload.type
            )
            if new_master != global_settings.get("master_song_asset"):
                global_settings["master_song_asset"] = new_master
                for project_scene in project["scenes"]:
                    project_scene[KEY]["approved_signature"] = ""
                persist(project)
        except (OSError, ValueError) as exc:
            st.error(f"Could not store master song: {exc}")

    master_song_asset = global_settings.get("master_song_asset")
    if master_song_asset:
        try:
            master_info = read_project_audio(ROOT, master_song_asset)
            st.success(f"Master song ready: {master_info[1]}")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            st.warning(f"Saved master song is unavailable: {exc}")
            master_song_asset = None
    else:
        st.info("A master song is needed only for workflows with a mapped master-audio input.")

    with st.expander("How to use this page", expanded=False):
        st.markdown(
            """
            1. Import your `scenes.json`, choose the **full original master song**, and optionally select the folder containing the short scene audio files for preview/Whisper.
            2. Choose a **Project workflow** when most or all scenes use the same ComfyUI workflow.
            3. Select a scene from the scene list and listen to its audio.
            4. Review or create the lyric transcription for vocal scenes.
            5. Choose the **Artist action** and **Camera action**, and add scene direction notes when needed.
            6. Check the workflow inputs, duration and reference media for the selected scene.
            7. Choose **LM Studio** or **Local H3 builder**, generate a prompt, then review or edit it manually.
            8. Click **Approve scene prompt** when the prompt is ready.
            9. Click **Send to ComfyUI** to render the scene.
            10. Use **Scene workflow** only when one scene needs a different workflow from the project default.
            11. Download the video from the preview window to a directory of your choice.

            Vocal/instrumental type, original timing and audio references come from `scenes.json`.
            """
        )

    left, right = st.columns(2)
    global_settings["characters"] = left.text_area("Recurring characters / wardrobe", value=global_settings["characters"], key=project_key + "_characters")
    global_settings["concept"] = right.text_area("Concept / continuity", value=global_settings["concept"], key=project_key + "_concept")

    # Optional project-wide workflow. Scenes can inherit this or override it.
    workflow_options = [""] + mapped_workflows(ROOT)
    project_workflow = str(global_settings.get("workflow", "") or "")
    if project_workflow and project_workflow not in workflow_options:
        workflow_options.append(project_workflow)
        st.warning("The saved project workflow is unavailable. Choose another installed mapped workflow or None.")
    selected_project_workflow = st.selectbox(
        "Project workflow",
        workflow_options,
        index=workflow_options.index(project_workflow),
        format_func=lambda value: value or "None / Select workflow",
        key=project_key + "_project_workflow",
        help="Optional default workflow for all scenes. Individual scenes can override it.",
    )
    if selected_project_workflow != project_workflow:
        global_settings["workflow"] = selected_project_workflow
        # Inherited scenes must rebuild mapped inputs when the project workflow changes.
        for project_scene in project["scenes"]:
            project_state = project_scene[KEY]
            if not project_state.get("workflow"):
                project_state["inputs"] = {}
                project_state["assets"] = {}
                project_state["duration_ack"] = False
                project_state["approved_signature"] = ""
        for key in list(st.session_state):
            if key.startswith(project_key + "_") and "_mapped_" in key:
                del st.session_state[key]
        persist(project)

nav, editor = st.columns([1, 2])
with nav:
    st.subheader("Scenes")
    overview = st.empty()
    ids = [s[KEY]["id"] for s in project["scenes"]]
    icons = {"New": "⚪", "Prompt Ready": "📝", "Ready to Render": "🟡", "Rendered": "✅", "Failed": "❌"}
    scene_labels = {}
    for scene_index, value in enumerate(ids):
        index = scene_index
        info = scene_info(project, index)
        status = scene_status(project, project["scenes"][index])
        scene_labels[value] = f"{icons[status]} {info['number']} · {info['type'].title()} · {info['duration']:.2f}s · {status}"
    st.markdown("##### Scene source")
    source_dir = ROOT / "data" / "director_scene_sources" / hashlib.sha256(project[KEY]["id"].encode()).hexdigest()[:32]
    source_dir.mkdir(parents=True, exist_ok=True)

    uploaded_scene_folder = st.file_uploader(
        "Select scenes folder",
        type=["json", "wav", "mp3", "flac", "ogg", "m4a", "aac", "opus"],
        accept_multiple_files="directory",
        key=project_key + "_scene_folder_upload",
        help=(
            "Choose the folder exported by Audio Chunker. ComfyMax stores a local "
            "working copy, so you only need to select the folder once for this project."
        ),
    )

    if uploaded_scene_folder:
        copied = 0
        for uploaded_file in uploaded_scene_folder:
            filename = Path(uploaded_file.name).name
            if not filename:
                continue
            destination = source_dir / filename
            content = uploaded_file.getvalue()
            if not destination.exists() or destination.read_bytes() != content:
                destination.write_bytes(content)
            copied += 1
        project[KEY]["scenes_folder"] = str(source_dir)
        persist(project)
        st.success(f"Scene working folder ready · {copied} files available.")

    scenes_folder = str(project[KEY].get("scenes_folder", "") or "")
    if scenes_folder and Path(scenes_folder).is_dir():
        wav_count = len(list(Path(scenes_folder).glob("*.wav")))
        st.caption(f"Working folder: {scenes_folder} · {wav_count} WAV file(s)")
    else:
        st.caption("Select the Audio Chunker scene folder once; it will be remembered for this project.")

    saved_scene_id = project[KEY].get("selected_scene_id")
    if saved_scene_id not in ids:
        saved_scene_id = ids[0]
    scene_widget_key = project_key + "_scene"
    if scene_widget_key not in st.session_state:
        st.session_state[scene_widget_key] = saved_scene_id

    selected = st.selectbox(
        "Select scene",
        ids,
        index=ids.index(saved_scene_id),
        format_func=scene_labels.get,
        key=scene_widget_key,
    )
    if project[KEY].get("selected_scene_id") != selected:
        project[KEY]["selected_scene_id"] = selected
        persist(project)
index = ids.index(selected)
scene = project["scenes"][index]
state = scene[KEY]

with nav:
    current_render = state.get("render", {})
    if current_render.get("video_asset"):
        preview_path = ROOT / current_render["video_asset"]
        if preview_path.exists():
            st.markdown("##### Scene video")
            st.video(preview_path.read_bytes())
            st.caption(current_render.get("video_name", preview_path.name))
            last_frame_asset = current_render.get("last_frame_asset")
            if last_frame_asset:
                last_frame_path = ROOT / last_frame_asset
                if last_frame_path.exists():
                    st.markdown("##### Last frame")
                    st.image(str(last_frame_path), caption=current_render.get("last_frame_name", last_frame_path.name))
                    st.download_button(
                        "Download last frame",
                        data=last_frame_path.read_bytes(),
                        file_name=current_render.get("last_frame_name", last_frame_path.name),
                        mime="image/png",
                        use_container_width=True,
                        key=prefix + "download_last_frame" if "prefix" in locals() else project_key + "_download_last_frame_" + state["id"],
                    )
            if current_render.get("last_frame_error"):
                st.warning("Video rendered, but automatic last-frame extraction failed: " + current_render["last_frame_error"])
        else:
            st.warning("The saved scene video could not be found on disk.")

info = scene_info(project, index)
prefix = project_key + "_" + state["id"] + "_"
source_scene_audio = scene_audio_from_folder(project[KEY].get("scenes_folder", ""), scene)

with editor:
    st.subheader(f"Scene {info['number']} · {info['type'].title()}")
    st.caption(f"Start {info['start']:.6f}s · End {info['end']:.6f}s · Duration {info['duration']:.6f}s")
    lyrics_transcription_ui(
        scene,
        str(source_scene_audio) if source_scene_audio else None,
        prefix,
    )
    # Refresh scene_info so prompt generation immediately sees edited/transcribed lyrics.
    info = scene_info(project, index)
    if source_scene_audio:
        st.audio(str(source_scene_audio))
    elif scene.get("audio_file"):
        st.caption(f"Source audio: {scene['audio_file']} · {scene.get('audio_source', 'unspecified')}")
    left, right = st.columns(2)
    with left:
        state["artist_action"] = preset("Artist action", state["artist_action"], presets["artist_action"], prefix + "action")
    with right:
        state["camera_action"] = preset("Camera action", state["camera_action"], presets["camera_action"], prefix + "camera")
    state["notes"] = st.text_area("Scene direction / continuity notes", value=state["notes"], key=prefix + "notes")

    with st.expander("H3 prompt details", expanded=False):
        state["location"] = st.text_input(
            "Scene / location",
            value=state.get("location", ""),
            key=prefix + "location",
            help="Example: music studio, luxury nightclub, city street at night.",
        )
        ref_left, ref_right = st.columns(2)
        state["picture_1_role"] = ref_left.text_input(
            "Picture 1 defines",
            value=state.get("picture_1_role", "facial identity of the performer"),
            key=prefix + "picture_1_role",
            help="Usually the performer's facial identity.",
        )
        state["picture_2_role"] = ref_right.text_input(
            "Picture 2 defines",
            value=state.get("picture_2_role", ""),
            key=prefix + "picture_2_role",
            help="Example: the music studio environment, wardrobe, or full-body appearance.",
        )
        state["lyric_language"] = st.text_input(
            "Lyric language",
            value=state.get("lyric_language", "English"),
            key=prefix + "lyric_language",
        )
        state["clip_start_seconds"] = st.number_input(
            "Master song start / clip_start_seconds",
            min_value=0.0,
            value=float(state.get("clip_start_seconds", info["start"])),
            step=0.001,
            format="%.6f",
            key=prefix + "clip_start_seconds",
            help=(
                "Absolute start position in the full master song for this H3 clip. "
                "This is separate from the short scene-audio file used for preview/Whisper."
            ),
        )
        state["continuation_action"] = st.text_area(
            "End / continuation instruction",
            value=state.get("continuation_action", ""),
            key=prefix + "continuation_action",
            help="Optional. Leave empty to use the safe default that keeps motion and camera trajectory in progress.",
        )

    installed_workflows = mapped_workflows(ROOT)
    project_workflow = str(global_settings.get("workflow", "") or "")
    scene_override = str(state.get("workflow", "") or "")

    scene_workflow_options = ["__project__"] + installed_workflows
    if scene_override and scene_override not in scene_workflow_options:
        scene_workflow_options.append(scene_override)
        st.warning("This scene's saved workflow is unavailable. Choose the project workflow or another installed mapped workflow.")

    previous_selection = scene_override or "__project__"
    workflow_selection = st.selectbox(
        "Scene workflow",
        scene_workflow_options,
        index=scene_workflow_options.index(previous_selection),
        format_func=lambda value: (
            f"Use project workflow ({project_workflow})" if value == "__project__" and project_workflow
            else "Use project workflow (None)" if value == "__project__"
            else value
        ),
        key=prefix + "workflow",
        help="By default this scene inherits the optional Project workflow. Select a workflow here only to override it for this scene.",
    )
    new_override = "" if workflow_selection == "__project__" else workflow_selection
    if new_override != scene_override:
        state["workflow"] = new_override
        state["inputs"] = {}
        state["assets"] = {}
        state["duration_ack"] = False
        state["approved_signature"] = ""
        for key in list(st.session_state):
            if key.startswith(prefix + "mapped_"):
                del st.session_state[key]
        st.session_state.pop("mvd_pending_load", None)

    effective_workflow = str(state.get("workflow", "") or project_workflow or "")
    mapping = workflow = None
    values, media, problems = {}, {}, []
    if effective_workflow:
        try:
            workflow, mapping, digest = load_mapped_workflow(ROOT, effective_workflow)
            state["workflow_digest"] = digest
            with st.expander("Workflow inputs and render settings", expanded=True):
                values, media, problems = mapped_inputs(
                    ROOT, mapping, state, settings, prefix + "mapped_",
                    scene_duration=info["duration"],
                    source_audio=str(source_scene_audio) if source_scene_audio else None,
                    master_audio_asset=master_song_asset,
                )
                # H3 master-song workflows may expose clip_start_seconds as a mapped input.
                # Keep the Director's persistent master-song position authoritative.
                for field_name, field_rule in mapping.get("fields", {}).items():
                    if field_name == "clip_start_seconds" or field_rule.get("setting") == "clip_start_seconds":
                        start_value = float(state.get("clip_start_seconds", info["start"]))
                        values[field_name] = str(start_value) if field_rule.get("type") == "text" else start_value
                        state["inputs"][field_name] = values[field_name]

                # Allow the MiniMax H3 diffusion/UNET model to be selected per scene.
                # The selected filename is written to the mapped field immediately before submission.
                unet_fields = [
                    (name, rule) for name, rule in mapping.get("fields", {}).items()
                    if rule.get("type") == "model_setting" and rule.get("setting") == "minimax_h3.unet"
                ]
                for unet_field, unet_rule in unet_fields:
                    current_unet = str(
                        state.get("video_model_override")
                        or values.get(unet_field)
                        or ""
                    )
                    try:
                        available_unets = comfyui_unet_models(st.session_state.get("mvd_comfy_url") or app_config["comfyui_url"])
                    except RuntimeError as exc:
                        available_unets = []
                        st.warning(str(exc))

                    # Keep the currently configured model selectable even if ComfyUI cannot list it.
                    model_options = list(available_unets)
                    if current_unet and current_unet not in model_options:
                        model_options.insert(0, current_unet)

                    if model_options:
                        selected_unet = st.selectbox(
                            unet_rule.get("label", "MiniMax H3 video model"),
                            model_options,
                            index=model_options.index(current_unet) if current_unet in model_options else 0,
                            key=prefix + "video_model_override",
                            help="Select the ComfyUI diffusion model for this scene. The choice is saved per scene.",
                        )
                        if selected_unet != state.get("video_model_override"):
                            state["video_model_override"] = selected_unet
                            state["approved_signature"] = ""
                        values[unet_field] = selected_unet
                        state["inputs"][unet_field] = selected_unet
                    elif current_unet:
                        values[unet_field] = current_unet
                if not any(r.get("type") in ("audio", "master_audio") for r in mapping["fields"].values()) and scene.get("audio_file"):
                    st.caption("This mapping has no audio input. The source WAV is preserved as a reference but will not be sent to this workflow.")
                match = duration_matches(values.get("duration"), info["duration"])
                if not match:
                    if state.get("duration_ack_value") != values.get("duration"):
                        state["duration_ack"] = False
                    state["duration_ack_value"] = values.get("duration")
                    st.warning(f"Original scene: {info['duration']:.6f}s. Workflow duration: {values.get('duration', 'not mapped')}. Source timing will remain unchanged.")
                    ack_key = prefix + "mapped_duration_ack_" + str(values.get("duration"))
                    state["duration_ack"] = st.checkbox("Use this render length; I will handle any timing difference during editing", value=state["duration_ack"], key=ack_key)
                    if not state["duration_ack"]:
                        problems.append("Acknowledge the render length difference or select a matching duration.")
                else:
                    state["duration_ack"] = False
        except (OSError, ValueError, KeyError, TypeError, ComfyUIError) as exc:
            problems.append(str(exc))
    else:
        st.caption("No workflow selected. You can still review audio, direct the scene and edit prompts. Select a project or scene workflow before rendering.")

    comfy_url = st.session_state.get("mvd_comfy_url") or app_config["comfyui_url"]
    comfy = ComfyUIClient(comfy_url)
    for problem in problems:
        st.info(problem)
    busy = state["render"].get("state") in ("queued", "submitting")

    prompt_key = prefix + "prompt"
    state["prompt"] = st.session_state.get(prompt_key, state["prompt"])
    mode = st.radio("Prompt generator", ["LM Studio", "Local H3 builder"], index=1, horizontal=True, key=prefix + "generator")
    replace_prompt = st.checkbox("Replace my current prompt when regenerating", key=prefix + "replace_prompt") if state["prompt"].strip() else True
    if mode == "Local H3 builder":
        image_count = sum(1 for item in media.values() if item and item[0] == "image")
        generate_label = "Regenerate H3 Prompt" if state["prompt"].strip() else "Generate H3 Prompt"
        if st.button(generate_label, disabled=busy or not replace_prompt, key="mvd_generate_prompt"):
            state["prompt"] = build_h3_music_prompt(project, scene, image_count=image_count,
                render_duration=values.get("duration", info["duration"]),
                audio_source=("master" if any((mapping or {}).get("fields", {}).get(k, {}).get("type") == "master_audio" for k in media)
                              else "scene" if any(v[0] == "audio" for v in media.values()) else None),
                has_video_context=any(v[0] == "video" for v in media.values()))
            state["prompt_source"] = "deterministic_h3_builder"
            state["approved_signature"] = ""
            st.session_state[prompt_key] = state["prompt"]
            persist(project)
            st.rerun()
    else:
        lm_url = st.session_state.get("mvd_lm_url") or app_config["lmstudio_url"]
        lm = LMStudioClient(lm_url, timeout=120)
        if st.session_state.get("mvd_models_url") != lm_url or st.button("Refresh LM Studio models"):
            try:
                st.session_state.mvd_models = LMStudioClient(lm_url, timeout=5).list_models()
                st.session_state.mvd_models_url = lm_url
            except (LMStudioError, ValueError) as exc:
                st.session_state.mvd_models = []
                st.warning(str(exc))
        model = st.selectbox("LM Studio model", st.session_state.get("mvd_models", []), key="mvd_model")
        allowed = bool(model and replace_prompt and not busy)
        pending = st.session_state.get("mvd_pending_load")
        request_key = (project[KEY]["id"], state["id"], model, lm_url)
        if pending and pending["key"] != request_key:
            st.session_state.pop("mvd_pending_load", None)
            pending = None
        approved_instances = None
        confirmed = False
        if pending:
            st.warning("LM Studio already has loaded models: " + ", ".join(f"{i.model} ({i.instance_id})" for i in pending["instances"]))
            if st.button("Unload listed models and generate", disabled=not allowed):
                approved_instances = pending["instances"]
                confirmed = True
                st.session_state.pop("mvd_pending_load", None)
            if st.button("Cancel model load"):
                st.session_state.pop("mvd_pending_load", None)
                st.rerun()
        clicked = st.button("Regenerate with LM Studio" if state["prompt"] else "Generate Prompt with LM Studio",
                            disabled=not allowed or bool(pending))
        if clicked or confirmed:
            try:
                with st.spinner("Generating scene prompt with LM Studio…"):
                    instance = lm.load_model(model, approved_instances=approved_instances)
                    st.session_state.mvd_model_instance = instance
                    st.session_state.mvd_model_server = lm_url
                    try:
                        generated = lm.generate_prompt(compose_prompt(project, scene, mapping), model,
                            prompt_system(mapping or {}, values.get("duration", info["duration"]), any(v[0] == "image" for v in media.values())),
                            app_config.get("temperature", 0.7),
                            images=[(v[2], v[3]) for v in media.values() if v[0] == "image"] or None)
                        state["prompt"] = generated.text
                        state["prompt_source"] = "lm_studio"
                        state["model"] = generated.model
                        state["approved_signature"] = ""
                        st.session_state[prompt_key] = generated.text
                    finally:
                        lm.unload_model(instance)
                        st.session_state.pop("mvd_model_instance", None)
                persist(project)
                st.rerun()
            except ModelLoadConfirmationRequired as exc:
                st.session_state.mvd_pending_load = {"key": request_key, "instances": exc.instances}
                persist(project)
                st.rerun()
            except (LMStudioError, ValueError) as exc:
                st.error(str(exc))
    if st.session_state.get("mvd_model_instance"):
        st.warning("Unload the Director's LM Studio model before rendering.")
        if st.button("Retry unloading Director model"):
            try:
                LMStudioClient(st.session_state.mvd_model_server).unload_model(st.session_state.mvd_model_instance)
                st.session_state.pop("mvd_model_instance", None)
                st.rerun()
            except LMStudioError as exc:
                st.error(str(exc))

    if prefix + "prompt" not in st.session_state:
        st.session_state[prefix + "prompt"] = state["prompt"]
    state["prompt"] = st.text_area("Editable scene prompt", height=240, key=prefix + "prompt")
    for name, rule in (mapping or {}).get("fields", {}).items():
        if rule.get("type") == "prompt":
            values[name] = state["prompt"]
    if mapping and not any(r.get("type") == "prompt" for r in mapping["fields"].values()):
        problems.append("The workflow mapping has no prompt input.")
    save, approve = st.columns(2)
    if save.button("Save Scene"):
        project[KEY]["selected_scene_id"] = selected
        if persist(project):
            st.success("Scene saved.")
    if approve.button("Approve scene prompt", disabled=not state["prompt"].strip() or not effective_workflow or bool(problems) or busy):
        project[KEY]["selected_scene_id"] = selected
        approve_scene(project, scene)
        persist(project)
        st.success(f"Scene {info['number']} prompt approved.")
    approved = state["approved_signature"] == signature(project, scene)
    st.caption(f"Status: {scene_status(project, scene)}. Editing the prompt, direction, global style or workflow inputs revokes approval.")
    render = state["render"]
    render_label = "Render Again" if render.get("output") or render.get("video_asset") else "Send to ComfyUI"

    if st.button(render_label, type="primary",
                 disabled=not approved or not effective_workflow or bool(problems) or busy or bool(st.session_state.get("mvd_model_instance"))):
        try:
            output_node = video_output_node_id(workflow, mapping)
            # Record intent before contacting ComfyUI. A failed local save blocks submission.
            previous_render = state["render"]
            state["render"] = {"state": "submitting", "signature": signature(project, scene),
                "server": comfy_url, "output_node_id": output_node, "workflow": effective_workflow}
            if not persist(project):
                state["render"] = previous_render
            else:
                try:
                    prompt_id, final_values = submit_mapped_workflow(comfy, workflow, mapping, values, media)
                except (ComfyUIError, ValueError, OSError) as exc:
                    # A timeout may occur after the server accepted the job. Require a queue check.
                    state["render"]["error"] = str(exc)
                    persist(project)
                    st.error(f"Could not confirm submission. Check the ComfyUI queue before retrying. {exc}")
                else:
                    state["render"].update(state="queued", prompt_id=prompt_id, values=final_values)
                    if persist(project):
                        st.rerun()
                    else:
                        st.warning(f"Keep this queue ID: {prompt_id}. Do not submit the scene again.")
        except ValueError as exc:
            st.error(str(exc))

    render = state["render"]
    if render.get("prompt_id") and st.button("Check render status"):
        render_client = ComfyUIClient(render.get("server") or comfy_url)
        try:
            output_info = check_render(render_client, render)
            if output_info:
                # Persist confirmed success before downloading or extracting an optional preview.
                persist(project)
                try:
                    video_bytes = render_client.download_output(output_info["filename"], output_info.get("subfolder", ""), output_info.get("type", "output"))
                    local_path = render_asset_path(ROOT, project[KEY]["id"], state["id"], render["prompt_id"], output_info["filename"])
                    local_path.parent.mkdir(parents=True, exist_ok=True)
                    local_path.write_bytes(video_bytes)
                    render.update(video_asset=local_path.relative_to(ROOT).as_posix(), video_name=output_info["filename"])
                    render.pop("download_error", None)
                    last_frame_path = local_path.with_name("last_frame.png")
                    try:
                        extract_last_frame(local_path, last_frame_path)
                    except RuntimeError as exc:
                        render["last_frame_error"] = str(exc)
                    else:
                        render.update(last_frame_asset=last_frame_path.relative_to(ROOT).as_posix(), last_frame_name="last_frame.png")
                        render.pop("last_frame_error", None)
                except (OSError, ValueError, ComfyUIError) as exc:
                    render["download_error"] = str(exc)
                if not render.get("unload_requested"):
                    try:
                        unload_comfyui_models(render.get("server") or comfy_url)
                    except RuntimeError as exc:
                        render["unload_error"] = str(exc)
                    else:
                        render["unload_requested"] = True
                        render.pop("unload_error", None)
            persist(project)
            if output_info or render.get("state") == "failed":
                st.rerun()
            st.info("The job has no completed video yet. Its queue ID is retained; no new render was submitted.")
        except ComfyUIError as exc:
            persist(project)
            st.warning(f"Status connection failed. The queue ID was kept; retry the status check, not submission. {exc}")
    if render.get("download_error"):
        st.warning("Video output confirmed, but the local preview could not be downloaded. Check render status to retry: " + render["download_error"])

    render = state["render"]
    if render.get("unload_error"):
        st.warning("Render completed, but the ComfyUI model could not be unloaded automatically: " + render["unload_error"])
    if render.get("prompt_id"):
        st.caption(f"ComfyUI job: {render['prompt_id']} · {render.get('state', '')}")

    if render.get("state") == "submitting":
        st.warning("Submission was interrupted before its queue ID was saved. Check the ComfyUI queue before retrying.")
        if st.button("I checked the queue — allow another submission"):
            render.update(state="failed", error="Interrupted submission; user checked queue.")
            persist(project)
            st.rerun()
    if render.get("state") == "failed":
        st.error(render.get("error", "Render failed."))
    if render.get("output") and render.get("signature") != signature(project, scene):
        st.info("This output belongs to an earlier scene revision. Review, approve and render the current revision separately.")

rows = timeline(project)
rendered = sum(row["Status"] == "Rendered" for row in rows)
vocal = sum(row["Type"] == "Vocal" for row in rows)
stats.markdown(f"**{len(rows)} scenes** · {vocal} Vocal · {len(rows) - vocal} Instrumental · **{rendered} Rendered** · {len(rows) - rendered} remaining")
progress.progress(rendered / len(rows))
overview.dataframe(rows, hide_index=True, height=360, use_container_width=True)
persist(project)
st.download_button("Download scenes.json with Director state", export_project(project), "scenes.json", "application/json")
st.caption(
    "Changes save locally after each interaction and the most recent Director project reopens automatically "
    "after a page/browser restart. Original scene timings, audio references and unknown JSON fields are retained."
)
