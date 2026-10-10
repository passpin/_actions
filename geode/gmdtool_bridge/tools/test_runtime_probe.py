"""Local, offline smoke tests (no game required)."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('runtime_probe', Path(__file__).with_name('runtime_probe.py'))
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class DiagnoseTests(unittest.TestCase):
    def setUp(self):
        self.first = {
            'playing': True, 'update_callbacks': 100,
            'percent': 0.1, 'player1': {'x': 50, 'y': 100},
            'trace': {'observed_updates': 8}, 'values': {'1': 0},
            'background': {'director_paused': False, 'window': {'foreground': False}},
        }

    def test_stalled(self):
        self.assertEqual(probe.diagnose(self.first, dict(self.first))['result'], 'game_callbacks_stalled')

    def test_progress(self):
        second = dict(self.first, update_callbacks=200, percent=0.2)
        self.assertEqual(probe.diagnose(self.first, second)['result'], 'game_progress_observed')

    def test_callbacks_only(self):
        second = dict(self.first, update_callbacks=200)
        self.assertEqual(probe.diagnose(self.first, second)['result'], 'callbacks_only')

    def test_attempt_changed(self):
        second = dict(self.first, update_callbacks=1)
        self.assertEqual(probe.diagnose(self.first, second)['result'], 'attempt_or_level_changed')

    def test_no_level(self):
        second = dict(self.first, playing=False)
        self.assertEqual(probe.diagnose(self.first, second)['result'], 'no_active_level')

    def test_item_change(self):
        second = dict(self.first, update_callbacks=120, values={'1': 2})
        self.assertTrue(probe.diagnose(self.first, second)['item_values_changed'])


if __name__ == '__main__':
    unittest.main()
