"""Small UI helpers for the selected scene; uses existing mapping field types."""
import hashlib
import math
from pathlib import Path

import streamlit as st

from modules.scene_workflow import read_image, store_image


MEDIA_EXTENSIONS = {
    "audio": (".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac", ".opus", ".mp4"),
    "video": (".mp4", ".webm", ".mov", ".mkv", ".avi", ".m4v"),
}


def preset(label, value, options, key):
    choices = options + ["Custom"]
    selected = st.selectbox(
        label,
        choices,
        index=choices.index(value) if value in options else len(options),
        key=key,
    )
    if selected == "Custom":
        return st.text_input(
            f"Custom {label.lower()}",
            value=value if value not in options else "",
            key=key + "_custom",
        )
    return selected


def _store_media(root, content, filename, mime, kind):
    suffix = Path(filename).suffix.lower()
    allowed = MEDIA_EXTENSIONS[kind]
    if suffix not in allowed or not content:
        raise ValueError(
            f"Choose a supported nonempty {kind} file "
            f"({', '.join(allowed)})."
        )

    digest = hashlib.sha256(content).hexdigest()
    relative = Path("data") / "director_assets" / f"{digest}{suffix}"
    destination = Path(root) / relative
    destination.parent.mkdir(parents=True, exist_ok=True)

    if not destination.exists():
        destination.write_bytes(content)

    return {
        "path": relative.as_posix(),
        "name": Path(filename).name,
        "mime": mime or "application/octet-stream",
        "sha256": digest,
        "kind": kind,
    }


def _read_media(root, asset, expected_kind):
    if asset.get("kind") != expected_kind:
        raise ValueError(f"Saved asset is not {expected_kind}.")

    base = (Path(root) / "data" / "director_assets").resolve()
    path = (Path(root) / asset["path"]).resolve()

    if not path.is_relative_to(base):
        raise ValueError("Media must be in the local Director asset folder.")

    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != asset["sha256"]:
        raise ValueError("Saved media has changed. Upload it again.")

    return (
        expected_kind,
        asset["name"],
        content,
        asset.get("mime") or "application/octet-stream",
    )



def _store_media_file(root, path, kind):
    path = Path(path)
    if not path.is_file():
        raise ValueError(f"{kind.title()} file does not exist: {path}")
    mime_by_suffix = {
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg",
        ".flac": "audio/flac",
        ".ogg": "audio/ogg",
        ".m4a": "audio/mp4",
        ".aac": "audio/aac",
        ".opus": "audio/ogg",
        ".mp4": "video/mp4" if kind == "video" else "audio/mp4",
    }
    return _store_media(
        root,
        path.read_bytes(),
        path.name,
        mime_by_suffix.get(path.suffix.lower(), "application/octet-stream"),
        kind,
    )

def _duration_options(options, scene_duration):
    result = list(options or [])
    if scene_duration is not None:
        try:
            duration = float(scene_duration)
            if duration > 0 and not any(
                math.isclose(float(item), duration, rel_tol=0, abs_tol=1e-6)
                for item in result
            ):
                result.append(duration)
        except (ValueError, TypeError):
            pass

    try:
        return sorted(set(result), key=float)
    except (ValueError, TypeError):
        return result


