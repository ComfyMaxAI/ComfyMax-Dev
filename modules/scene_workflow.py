"""Shared mapped submission and prompt construction; uses existing clients."""
from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

from modules.comfyui import ComfyUIError, ComfyRenderError, apply_mapping, load_api_workflow
from modules.prompt_enhancer import get_h3_system_prompt


def mapped_workflows(root):
    return sorted(p.name for p in (Path(root) / "workflows").glob("*.json")
                  if (Path(root) / "config" / "workflow_mappings" / p.name).is_file())


def load_mapped_workflow(root, name):
    if name not in mapped_workflows(root):
        raise ValueError("Choose an available mapped workflow.")
    root = Path(root)
    raw = (root / "workflows" / name).read_bytes()
    mapping_raw = (root / "config" / "workflow_mappings" / name).read_bytes()
    mapping = json.loads(mapping_raw)
    if not isinstance(mapping, dict) or not isinstance(mapping.get("fields"), dict):
        raise ValueError("The workflow mapping has no valid fields.")
    workflow = load_api_workflow(raw)
    digest = hashlib.sha256(raw + mapping_raw).hexdigest()
    return workflow, mapping, digest


def prompt_system(mapping, duration, has_image=False):
    if mapping.get("h3_mode"):
        return get_h3_system_prompt(mapping["h3_mode"], has_image=has_image, duration_seconds=duration)
    return ("Write only a high-quality video-generation prompt for the supplied mapped workflow and scene. "
            "Preserve exact lyrics and source context. Respect Vocal/Instrumental type, clip duration, "
            "artist action, camera and global style. Do not invent supplied reference assets.")


def submit_mapped_workflow(client, workflow, mapping, values, media=None):
    """The common submission path for the main page and the Scene Director."""
    final_values = dict(values)

    if "seed" in final_values and int(final_values["seed"]) == 0:
        final_values["seed"] = random.randint(1, (1 << 53) - 1)

    for name, item in (media or {}).items():
        # New Director format: (kind, filename, content, mime).
        if len(item) == 4:
            kind, filename, content, mime = item
        else:
            # Backward compatibility with the previous image-only format.
            kind = "image"
            filename, content, mime = item

        if kind == "image":
            uploaded_name = client.upload_image(filename, content, mime)
        elif kind == "audio":
            uploaded_name = client.upload_audio(filename, content, mime)
        elif kind == "video":
            uploaded_name = client.upload_video(filename, content, mime)
        else:
            raise ValueError(f"Unsupported mapped media type: {kind}")

        final_values[name] = uploaded_name

    configured = apply_mapping(workflow, mapping, final_values)
    return client.queue_prompt(configured), final_values


def store_image(root, content, filename, mime):
    suffix = Path(filename).suffix.lower()
    if suffix not in (".png", ".jpg", ".jpeg", ".webp") or not content:
        raise ValueError("Choose a supported nonempty reference image.")
    digest = hashlib.sha256(content).hexdigest()
    relative = Path("data") / "director_assets" / (digest + suffix)
    destination = Path(root) / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        destination.write_bytes(content)
    return {"path": relative.as_posix(), "name": Path(filename).name, "mime": mime, "sha256": digest}


def read_image(root, asset):
    base = (Path(root) / "data" / "director_assets").resolve()
    path = (Path(root) / asset["path"]).resolve()
    if not path.is_relative_to(base):
        raise ValueError("Reference image must be in the local Director asset folder.")
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != asset["sha256"]:
        raise ValueError("Reference image has changed. Upload it again.")
    return asset["name"], content, asset.get("mime")



def video_output_node_id(workflow, mapping=None):
    """
    Resolve the intended video output node.

    Preferred: mapping["output_node_id"] / mapping["video_output_node_id"].
    Fallback: a unique SaveVideo node in the API workflow.
    """
    mapping = mapping or {}
    explicit = mapping.get("video_output_node_id", mapping.get("output_node_id"))
    if explicit is not None and str(explicit).strip():
        return str(explicit)

    save_nodes = [
        str(node_id)
        for node_id, node in workflow.items()
        if isinstance(node, dict) and str(node.get("class_type", "")).lower() == "savevideo"
    ]
    if len(save_nodes) == 1:
        return save_nodes[0]
    if len(save_nodes) > 1:
        raise ValueError(
            "This workflow contains multiple SaveVideo nodes. Add "
            "'video_output_node_id' to its workflow mapping."
        )
    raise ValueError(
        "No SaveVideo node was found. Add 'video_output_node_id' to the workflow mapping."
    )

def check_render(client, render, output_node_id=None):
    """A queue ID or a still image is never counted as a rendered video."""
    try:
        output = client.get_completed_output(render["prompt_id"], output_node_id=output_node_id)
        if output is not None:
            if Path(output["filename"]).suffix.lower() not in (".mp4", ".webm", ".mov", ".mkv", ".avi", ".m4v"):
                raise ComfyRenderError("The workflow completed without an expected video output.")
            render.update(state="completed", output=output, error="")
        return output
    except ComfyRenderError as exc:
        render.update(state="failed", error=str(exc))
        return None
    except ComfyUIError as exc:
        # Communication failures do not prove that a queued job failed.
        render["check_error"] = str(exc)
        raise



def completed_render(client, prompt_id, output_node_id=None):
    """Return completed ComfyUI video output plus bytes, or None while still rendering."""
    output = client.get_completed_output(prompt_id, output_node_id=output_node_id)
    if output is None:
        return None

    video_bytes = client.download_output(
        output["filename"],
        output.get("subfolder", ""),
        output.get("type", "output"),
    )
    return output, video_bytes
