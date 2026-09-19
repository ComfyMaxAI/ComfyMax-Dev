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
    master_audio_asset=None,
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

        elif kind == "master_audio":
            # Project-wide full song. Unlike normal scene audio, this is never
            # populated from the short scene WAV used by Whisper/preview.
            asset = master_audio_asset
            if asset:
                try:
                    media[name] = _read_media(root, asset, "audio")
                    values[name] = media[name][1]
                    st.success(f"Master song: {media[name][1]}")
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    problems.append(f"{label}: select the master song again ({exc}).")
            else:
                problems.append(f"Choose the full master song in Global music video settings for {label}.")

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

            if kind == "select_number" and is_duration and rule.get("allow_custom_duration", False):
                options = _duration_options(options, scene_duration)

            if not options:
                problems.append(f"{label}: mapping has no options.")
                continue

            # For duration, prefer the actual scene/audio duration when no
            # explicit user choice has yet been stored.
            preferred = saved
            if is_duration and name not in state["inputs"] and scene_duration in options:
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
            not in ("image", "audio", "master_audio", "video", "prompt")
        }
    )
    return values, media, problems


def duration_matches(actual, expected):
    try:
        return math.isclose(float(actual), expected, rel_tol=0, abs_tol=1e-6)
    except (ValueError, TypeError):
        return False


def store_project_audio(root, content, filename, mime):
    """Store a project-wide master-song asset in the Director asset store."""
    return _store_media(root, content, filename, mime, "audio")


def read_project_audio(root, asset):
    """Read a stored project-wide master-song asset."""
    return _read_media(root, asset, "audio")


def lyrics_transcription_ui(scene, source_audio, prefix):
    """Edit a Director transcript while preserving the imported scene verbatim."""
    state = scene["comfymax_director"]
    key = prefix + "lyrics"
    pending = st.session_state.pop(prefix + "pending_transcript", None)
    if pending is not None:
        state["lyrics_override"] = pending["text"]
        state["transcription"] = pending
        st.session_state[key] = pending["text"]
    original = str(scene.get("lyrics", scene.get("text", scene.get("context", ""))) or "")
    if key not in st.session_state:
        st.session_state[key] = state.get("lyrics_override", original)
    edited = st.text_area("Lyrics / transcript", key=key, height=120,
        help="Director edits are stored separately; the original scene text remains unchanged.")
    if edited != original or "lyrics_override" in state:
        state["lyrics_override"] = edited
    model_size = st.selectbox("Whisper model", ["tiny", "base", "small", "medium", "large-v3"], index=2, key=prefix + "whisper_model")
    language = st.text_input("Language", value=str(state.get("whisper_language", scene.get("whisper_language", ""))),
                            key=prefix + "whisper_language", help="Optional language code: en, nl, fr.").strip()
    state["whisper_language"] = language
    can_transcribe = bool(source_audio and Path(source_audio).is_file())
    if st.button("Transcribe with Whisper", key=prefix + "whisper_transcribe", disabled=not can_transcribe):
        try:
            from modules.whisper_transcriber import transcribe_audio
            with st.spinner("Transcribing scene audio with Whisper..."):
                result = transcribe_audio(source_audio, model_size=model_size, language=language or None, prefer_gpu=True)
            result["text"] = str(result.get("text") or "").strip()
            st.session_state[prefix + "pending_transcript"] = result
        except Exception as exc:
            st.error(f"Whisper transcription failed: {exc}")
        else:
            st.rerun()
    if not can_transcribe:
        st.caption("No local scene audio was found for Whisper transcription. Lyrics can still be entered manually.")
    return edited
