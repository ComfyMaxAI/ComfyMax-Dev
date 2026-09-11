import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from modules.prompt_library import PromptLibrary
from streamlit.testing.v1 import AppTest


class LibraryTests(unittest.TestCase):
    def test_storage(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'library.sqlite3'
            lib = PromptLibrary(path)
            for text, approved in [('hello', False), ('  ', True)]:
                with self.assertRaises(ValueError):
                    lib.save(text, approved=approved)
            prompt = 'Café 🌅\nA camera moves. <script>literal</script>'
            self.assertTrue(lib.save(prompt, approved=True, workflow='video', prompt_type='t2v'))
            self.assertFalse(lib.save(prompt, approved=True, workflow='video', prompt_type='t2v'))
            reopened = PromptLibrary(path)
            self.assertEqual(reopened.list('CAFÉ')[0]['prompt'], prompt)
            self.assertEqual(len(reopened.list(workflow='other')), 0)
            self.assertEqual(len(reopened.list(prompt_type='t2v')), 1)
            with ThreadPoolExecutor(max_workers=4) as pool:
                list(pool.map(lambda i: PromptLibrary(path).save(str(i), approved=True), range(12)))
            self.assertEqual(len(reopened.list()), 13)
            row = reopened.list('CAFÉ')[0]
            self.assertTrue(reopened.delete(row['id']))
            self.assertFalse(reopened.delete(row['id']))
            self.assertFalse(reopened.list('CAFÉ'))

    def test_ui(self):
        with tempfile.TemporaryDirectory() as folder:
            lib = PromptLibrary(Path(folder) / 'test.sqlite3')
            with patch('modules.prompt_library.PromptLibrary', return_value=lib), \
                 patch('modules.lmstudio.LMStudioClient.list_models', return_value=[]):
                app = AppTest.from_file(str(ROOT / 'App.py'), default_timeout=30).run()
                self.assertFalse(app.exception)
                button = lambda at, label: next(b for b in at.button if b.label == label)
                self.assertTrue(button(app, 'Save approved prompt').disabled)
                app.text_area(key='final_prompt_editor').input('Approved café prompt').run()
                button(app, 'Approve prompt').click().run()
                self.assertFalse(button(app, 'Save approved prompt').disabled)
                button(app, 'Save approved prompt').click().run()
                self.assertEqual(len(lib.list()), 1)
                button(app, 'Save approved prompt').click().run()
                self.assertEqual(len(lib.list()), 1)
                app.text_area(key='final_prompt_editor').input('Changed prompt').run()
                self.assertTrue(button(app, 'Save approved prompt').disabled)
                page = AppTest.from_file(str(ROOT / 'App.py'), default_timeout=30).run()
                page.switch_page('pages/Prompt_Library.py').run()
                self.assertFalse(page.exception)
                self.assertEqual(page.code[0].value, 'Approved café prompt')
                page.text_input[0].input('no match').run()
                self.assertEqual(len(page.code), 0)
                page.text_input[0].input('CAFÉ').run()
                self.assertEqual(len(page.code), 1)
                button(page, 'Delete prompt').click().run()
                self.assertEqual(len(lib.list()), 1)
                button(page, 'Cancel').click().run()
                self.assertEqual(len(lib.list()), 1)
                button(page, 'Reuse prompt').click().run()
                self.assertFalse(page.exception)
                self.assertEqual(page.text_area(key='final_prompt_editor').value, 'Approved café prompt')
                self.assertFalse(page.session_state['prompt_approved'])
                page.switch_page('pages/Prompt_Library.py').run()
                app.session_state['library_reuse'] = lib.list()[0]
                app.run()
                self.assertEqual(app.text_area(key='final_prompt_editor').value, 'Approved café prompt')
                self.assertFalse(app.session_state['prompt_approved'])
                button(page, 'Delete prompt').click().run()
                button(page, 'Confirm delete').click().run()
                self.assertFalse(lib.list())
                self.assertFalse(page.exception)

if __name__ == '__main__':
    unittest.main()

