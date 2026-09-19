import copy
import json
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from streamlit.testing.v1 import AppTest
from modules.comfyui import ComfyUIClient, ComfyUIError, ComfyRenderError
from modules.lmstudio import GeneratedPrompt, LoadedInstance, ModelLoadConfirmationRequired
from modules.music_video_director import (
    KEY, ProjectStore, approve_scene, compose_prompt, export_project, import_project,
    new_project, scene_status, signature, timeline,
)
from modules.scene_workflow import (
    check_render, load_mapped_workflow, read_image, store_image, submit_mapped_workflow,
)


def manifest(count=2):
    rate = 44100
    return {"format": "comfymax-scenes", "version": 1, "project": "Fixture song",
        "sample_rate": rate, "channels": 2, "audio_encoding": "float32",
        "total_frames": count * 233059, "duration": count * 233059 / rate,
        "unknown_project": {"preserve": [1, 2, 3]},
        "scenes": [{"scene": i + 1, "start": i * 233059 / rate,
            "end": (i + 1) * 233059 / rate, "duration": 233059 / rate,
            "type": "vocal" if i % 2 else "instrumental", "audio_source": "vocals" if i % 2 else "full_mix",
            "audio_file": f"scene_{i + 1:03d}.wav", "start_frame": i * 233059,
            "end_frame": (i + 1) * 233059, "frames": 233059,
            "lyrics": "Écoute-moi" if i % 2 else "", "unknown_scene": {"keep": True}}
            for i in range(count)]}


def project():
    return import_project(json.dumps(manifest()))


class DirectorDataTests(unittest.TestCase):
    def test_lossless_export_and_reopen(self):
        original = manifest(60)
        value = import_project(json.dumps(original))
        state = value["scenes"][1][KEY]
        state.update(artist_action="Dancing", camera_action="Tracking shot", workflow="text_only.json", prompt="Exact edited prompt")
        with tempfile.TemporaryDirectory() as folder:
            store = ProjectStore(Path(folder) / "projects.sqlite3")
            store.save(value)
            reopened = store.load(value[KEY]["id"])
            self.assertEqual(reopened["scenes"][1][KEY]["artist_action"], "Dancing")
            self.assertEqual(reopened["scenes"][1][KEY]["workflow"], "text_only.json")
            output = json.loads(export_project(reopened))
            output.pop(KEY)
            for scene in output["scenes"]:
                scene.pop(KEY)
            self.assertEqual(output, original)
            self.assertEqual(len(timeline(reopened)), 60)
            self.assertEqual(timeline(reopened)[1]["Start (s)"], original["scenes"][1]["start"])

    def test_existing_director_drafts_migrate_without_loss(self):
        original = {"version": 1, "id": "old-project", "title": "Earlier draft", "style": "Neon",
            "extra": ["keep"], "scenes": [{"id": "old-scene", "duration": 7.0,
            "action": "Walk", "camera": "Orbit", "lyrics": "Bonjour", "prompt": "User edits"}]}
        loaded = import_project(json.dumps(original))
        self.assertEqual(loaded[KEY]["id"], "old-project")
        self.assertEqual(loaded[KEY]["settings"]["video_style"], "Neon")
        self.assertEqual(loaded["scenes"][0][KEY]["prompt"], "User edits")
        self.assertEqual(loaded["extra"], ["keep"])

    def test_invalid_imports(self):
        for text in ("bad JSON", "[]", '{"scenes": []}', b"\xff"):
            with self.assertRaises(ValueError):
                import_project(text)
        for duration in (0, -1, float("nan"), float("inf"), True):
            value = manifest()
            value["scenes"][0]["duration"] = duration
            with self.assertRaises(ValueError):
                import_project(json.dumps(value))
        value = manifest()
        value["scenes"][0]["type"] = {"bad": True}
        with self.assertRaises(ValueError):
            import_project(json.dumps(value))

    def test_approval_invalidates_and_old_render_is_not_current(self):
        value = project()
        scene = value["scenes"][0]
        state = scene[KEY]
        self.assertEqual(scene_status(value, scene), "New")
        state.update(prompt="Reviewed text", workflow="text_only.json")
        self.assertEqual(scene_status(value, scene), "Prompt Ready")
        approve_scene(value, scene)
        self.assertEqual(scene_status(value, scene), "Ready to Render")
        state["render"] = {"signature": signature(value, scene), "state": "completed", "output": {"filename": "clip.mp4"}}
        self.assertEqual(scene_status(value, scene), "Rendered")
        state["prompt"] = "Edited again"
        self.assertEqual(scene_status(value, scene), "Prompt Ready")
        approve_scene(value, scene)
        value[KEY]["settings"]["video_style"] = "Rock"
        self.assertEqual(scene_status(value, scene), "Prompt Ready")
        state["render"] = {"signature": signature(value, scene), "state": "failed", "error": "GPU error"}
        self.assertEqual(scene_status(value, scene), "Failed")
        state["inputs"]["duration"] = 10
        self.assertEqual(scene_status(value, scene), "Prompt Ready")

    def test_prompt_contains_source_type_lyrics_and_workflow(self):
        value = project()
        scene = value["scenes"][1]
        scene[KEY].update(workflow="text_only.json", artist_action="Walking toward camera")
        scene[KEY]["inputs"]["duration"] = 6
        prompt = compose_prompt(value, scene, {"h3_mode": "ref2va"})
        for expected in ("Scene 2", "Vocal", "Écoute-moi", "Walking toward camera", "text_only.json", "6 seconds", "Clip time starts at zero"):
            self.assertIn(expected, prompt)
        self.assertIn("do not add singing", compose_prompt(value, value["scenes"][0]).lower())


