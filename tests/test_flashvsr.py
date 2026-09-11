import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from modules.flashvsr_paths import output_directory, reserve_output
from modules.flashvsr_client import _parse_progress_line, run_flashvsr, FlashVSRError


class IntegrationTests(unittest.TestCase):
    def test_settings_and_collision(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'config').mkdir()
            with self.assertRaises(ValueError):
                output_directory(root)
            (root / 'config/settings.json').write_text(json.dumps({'comfyui_output_folder': temp}))
            target = output_directory(root)
            self.assertEqual(target, root / 'videos/upscaled')
            first = reserve_output(target, 'clip.mp4')
            first.write_bytes(b'original')
            second = reserve_output(target, 'clip.mp4')
            self.assertNotEqual(first, second)
            self.assertEqual(first.read_bytes(), b'original')

    def test_progress_protocol(self):
        self.assertEqual(_parse_progress_line('COMFYMAX_PROGRESS|101|done').percent, 100)
        self.assertIsNone(_parse_progress_line('COMFYMAX_PROGRESS|bad|broken'))

    def test_failed_worker_reports_log(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            video = root / 'input.mp4'
            video.write_bytes(b'input')
            with patch('modules.flashvsr_client.validate_flashvsr_install', return_value={'python': root/'python.exe', 'worker':root/'worker.py', 'root':root}), patch('modules.flashvsr_client.subprocess.Popen') as spawn:
                spawn.return_value.stdout = iter(['GPU failed\n'])
                spawn.return_value.wait.return_value = 1
                with self.assertRaisesRegex(FlashVSRError, 'GPU failed'):
                    run_flashvsr(root, video, root/'output.mp4')

    def test_corrupt_model_does_not_replace_existing(self):
        engine = Path(__file__).resolve().parents[1] / 'engines/flashvsr'
        spec = importlib.util.spec_from_file_location('installer', engine/'installer.py')
        installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'models').mkdir()
            (root/'source').mkdir()
            (root/'models/model').write_bytes(b'original')
            (root/'source/model').write_bytes(b'corrupt')
            (root/'models.json').write_text(json.dumps({'model':{'sha256':'bad', 'url':'unused'}}))
            with self.assertRaisesRegex(RuntimeError, 'checksum mismatch'):
                installer.install_models(root, root/'source')
            self.assertEqual((root/'models/model').read_bytes(), b'original')
            self.assertFalse((root/'models/model.partial').exists())


if __name__ == '__main__':
    unittest.main()
