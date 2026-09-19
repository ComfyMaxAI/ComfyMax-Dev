import copy
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import test_music_video_director as baseline
from streamlit.testing.v1 import AppTest
from modules.comfyui import ComfyUIError
from modules.h3_music_prompt_builder import build_h3_music_prompt
from modules.music_video_director import KEY, compose_prompt, export_project, scene_info, scene_status, signature
from modules.scene_workflow import load_mapped_workflow, render_asset_path

ROOT = Path(__file__).resolve().parents[1]


class RecoveryDataTests(unittest.TestCase):
    def test_edited_lyrics_preserve_original_and_unknown_fields(self):
        project = baseline.project()
        original = copy.deepcopy(project["scenes"][1])
        scene = project["scenes"][1]
        before = signature(project, scene)
        scene[KEY]["lyrics_override"] = "My exact revised words"
        self.assertNotEqual(signature(project, scene), before)
        self.assertEqual(scene_info(project, 1)["lyrics"], "My exact revised words")
        self.assertIn("My exact revised words", compose_prompt(project, scene))
        self.assertIn("My exact revised words", build_h3_music_prompt(project, scene))
        result = json.loads(export_project(project))["scenes"][1]
        original.pop(KEY)
        result.pop(KEY)
        self.assertEqual(result, original)

    def test_local_builder_does_not_invent_attached_media(self):
        project = baseline.project()
        scene = project["scenes"][1]
        prompt = build_h3_music_prompt(project, scene, render_duration=6)
        self.assertNotIn("incoming protected video context", prompt)
        self.assertNotIn("protected master-song", prompt)
        self.assertIn("6 seconds", prompt)
        self.assertIn("no source audio is attached", prompt)

    def test_render_paths_are_isolated(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = [render_asset_path(folder, project, scene, job, "clip.mp4")
                     for project, scene, job in [("a", "1", "x"), ("b", "1", "x"), ("a", "1", "y"), ("../../elsewhere", "1", "x")]]
            self.assertEqual(len(set(paths)), 4)
            self.assertTrue(all(path.resolve().is_relative_to(Path(folder).resolve()) for path in paths))

    def test_director_video_and_audio_vae_mappings_are_distinct(self):
        for name in ("director_minimax_1_ref.json", "director_minimax_2_ref.json", "director_minimax_NoAudio_1_ref.json"):
            graph, mapping, _ = load_mapped_workflow(ROOT, name)
            video = mapping["fields"]["video_vae"]
            audio = mapping["fields"]["audio_vae"]
            self.assertNotEqual(video["node_id"], audio["node_id"])
            self.assertIn("video_vae", graph[video["node_id"]]["inputs"]["vae_name"])
            self.assertIn("audio_vae", graph[audio["node_id"]]["inputs"]["vae_name"])


class RecoveryUITests(unittest.TestCase):
    setUp = baseline.DirectorUITests.setUp
    button = baseline.DirectorUITests.button
    select = baseline.DirectorUITests.select
    area = baseline.DirectorUITests.area
    prepare_workflow = baseline.DirectorUITests.prepare_workflow

    def test_local_regeneration_needs_explicit_replacement(self):
        self.area("Editable scene prompt").input("Keep my changes").run()
        self.assertTrue(self.button("Regenerate H3 Prompt").disabled)
        next(c for c in self.app.checkbox if c.label.startswith("Replace my current prompt")).check().run()
        with patch("modules.comfyui.ComfyUIClient.queue_prompt") as queue:
            self.button("Regenerate H3 Prompt").click().run()
            queue.assert_not_called()
        self.assertFalse(self.app.exception)
        self.assertIn("subject_definitions", self.area("Editable scene prompt").value)

    def test_approve_without_workflow_is_disabled(self):
        self.area("Editable scene prompt").input("Draft").run()
        self.assertTrue(self.button("Approve scene prompt").disabled)
        self.assertFalse(self.app.exception)

    def test_persistence_failure_blocks_submission(self):
        self.prepare_workflow()
        self.area("Editable scene prompt").input("Reviewed").run()
        self.button("Approve scene prompt").click().run()
        with patch.object(self.store, "save", side_effect=sqlite3.OperationalError("disk full")), \
             patch("modules.comfyui.ComfyUIClient.queue_prompt") as queue:
            self.button("Send to ComfyUI").click().run()
            queue.assert_not_called()
        self.assertFalse(self.app.exception)

    def test_restart_and_connection_failure_keep_same_job(self):
        self.prepare_workflow()
        self.area("Editable scene prompt").input("Reviewed").run()
        self.button("Approve scene prompt").click().run()
        with patch("modules.comfyui.ComfyUIClient.queue_prompt", return_value="resume-this-job") as queue:
            self.button("Send to ComfyUI").click().run()
            self.app = AppTest.from_file(str(ROOT / "App.py"), default_timeout=30).run()
            self.app.switch_page("pages/Music_Video_Scene_Director.py").run()
            self.assertTrue(self.button("Send to ComfyUI").disabled)
            with patch("modules.comfyui.ComfyUIClient.get_completed_output", side_effect=ComfyUIError("temporary outage")):
                self.button("Check render status").click().run()
            saved = self.store.load(self.store.list()[0]["id"])
            self.assertEqual(saved["scenes"][0][KEY]["render"]["state"], "queued")
            self.assertEqual(saved["scenes"][0][KEY]["render"]["prompt_id"], "resume-this-job")
            with patch("modules.comfyui.ComfyUIClient.get_completed_output", return_value={"filename": "video.mp4"}):
                self.button("Check render status").click().run()
            self.assertEqual(queue.call_count, 1)
        saved = self.store.load(self.store.list()[0]["id"])
        self.assertEqual(scene_status(saved, saved["scenes"][0]), "Rendered")

    def test_lyrics_edit_and_whisper_leave_source_unchanged(self):
        project = self.app.session_state["mvd_project"]
        scene = project["scenes"][1]
        original = copy.deepcopy(scene)
        folder = Path(self.temp.name)
        (folder / scene["audio_file"]).write_bytes(b"mock wave")
        project[KEY]["scenes_folder"] = str(folder)
        self.select("Select scene").select(scene[KEY]["id"]).run()
        self.area("Lyrics / transcript").input("Manual correction").run()
        with patch("modules.whisper_transcriber.transcribe_audio", return_value={"text": "Recognized words", "language": "en"}):
            self.button("Transcribe with Whisper").click().run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.area("Lyrics / transcript").value, "Recognized words")
        actual = self.app.session_state["mvd_project"]["scenes"][1]
        self.assertEqual(actual["lyrics"], original["lyrics"])
        self.assertNotIn("whisper_language", actual)

    def test_duration_does_not_silently_expand_fixed_mapping(self):
        self.select("Scene workflow").select("text_only.json").run()
        actual = baseline.manifest()["scenes"][0]["duration"]
        self.assertNotIn(str(actual), self.select("Duration").options)
        self.assertTrue(any(c.label.startswith("Use this render length") for c in self.app.checkbox))
