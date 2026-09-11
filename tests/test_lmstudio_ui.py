import sys
import unittest
from pathlib import Path
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from streamlit.testing.v1 import AppTest
from modules.lmstudio import LoadedInstance, ModelLoadConfirmationRequired, GeneratedPrompt

class UITests(unittest.TestCase):
    def test_confirmation_and_cancel(self):
        for multiple in [False, True]:
            for approve in [False, True]:
                instances = [LoadedInstance('a', 'a-1')]
                if multiple:
                    instances.append(LoadedInstance('c', 'c-1'))
                with patch('modules.lmstudio.LMStudioClient.list_models', return_value=['b']), patch('modules.lmstudio.LMStudioClient.load_model', side_effect=[ModelLoadConfirmationRequired(instances), 'b-1']) as load, patch('modules.lmstudio.LMStudioClient.generate_prompt', return_value=GeneratedPrompt('result', 'b', 'b-1')), patch('modules.lmstudio.LMStudioClient.unload_model') as unload:
                    app = AppTest.from_file(str(ROOT / 'App.py'), default_timeout=30).run()
                    button = lambda label: next(b for b in app.button if b.label == label)
                    app.selectbox[0].select(ROOT / 'workflows/text_only.json').run()
                    next(x for x in app.text_area if x.label == 'What would you like to create?').input('A mountain').run()
                    self.assertFalse(button('Generate H3 prompt').disabled)
                    button('Generate H3 prompt').click().run()
                    self.assertFalse(app.exception)
                    self.assertTrue(app.warning)
                    self.assertEqual(load.call_count, 1)
                    unload.assert_not_called()
                    if multiple:
                        self.assertIn('Multiple', app.warning[0].value)
                    button('Unload and continue' if approve else 'Cancel new load').click().run()
                    self.assertFalse(app.exception)
                    self.assertNotIn('lm_pending_load', app.session_state)
                    if approve:
                        self.assertEqual(load.call_args.kwargs['approved_instances'], instances)
                        self.assertEqual(app.text_area(key='final_prompt_editor').value, 'result')
                    else:
                        self.assertEqual(load.call_count, 1)
                        unload.assert_not_called()
                    self.assertFalse(button('Unload all models from LM Studio').disabled)

if __name__ == '__main__':
    unittest.main()