class WorkflowTests(unittest.TestCase):
    def test_submission_uses_existing_mapping_and_upload(self):
        workflow, mapping, digest = load_mapped_workflow(ROOT, "text_only.json")
        client = Mock()
        client.queue_prompt.return_value = "queued-id"
        client.upload_image.return_value = "input/ref.png"
        mapping["fields"]["test_image"] = {"node_id": "1", "input": "image", "type": "image"}
        job, values = submit_mapped_workflow(client, workflow, mapping, {"prompt": "Exact approved text", "duration": 6, "seed": 0},
            {"test_image": ("ref.png", b"image", "image/png")})
        self.assertEqual(job, "queued-id")
        self.assertGreater(values["seed"], 0)
        mapped = client.queue_prompt.call_args.args[0]
        self.assertEqual(mapped["1"]["inputs"]["value"], "Exact approved text")
        self.assertEqual(mapped["1"]["inputs"]["image"], "input/ref.png")
        self.assertNotIn("image", workflow["1"]["inputs"])

    def test_history_requires_successful_video_and_detects_errors(self):
        client = ComfyUIClient("http://unused")
        for container in ("images", "videos", "gifs"):
            history = {"job": {"status": {"completed": True, "status_str": "success"}, "outputs": {
                "preview": {"images": [{"filename": None}, {"filename": "preview.png"}]}, "result": {container: [{"filename": "clip.mp4"}]}}}}
            with patch.object(client, "get_history", return_value=history):
                self.assertEqual(client.get_completed_output("job")["filename"], "clip.mp4")
        with patch.object(client, "get_history", return_value={"job": {"status": {"completed": False, "status_str": "error"}}}):
            with self.assertRaises(ComfyRenderError):
                client.get_completed_output("job")
        with patch.object(client, "get_history", return_value={"job": {"status": {"completed": True, "status_str": "success"}, "outputs": {}}}):
            with self.assertRaises(ComfyRenderError):
                client.get_completed_output("job")
        with patch.object(client, "get_history", return_value={}):
            self.assertIsNone(client.get_completed_output("job"))

    def test_render_failures_vs_connection_failures(self):
        client = Mock()
        render = {"prompt_id": "job", "state": "queued"}
        client.get_completed_output.side_effect = ComfyUIError("Connection lost")
        with self.assertRaises(ComfyUIError):
            check_render(client, render)
        self.assertEqual(render["state"], "queued")
        client.get_completed_output.side_effect = ComfyRenderError("GPU failed")
        check_render(client, render)
        self.assertEqual(render["state"], "failed")
        client.get_completed_output.side_effect = None
        client.get_completed_output.return_value = {"filename": "result.mp4"}
        check_render(client, render)
        self.assertEqual(render["state"], "completed")

    def test_image_storage_reopen_and_path_validation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            asset = store_image(root, b"reference", "image.png", "image/png")
            self.assertEqual(read_image(root, asset)[1], b"reference")
            altered = {**asset, "path": "../outside.png"}
            with self.assertRaises(ValueError):
                read_image(root, altered)
            (root / asset["path"]).write_bytes(b"modified")
            with self.assertRaises(ValueError):
                read_image(root, asset)


class DirectorUITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = ProjectStore(Path(self.temp.name) / "test.sqlite3")
        for target, kwargs in [
            ("modules.music_video_director.ProjectStore", {"return_value": self.store}),
            ("modules.lmstudio.LMStudioClient.list_models", {"return_value": ["test-model"]}),
            ("modules.lmstudio.LMStudioClient.load_model", {"return_value": "instance"}),
            ("modules.lmstudio.LMStudioClient.unload_model", {}),
            ("urllib.request.urlopen", {"side_effect": urllib.error.URLError("Test: service not connected")}),
            ("modules.comfyui.ComfyUIClient.download_output", {"side_effect": ComfyUIError("Test: no preview download")}),
        ]:
            patcher = patch(target, **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.app = AppTest.from_file(str(ROOT / "App.py"), default_timeout=30).run()
        self.app.session_state["mvd_project"] = project()
        self.app.switch_page("pages/Music_Video_Scene_Director.py").run()

    def button(self, label):
        return next(b for b in self.app.button if b.label == label)

    def select(self, label):
        return next(s for s in self.app.selectbox if s.label == label)

    def area(self, label):
        return next(s for s in self.app.text_area if s.label == label)

    def prepare_workflow(self):
        self.select("Scene workflow").select("text_only.json").run()
        next(c for c in self.app.checkbox if c.label.startswith("Use this render length")).check().run()
        self.assertFalse(self.app.exception)

    def test_edit_approve_render_and_reopen(self):
        self.prepare_workflow()
        self.area("Editable scene prompt").input("Manually reviewed scene").run()
        self.button("Approve scene prompt").click().run()
        self.assertFalse(self.button("Send to ComfyUI").disabled)
        with patch("modules.comfyui.ComfyUIClient.queue_prompt", return_value="job") as queue:
            self.button("Send to ComfyUI").click().run()
            self.assertFalse(self.app.exception)
            self.assertEqual(queue.call_count, 1)
            self.assertEqual(queue.call_args.args[0]["1"]["inputs"]["value"], "Manually reviewed scene")
        self.assertTrue(self.button("Send to ComfyUI").disabled)
        with patch("modules.comfyui.ComfyUIClient.get_completed_output", return_value={"filename": "scene.mp4", "subfolder": "videos", "type": "output"}):
            self.button("Check render status").click().run()
        self.assertFalse(self.app.exception)
        saved = self.store.load(self.store.list()[0]["id"])
        self.assertEqual(scene_status(saved, saved["scenes"][0]), "Rendered")
        second = saved["scenes"][1][KEY]["id"]
        self.select("Select scene").select(second).run()
        self.assertEqual(self.select("Scene workflow").value, "__project__")
        self.assertEqual(self.area("Editable scene prompt").value, "")
        self.button("Open project").click().run()
        self.select("Select scene").select(saved["scenes"][0][KEY]["id"]).run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.area("Editable scene prompt").value, "Manually reviewed scene")
        self.area("Editable scene prompt").input("Changed prompt").run()
        self.assertTrue(self.button("Render Again").disabled)

    def test_generation_is_editable_never_queues_and_requires_replace(self):
        self.prepare_workflow()
        next(r for r in self.app.radio if r.label == "Prompt generator").set_value("LM Studio").run()
        with patch("modules.lmstudio.LMStudioClient.generate_prompt", return_value=GeneratedPrompt("Generated scene", "test-model", "instance")) as generate, \
             patch("modules.comfyui.ComfyUIClient.queue_prompt") as queue:
            self.button("Generate Prompt with LM Studio").click().run()
            self.assertFalse(self.app.exception)
            self.assertEqual(self.area("Editable scene prompt").value, "Generated scene")
            self.assertIn("Instrumental", generate.call_args.args[0])
            self.assertIn("text_only.json", generate.call_args.args[0])
            queue.assert_not_called()
            self.assertTrue(self.button("Regenerate with LM Studio").disabled)
            self.area("Editable scene prompt").input("My edits").run()
            self.assertEqual(self.area("Editable scene prompt").value, "My edits")
            self.assertTrue(self.button("Send to ComfyUI").disabled)

    def test_model_confirmation_cancel_preserves_prompt(self):
        self.prepare_workflow()
        next(r for r in self.app.radio if r.label == "Prompt generator").set_value("LM Studio").run()
        with patch("modules.lmstudio.LMStudioClient.load_model", side_effect=ModelLoadConfirmationRequired([LoadedInstance("other", "other-id")])):
            self.button("Generate Prompt with LM Studio").click().run()
        self.assertFalse(self.app.exception)
        self.button("Cancel model load").click().run()
        self.assertNotIn("mvd_pending_load", self.app.session_state)
        self.assertEqual(self.area("Editable scene prompt").value, "")

    def test_presets_and_failed_render_persist(self):
        self.prepare_workflow()
        self.select("Artist action").select("Dancing").run()
        self.select("Camera action").select("Custom").run()
        next(x for x in self.app.text_input if x.label == "Custom camera action").input("Crane above the singer").run()
        self.area("Editable scene prompt").input("Scene prompt").run()
        self.button("Approve scene prompt").click().run()
        with patch("modules.comfyui.ComfyUIClient.queue_prompt", return_value="failed-job"):
            self.button("Send to ComfyUI").click().run()
        with patch("modules.comfyui.ComfyUIClient.get_completed_output", side_effect=ComfyRenderError("GPU failed")):
            self.button("Check render status").click().run()
        saved = self.store.load(self.store.list()[0]["id"])
        self.assertEqual(scene_status(saved, saved["scenes"][0]), "Failed")
        self.assertEqual(saved["scenes"][0][KEY]["artist_action"], "Dancing")
        self.assertEqual(saved["scenes"][0][KEY]["camera_action"], "Crane above the singer")
        self.assertEqual(saved["scenes"][0][KEY]["render"]["prompt_id"], "failed-job")

    def test_existing_main_page_still_submits_approved_prompt(self):
        self.app.switch_page("App.py").run()
        self.app.selectbox(key="selected_workflow").select(ROOT / "workflows/text_only.json").run()
        self.app.text_area(key="final_prompt_editor").input("Main-page approved text").run()
        self.button("Approve prompt").click().run()
        with patch("modules.comfyui.ComfyUIClient.queue_prompt", return_value="main-job") as queue, \
             patch("modules.comfyui.ComfyUIClient.get_completed_output", return_value={"filename": "main.mp4"}), \
             patch("modules.comfyui.ComfyUIClient.download_output", return_value=b"test video"), \
             patch("modules.comfyui.ComfyUIClient.get_execution_seconds", return_value=1.0), \
             patch("modules.comfyui.ComfyUIClient.get_used_seed", return_value=123):
            self.button("Send to ComfyUI").click().run()
        self.assertFalse(self.app.exception)
        self.assertEqual(queue.call_count, 1)
        self.assertEqual(queue.call_args.args[0]["1"]["inputs"]["value"], "Main-page approved text")
        self.assertEqual(self.app.session_state["last_prompt_id"], "main-job")


if __name__ == "__main__":
    unittest.main()