def mapped_inputs(
    root,
    mapping,
    state,
    settings,
    prefix,
    *,
    scene_duration=None,
    source_audio=None,
):
    values, media, problems = {}, {}, []

    for name, rule in mapping["fields"].items():
        kind = str(rule.get("type", "text")).lower()
        label = rule.get("label", name.replace("_", " ").title())
        key = prefix + name
        saved = state["inputs"].get(name, rule.get("default"))

        if kind == "prompt":
            values[name] = state["prompt"]

        elif kind == "model_setting":
            value = settings
            for part in str(rule.get("setting", "")).split("."):
                value = value.get(part, "") if isinstance(value, dict) else ""
            if value:
                values[name] = value

        elif kind == "image":
            uploaded = st.file_uploader(
                label,
                type=["png", "jpg", "jpeg", "webp"],
                key=key,
            )
            if uploaded:
                try:
                    state["assets"][name] = store_image(
                        root,
                        uploaded.getvalue(),
                        uploaded.name,
                        uploaded.type,
                    )
                    state["assets"][name]["kind"] = "image"
                except (OSError, ValueError) as exc:
                    problems.append(f"{label}: {exc}")

            asset = state["assets"].get(name)
            if asset:
                try:
                    filename, content, mime = read_image(root, asset)
                    media[name] = ("image", filename, content, mime)
                    values[name] = filename
                    st.success(f"Selected image: {filename}")
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    problems.append(f"{label}: upload the image again ({exc}).")
            else:
                problems.append(f"Upload {label}.")

        elif kind in ("audio", "video"):
            # If Audio Chunker supplied a scene WAV and the user has not chosen
            # an override, import it automatically into the persistent asset store.
            if kind == "audio" and source_audio and not state["assets"].get(name):
                try:
                    state["assets"][name] = _store_media_file(root, source_audio, "audio")
                except (OSError, ValueError) as exc:
                    problems.append(f"{label}: {exc}")

            allowed = [ext.lstrip(".") for ext in MEDIA_EXTENSIONS[kind]]
            uploaded = st.file_uploader(
                f"{label} (optional override)" if kind == "audio" and source_audio else label,
                type=allowed,
                key=key,
                help=(
                    f"Upload a different {kind} file to override the saved file. "
                    "The selected asset is stored per scene and remains available "
                    "when you switch between scenes."
                ),
            )

            if uploaded:
                try:
                    state["assets"][name] = _store_media(
                        root,
                        uploaded.getvalue(),
                        uploaded.name,
                        uploaded.type,
                        kind,
                    )
                except (OSError, ValueError) as exc:
                    problems.append(f"{label}: {exc}")

            asset = state["assets"].get(name)
            if asset:
                try:
                    media[name] = _read_media(root, asset, kind)
                    values[name] = media[name][1]
                    st.success(f"Selected {kind}: {media[name][1]}")
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    problems.append(f"{label}: select the {kind} again ({exc}).")
            else:
                problems.append(f"Upload {label}.")

        elif kind in ("select", "select_number"):
            options = rule.get("options", [])
            is_duration = name.lower() == "duration" or label.lower() == "duration"

            if kind == "select_number" and is_duration:
                options = _duration_options(options, scene_duration)

            if not options:
                problems.append(f"{label}: mapping has no options.")
                continue

            # For duration, prefer the actual scene/audio duration when no
            # explicit user choice has yet been stored.
            preferred = saved
            if is_duration and name not in state["inputs"] and scene_duration is not None:
                preferred = float(scene_duration)

            index = options.index(preferred) if preferred in options else 0
            values[name] = st.selectbox(label, options, index=index, key=key)

        elif kind in ("number", "integer"):
            cast = int if kind == "integer" else float
            minimum = cast(rule.get("min", 0))
            maximum = cast(
                rule.get(
                    "max",
                    (1 << 53) - 1 if kind == "integer" else 1000000,
                )
            )
            if minimum > maximum:
                problems.append(f"{label}: invalid mapped bounds.")
                continue

            is_duration = name.lower() == "duration" or label.lower() == "duration"
            initial = saved
            if is_duration and name not in state["inputs"] and scene_duration is not None:
                initial = scene_duration

            try:
                default = min(max(cast(initial or 0), minimum), maximum)
            except (ValueError, TypeError, OverflowError):
                default = minimum

            values[name] = st.number_input(
                label,
                min_value=minimum,
                max_value=maximum,
                value=default,
                key=key,
            )

        elif kind == "text":
            values[name] = st.text_input(
                label,
                value=str(saved or ""),
                key=key,
            )
            if rule.get("required") and not values[name].strip():
                problems.append(f"Provide {label}.")

        else:
            problems.append(f"Unsupported mapping field type: {kind} ({label}).")

    state["inputs"].update(
        {
            name: value
            for name, value in values.items()
            if mapping["fields"][name].get("type")
            not in ("image", "audio", "video", "prompt")
        }
    )
    return values, media, problems


def duration_matches(actual, expected):
    try:
        return math.isclose(float(actual), expected, rel_tol=0, abs_tol=1e-6)
    except (ValueError, TypeError):
        return False


def lyrics_transcription_ui(scene, source_audio, prefix, *, default_model="small"):
    """Render the per-scene local Whisper controls and keep lyrics editable."""
    from modules.whisper_transcriber import WhisperTranscriptionError, transcribe_audio

    scene_type = str(scene.get("type", "vocal" if scene.get("lyrics") else "instrumental")).lower()
    st.markdown("##### Lyrics / vocals")

    if scene_type != "vocal":
        st.info("Instrumental scene — transcription not required.")
        return scene.get("lyrics", "")

    if source_audio:
        st.caption(f"Scene audio: {Path(source_audio).name}")
    else:
        st.warning("No scene audio is available for transcription.")

    model_options = ["small", "medium", "large-v3", "base"]
    model_index = model_options.index(default_model) if default_model in model_options else 0
    model_size = st.selectbox(
        "Whisper model",
        model_options,
        index=model_index,
        key=prefix + "whisper_model",
        help="small is the ComfyMax default for fast scene transcription. Larger models can improve recognition but require more resources.",
    )
    language = st.text_input(
        "Language (optional)",
        value="",
        key=prefix + "whisper_language",
        placeholder="e.g. en, nl, fr — leave empty for automatic detection",
    ).strip()

    if st.button(
        "Transcribe with Whisper",
        key=prefix + "whisper_transcribe",
        disabled=not bool(source_audio),
        use_container_width=True,
    ):
        try:
            with st.spinner("Transcribing scene vocals locally…"):
                result = transcribe_audio(
                    source_audio,
                    model_size=model_size,
                    language=language or None,
                )
            scene["lyrics"] = result["text"]
            st.session_state[prefix + "lyrics_editor"] = result["text"]
            scene.setdefault("comfymax_director", {})
            state = scene["comfymax_director"]
            state["transcription"] = {
                "model": result["model"],
                "language": result["language"],
                "language_probability": result["language_probability"],
                "segments": result["segments"],
                "device": result.get("device", "cpu"),
                "compute_type": result.get("compute_type", ""),
                "gpu_fallback": result.get("gpu_fallback", False),
            }
            if result.get("gpu_fallback"):
                st.info("GPU acceleration is not available. ComfyMax automatically used CPU transcription.")
            else:
                st.caption("Whisper device: NVIDIA CUDA")
            st.success("Transcription completed. Review the lyrics below before generating the H3 prompt.")
        except WhisperTranscriptionError as exc:
            st.error(str(exc))

    lyrics = st.text_area(
        "Lyrics / transcript",
        value=str(scene.get("lyrics", "")),
        height=160,
        key=prefix + "lyrics_editor",
        help="Correct any recognition errors here. This exact text is supplied to LM Studio as scene context.",
    )
    scene["lyrics"] = lyrics
    return lyrics
