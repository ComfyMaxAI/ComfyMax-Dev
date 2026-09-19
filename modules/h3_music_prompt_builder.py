"""Deterministic MiniMax H3 music-video prompt builder.

Creates the official six-section REF2VA-style music-video prompt locally.
The full master song is the authoritative audio timeline; short scene audio is
only a Director/Whisper aid and is never described as the H3 master audio.
"""
from __future__ import annotations

DIRECTOR_KEY = "comfymax_director"


def _clean(value, fallback=""):
    text = str(value or "").strip()
    return text or fallback


def _sentence(value):
    text = _clean(value)
    if not text:
        return ""
    return text if text[-1] in ".!?" else text + "."


def build_h3_music_prompt(project, scene, image_count=0, render_duration=None, audio_source=None, has_video_context=False):
    """Build one deterministic MiniMax H3 music-video prompt."""
    scenes = project.get("scenes", [])
    try:
        index = next(i for i, item in enumerate(scenes) if item is scene)
    except StopIteration:
        index = 0

    state = scene.get(DIRECTOR_KEY, {})
    settings = project.get(DIRECTOR_KEY, {}).get("settings", {})

    scene_type = _clean(scene.get("type"), "vocal" if scene.get("lyrics") else "instrumental").lower()
    lyrics = _clean(state.get("lyrics_override", scene.get("lyrics") or scene.get("text") or scene.get("context")))
    style = _clean(settings.get("video_style"), "cinematic music-video")
    location = _clean(state.get("location"), "the established performance environment")
    artist_action = _clean(state.get("artist_action"), "performs naturally")
    camera_action = _clean(state.get("camera_action"), "Static camera")
    notes = _clean(state.get("notes"))
    language = _clean(state.get("lyric_language"), "English")
    picture_1_role = _clean(state.get("picture_1_role"), "facial identity of the performer")
    picture_2_role = _clean(state.get("picture_2_role"), location)
    continuation_action = _clean(
        state.get("continuation_action"),
        "Keep the final body motion and camera trajectory in progress so the next clip can continue the same physical shot.",
    )

    # clip_start_seconds belongs to the workflow/master-song timeline.  It is
    # intentionally not written as an instruction to 'seek' audio in the prompt:
    # the SongMaskedAVContext node already supplies the exact protected audio slice.
    try:
        clip_start_seconds = float(state.get("clip_start_seconds", scene.get("start", 0.0)))
    except (TypeError, ValueError):
        clip_start_seconds = 0.0

    has_refs = image_count > 0
    if image_count >= 2:
        subject_definitions = (
            f"<Subject 1> is the main performer whose {picture_1_role} comes from <Picture 1>; "
            f"<Picture 2> defines {picture_2_role}."
        )
    elif image_count == 1:
        subject_definitions = (
            f"<Subject 1> is the main performer whose {picture_1_role} comes from <Picture 1>."
        )
    else:
        subject_definitions = "<Subject 1> is the main performer in the music video."

    summary_prefix = "[reference generation] " if has_refs else ""
    if index == 0 or not has_video_context:
        summary = (
            f"{summary_prefix}<Subject 1> begins the continuous music-video performance in {location}, "
            "establishing the performer, physical action, and camera movement."
        )
    else:
        summary = (
            f"{summary_prefix}Continue the existing music video with <Subject 1> in {location} without "
            "resetting the referenced performer or the incoming visual state."
        )

    if has_refs:
        retention = (
            "<Subject 1> (appears throughout [Shot 1]): fully_preserved - retain the referenced facial identity, "
            "hair identity, body proportions, wardrobe, colors, and stable distinguishing features while pose, "
            "expression, lighting, framing, and movement follow the current performance and incoming continuation state."
        )
    else:
        retention = (
            "<Subject 1> (appears throughout [Shot 1]): fully_preserved - maintain the same performer identity, "
            "body proportions, wardrobe, colors, and stable distinguishing features while pose, expression, lighting, "
            "framing, and movement evolve naturally."
        )

    detail_parts = []
    if index == 0 or not has_video_context:
        detail_parts.append(f"The performance begins in {location}.")
    else:
        detail_parts.append(
            "The existing performer motion, camera trajectory, body momentum, facial state, lighting, environment, "
            "and object state continue uninterrupted from the incoming protected video context."
        )

    detail_parts.append(_sentence(f"<Subject 1> (S1) {artist_action}"))
    detail_parts.append(_sentence(camera_action))

    if scene_type == "vocal":
        if lyrics:
            detail_parts.append(
                "<Subject 1> (S1) performs in exact synchronization with the current protected master-song phrase. "
                "Mouth shapes, jaw articulation, breaths, facial performance, head motion, gestures, and body rhythm "
                f"follow the supplied song timing while the visible singer performs: <d>[{language}] {lyrics}</d>"
            )
        else:
            detail_parts.append(
                "<Subject 1> (S1) performs the current protected master-song vocal phrase with clear readable mouth "
                "and jaw articulation synchronized to the supplied song timing. Do not invent lyrics or dialogue."
            )
    else:
        detail_parts.append(
            "This master-song section is instrumental. <Subject 1> follows its rhythm and musical dynamics through "
            "natural body movement and performance energy without singing, speaking, or invented dialogue."
        )

    if settings.get("characters"):
        detail_parts.append(_sentence(settings["characters"]))
    if settings.get("concept"):
        detail_parts.append(_sentence(settings["concept"]))
    if render_duration is not None:
        detail_parts.append(f"Keep the complete clip within {float(render_duration):g} seconds, starting at clip time zero.")
    if notes:
        detail_parts.append(_sentence(notes))
    if index < len(scenes) - 1:
        detail_parts.append(_sentence(continuation_action))

    detailed = " ".join(part for part in detail_parts if part)

    if scene_type == "vocal":
        music = (
            "The current section of the original protected master song remains the dominant audience-only musical "
            "layer. The visible singing, breathing, phrasing, body rhythm, gestures, and emotional intensity remain "
            "synchronized to this exact song section. The untouched original master song remains the final soundtrack."
        )
    else:
        music = (
            "The current instrumental section of the original protected master song remains the dominant audience-only "
            "musical layer. Body rhythm, movement, camera energy, and emotional timing follow this exact song section. "
            "The untouched original master song remains the final soundtrack."
        )

    if audio_source == "scene":
        detailed = detailed.replace("protected master-song", "supplied scene-audio")
        music = music.replace("original protected master song", "supplied scene audio").replace("untouched original master song", "supplied scene audio")
    elif audio_source is None:
        detailed = detailed.replace("performs in exact synchronization with the current protected master-song phrase", "performs the requested vocal phrase")
        detailed = detailed.replace("follow the supplied song timing", "follow the requested phrasing")
        detailed = detailed.replace("current protected master-song vocal phrase", "requested vocal phrase")
        detailed = detailed.replace("synchronized to the supplied song timing", "with natural phrasing")
        detailed = detailed.replace("This master-song section", "This scene")
        music = "N/A — no source audio is attached by this mapping."

    # Keep useful timing as a harmless comment-like sentence outside the H3 syntax only
    # when notes need debugging? No: production prompt remains clean. The workflow owns timing.
    _ = (clip_start_seconds, render_duration)

    return (
        "subject_definitions:\n"
        f"{subject_definitions}\n\n"
        "summary:\n"
        f"{summary}\n\n"
        "retention_analysis:\n"
        f"{retention}\n\n"
        "detailed_description:\n"
        f"The target video has a {style} style with natural skin texture, coherent lighting, restrained contrast, "
        "and physically grounded camera movement.\n"
        f"[Shot 1] {detailed}\n\n"
        "overall_soundscape:\n"
        "Very subtle diegetic room or environmental tone, cloth movement, footsteps, and other natural physical "
        "sounds beneath the song; keep them restrained so the master song dominates.\n\n"
        "non_diegetic_music:\n"
        f"{music}"
    )
