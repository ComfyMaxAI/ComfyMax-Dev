"""Lossless scene-manifest extensions and persistent Director state."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

KEY = "comfymax_director"
STATUSES = ("New", "Prompt Ready", "Ready to Render", "Rendered", "Failed")
MAX_BYTES = 20_000_000


def title(project):
    return str(project.get("project") or project.get("title") or "Untitled")


def new_scene():
    return {"id": uuid4().hex, "duration": 5.0, "lyrics": "", "action": ""}


def new_project():
    return validate_project({"version": 1, "id": uuid4().hex, "title": "Untitled",
                             "target_duration": 180.0, "scenes": [new_scene()]})


def _number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number.")
    return value


def scene_info(project, index):
    scene = project["scenes"][index]
    start = scene.get("start", sum(s["duration"] for s in project["scenes"][:index]))
    duration = scene.get("duration", scene.get("end", start) - start)
    return {"number": scene.get("scene", scene.get("scene_id", index + 1)),
            "start": start, "end": scene.get("end", start + duration), "duration": duration,
            "type": scene.get("type", "vocal" if scene.get("lyrics") else "instrumental").lower(),
            "lyrics": scene.get(KEY, {}).get("lyrics_override", scene.get("lyrics", scene.get("text", scene.get("context", ""))))}


def validate_project(value):
    if not isinstance(value, dict) or not isinstance(value.get("scenes"), list) or not 1 <= len(value["scenes"]) <= 1000:
        raise ValueError("Expected a project with 1–1000 scene objects.")
    if value.get("format") not in (None, "comfymax-scenes") or value.get("version", 1) != 1:
        raise ValueError("Unsupported scenes.json format/version.")
    project = copy.deepcopy(value)
    meta = project.setdefault(KEY, {})
    if not isinstance(meta, dict) or meta.get("version", 1) != 1:
        raise ValueError("Unsupported Director metadata.")
    meta.setdefault("version", 1)
    meta.setdefault("id", project.get("id") or uuid4().hex)
    if not isinstance(meta["id"], str) or not meta["id"] or len(meta["id"]) > 128:
        raise ValueError("Invalid Director project ID.")
    meta.setdefault("settings", {"video_style": project.get("style", "Cinematic"),
        "characters": project.get("characters", ""), "concept": project.get("concept", "")})
    if not isinstance(meta["settings"], dict):
        raise ValueError("Invalid global settings.")
    for name in ("video_style", "characters", "concept"):
        meta["settings"].setdefault(name, "")
        if not isinstance(meta["settings"][name], str):
            raise ValueError("Global settings must contain text.")
    ids = set()
    for index, scene in enumerate(project["scenes"]):
        if not isinstance(scene, dict):
            raise ValueError("Each scene must be an object.")
        duration = _number(scene.get("duration"), f"Scene {index + 1} duration")
        if duration <= 0 or duration > 3600:
            raise ValueError(f"Scene {index + 1} must have a positive duration no longer than one hour.")
        if not isinstance(scene.get("type", "instrumental"), str):
            raise ValueError(f"Scene {index + 1}: invalid type.")
        info = scene_info(project, index)
        start = _number(info["start"], "Start")
        end = _number(info["end"], "End")
        if start < 0 or end <= start or not math.isclose(end - start, duration, rel_tol=1e-7, abs_tol=1e-6):
            raise ValueError(f"Scene {index + 1}: start, end and duration disagree.")
        if info["type"] not in ("vocal", "instrumental"):
            raise ValueError(f"Scene {index + 1}: expected Vocal or Instrumental.")
        state = scene.setdefault(KEY, {})
        if not isinstance(state, dict):
            raise ValueError("Invalid Director scene metadata.")
        defaults = {"id": uuid4().hex, "artist_action": scene.get("action", "Standing still"),
            "camera_action": scene.get("camera", "Static camera"), "notes": scene.get("continuity", ""),
            "location": scene.get("location", ""), "picture_1_role": "facial identity of the performer",
            "picture_2_role": scene.get("location", ""), "lyric_language": "English",
            "continuation_action": "", "prompt_source": "",
            "clip_start_seconds": float(info["start"]),
            "workflow": "", "inputs": {}, "assets": {}, "prompt": scene.get("prompt", ""),
            "approved_signature": "", "status": "New", "render": {}, "duration_ack": False}
        for name, default in defaults.items():
            state.setdefault(name, default)
        try:
            state["clip_start_seconds"] = float(state.get("clip_start_seconds", info["start"]))
        except (TypeError, ValueError):
            state["clip_start_seconds"] = float(info["start"])
        if state["clip_start_seconds"] < 0 or not math.isfinite(state["clip_start_seconds"]):
            raise ValueError("Invalid scene clip_start_seconds.")
        if not isinstance(state["id"], str) or not state["id"] or state["id"] in ids:
            raise ValueError("Director scene IDs must be unique nonempty strings.")
        ids.add(state["id"])
        for name in ("artist_action", "camera_action", "notes", "location", "picture_1_role",
                     "picture_2_role", "lyric_language", "continuation_action", "prompt_source",
                     "workflow", "prompt", "approved_signature"):
            if not isinstance(state[name], str):
                raise ValueError(f"Invalid scene {name}.")
        if "lyrics_override" in state and not isinstance(state["lyrics_override"], str):
            raise ValueError("Invalid scene lyrics override.")
        for name in ("inputs", "assets", "render"):
            if not isinstance(state[name], dict):
                raise ValueError(f"Invalid scene {name}.")
        if state["status"] not in STATUSES or not isinstance(state["duration_ack"], bool):
            raise ValueError("Invalid scene status or duration acknowledgement.")
    return project


def timeline(project):
    return [{"Scene": (info := scene_info(project, i))["number"], "Start (s)": info["start"],
             "End (s)": info["end"], "Duration (s)": info["duration"], "Type": info["type"].title(),
             "Status": scene_status(project, scene)} for i, scene in enumerate(project["scenes"])]


def effective_workflow(project, scene):
    """Resolve scene override first, then the optional project-wide workflow."""
    state = scene[KEY]
    settings = project[KEY]["settings"]
    return str(state.get("workflow") or settings.get("workflow") or "")


def signature(project, scene):
    state = scene[KEY]
    relevant = {"source": {k: v for k, v in scene.items() if k != KEY},
        "settings": project[KEY]["settings"],
        "direction": {k: state.get(k) for k in ("artist_action", "camera_action", "notes",
            "location", "picture_1_role", "picture_2_role", "lyric_language", "continuation_action",
            "clip_start_seconds", "lyrics_override", "inputs", "assets", "prompt", "duration_ack", "workflow_digest", "video_model_override")},
        "effective_workflow": effective_workflow(project, scene)}
    return hashlib.sha256(json.dumps(relevant, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def scene_status(project, scene):
    state = scene[KEY]
    current = signature(project, scene)
    render = state["render"]
    if render.get("signature") == current:
        if render.get("state") in ("completed", "rendered") and render.get("output"):
            return "Rendered"
        if render.get("state") == "failed":
            return "Failed"
    if state["prompt"].strip():
        if state["approved_signature"] == current:
            return "Ready to Render"
        return "Prompt Ready"
    return "New"


def approve_scene(project, scene):
    if not scene[KEY]["prompt"].strip():
        raise ValueError("Review a nonempty prompt first.")
    if not effective_workflow(project, scene):
        raise ValueError("Choose a project workflow or a scene workflow before approving for render.")
    scene[KEY]["approved_signature"] = signature(project, scene)


def compose_prompt(project, scene, mapping=None):
    index = next(i for i, s in enumerate(project["scenes"]) if s[KEY]["id"] == scene[KEY]["id"])
    info = scene_info(project, index)
    state = scene[KEY]
    settings = project[KEY]["settings"]
    render_duration = state["inputs"].get("duration", info["duration"])

    lines = [
        f"Music video: {title(project)}",
        f"Video style: {settings['video_style']}",
        f"Recurring characters: {settings['characters']}",
        f"Concept / continuity: {settings['concept']}",
        f"Scene {info['number']} — {info['type'].title()}",
        f"Original song interval: {info['start']:.9f}–{info['end']:.9f} seconds; duration {info['duration']:.9f} seconds.",
        f"Requested rendered clip duration: {render_duration} seconds. Clip time starts at zero.",
        f"Artist action: {state['artist_action']}",
        f"Camera action: {state['camera_action']}",
        f"Scene direction / continuity: {state['notes']}",
        f"Workflow: {effective_workflow(project, scene)}",
    ]

    if mapping:
        lines.append(
            f"Workflow information: {mapping.get('description', '')}; "
            f"prompt mode: {mapping.get('h3_mode', 'general')}"
        )

    lyrics = str(info.get("lyrics") or "").strip()

    if info["type"] == "vocal":
        if lyrics:
            lines.extend([
                "",
                "=== VOCAL SCENE REQUIREMENT — MANDATORY ===",
                "The supplied lyrics below are part of the FINAL MiniMax H3 generation prompt.",
                "You MUST copy the supplied lyrics VERBATIM into the final generated prompt.",
                "Do not summarize, paraphrase, rewrite, shorten, correct, translate, or omit any lyric text.",
                "The literal lyric text MUST appear in the final prompt, preferably in detailed_description at the moment the subject sings.",
                "Explicitly state that the performing subject sings these exact words.",
                "The performance must be synchronized to the supplied audio.",
                "The supplied audio determines vocal timing, rhythm, phrasing, and lip synchronization.",
                "Do NOT replace the literal lyrics with generic wording such as 'sings the supplied lyrics', "
                "'sings with accurate lip sync', 'performs the lyrics', or similar wording.",
                "Do not invent any additional words, dialogue, or lyrics.",
                "",
                "EXACT LYRICS — COPY VERBATIM INTO THE FINAL PROMPT:",
                "<<<LYRICS",
                lyrics,
                "LYRICS",
                ">>>",
                "",
                "Before returning the final prompt, verify that the exact lyric text between "
                "<<<LYRICS and LYRICS>>> appears in your final generated prompt.",
            ])
        else:
            lines.extend([
                "",
                "=== VOCAL SCENE REQUIREMENT ===",
                "This scene is marked as Vocal, but no lyric transcript is available.",
                "Do not invent lyrics or dialogue.",
                "Use the supplied audio for performance timing and lip synchronization where the workflow supports audio.",
            ])
    else:
        lines.extend([
            "",
            "=== INSTRUMENTAL SCENE REQUIREMENT — MANDATORY ===",
            "This is an instrumental scene.",
            "Do not add singing, lyrics, spoken dialogue, or invented speech.",
            "Describe only the visual performance, action, camera work, atmosphere, and other relevant scene details.",
        ])

    lines.extend([
        "",
        "Audio handling:",
        "An audio filename is a source reference, not proof that audio is attached to the workflow.",
        "Do not claim that LM Studio has listened to or analyzed the audio.",
        "When the ComfyUI workflow receives the scene audio separately, the final H3 prompt should describe "
        "the intended synchronization without pretending the language model heard the audio.",
    ])

    return "\n".join(lines)


def export_project(project):
    project = validate_project(project)
    for scene in project["scenes"]:
        scene[KEY]["status"] = scene_status(project, scene)
    return json.dumps(project, ensure_ascii=False, indent=2, allow_nan=False)


def import_project(content):
    if len(content) > MAX_BYTES:
        raise ValueError("Project JSON must be smaller than 20 MB.")
    try:
        return validate_project(json.loads(content))
    except (UnicodeError, json.JSONDecodeError, RecursionError, TypeError, AttributeError) as exc:
        raise ValueError("Invalid scene project JSON.") from exc


class ProjectStore:
    def __init__(self, path: Path):
        self.path = Path(path)

    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                db.execute("CREATE TABLE IF NOT EXISTS projects (id TEXT PRIMARY KEY, title TEXT NOT NULL, updated TEXT NOT NULL, content TEXT NOT NULL)")
        except Exception:
            db.close()
            raise
        return db

    def save(self, project):
        content = export_project(project)
        with closing(self._connect()) as db, db:
            db.execute("INSERT INTO projects VALUES (?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET title=excluded.title, updated=excluded.updated, content=excluded.content",
                (project[KEY]["id"], title(project), datetime.now(timezone.utc).isoformat(), content))

    def list(self):
        with closing(self._connect()) as db:
            return [{"id": r[0], "title": r[1], "updated": r[2]} for r in db.execute(
                "SELECT id, title, updated FROM projects ORDER BY updated DESC, id")]

    def load(self, project_id):
        with closing(self._connect()) as db:
            row = db.execute("SELECT content FROM projects WHERE id=?", (project_id,)).fetchone()
        if row is None:
            raise ValueError("The selected project no longer exists.")
        return import_project(row[0])
