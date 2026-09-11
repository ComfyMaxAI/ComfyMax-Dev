import sys
import unittest
from pathlib import Path
from unittest.mock import Mock
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from modules.lmstudio import LMStudioClient, LMStudioError, LoadedInstance, ModelLoadConfirmationRequired

A = LoadedInstance('a', 'a-1')
B = LoadedInstance('b', 'b-1')

class LoadTests(unittest.TestCase):
    def client(self, states):
        c = LMStudioClient('http://localhost:1234')
        c.loaded_instances = Mock(side_effect=states)
        c._request = Mock(return_value=Mock(json=lambda: {'instance_id': 'new'}))
        return c

    def test_empty_loads(self):
        c = self.client([[]])
        self.assertEqual(c.load_model('b'), 'new')
        c._request.assert_called_once_with('POST', '/api/v1/models/load', json={'model': 'b'})

    def test_reuses_key_and_instance(self):
        for model in ['a', 'a-1']:
            c = self.client([[A]])
            self.assertEqual(c.load_model(model), 'a-1')
            c._request.assert_not_called()

    def test_conflict_and_multiple_require_confirmation(self):
        for instances in [[A], [A, B], [B, LoadedInstance('b', 'b-2')]]:
            c = self.client([instances])
            with self.assertRaises(ModelLoadConfirmationRequired):
                c.load_model('b')
            c._request.assert_not_called()

    def test_confirmed_unloads_before_load(self):
        c = self.client([[A, B], []])
        c.load_model('c', approved_instances=[A, B])
        self.assertEqual([x.args[1] for x in c._request.call_args_list],
                         ['/api/v1/models/unload', '/api/v1/models/unload', '/api/v1/models/load'])

    def test_changed_state_requires_new_consent(self):
        c = self.client([[A, B]])
        with self.assertRaises(ModelLoadConfirmationRequired):
            c.load_model('c', approved_instances=[A])
        c._request.assert_not_called()

    def test_remaining_instance_blocks_load(self):
        c = self.client([[A], [A]])
        with self.assertRaises(ModelLoadConfirmationRequired):
            c.load_model('b', approved_instances=[A])
        self.assertEqual(c._request.call_count, 1)

    def test_unload_failure_blocks_load(self):
        c = self.client([[A]])
        c._request.side_effect = LMStudioError('failed')
        with self.assertRaises(LMStudioError):
            c.load_model('b', approved_instances=[A])
        self.assertEqual(c._request.call_count, 1)

    def test_query_failure_blocks_load(self):
        c = self.client([])
        c.loaded_instances.side_effect = LMStudioError('offline')
        with self.assertRaises(LMStudioError):
            c.load_model('b')
        c._request.assert_not_called()

    def test_parser_fails_closed(self):
        c = LMStudioClient('http://localhost:1234')
        for data in [{}, [], {'models': [{}]}, {'models': [{'key': 'a', 'loaded_instances': [{}]}]}]:
            c._request = Mock(return_value=Mock(json=lambda: data))
            with self.assertRaises(LMStudioError):
                c.loaded_instances()
        c._request = Mock(return_value=Mock(json=lambda: {'models': [{'key': 'a', 'loaded_instances': [{'id': 'a-1'}]}]}))
        self.assertEqual(c.loaded_instances(), [A])

    def test_concurrent_clients_do_not_double_load(self):
        loaded = []
        def request(method, path, **kwargs):
            if method == 'GET':
                return Mock(json=lambda: {'models': [{'key': 'b', 'loaded_instances': list(loaded)}]})
            loaded.append({'id': 'b-1'})
            return Mock(json=lambda: {'instance_id': 'b-1'})
        clients = [LMStudioClient('http://localhost:1234') for _ in range(2)]
        for c in clients:
            c._request = Mock(side_effect=request)
        with ThreadPoolExecutor(2) as pool:
            self.assertEqual(list(pool.map(lambda c: c.load_model('b'), clients)), ['b-1', 'b-1'])
        self.assertEqual(len(loaded), 1)

if __name__ == '__main__':
    unittest.main()
