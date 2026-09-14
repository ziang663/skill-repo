import unittest

from run_model import validated_launch_overrides


class TestLaunchOverrides(unittest.TestCase):
    def record(self, values, model='v4pro'):
        return {'model': model, 'authorization': 'User approved local memory/graph tuning',
                'reason': 'Preserved baseline startup OOM', 'strategies': {'sla': values}}

    def test_recorded_memory_and_graph_settings(self):
        values = ['--mem-fraction-static', '0.88', '--cuda-graph-max-bs-decode', '64']
        self.assertEqual(validated_launch_overrides(self.record(values), 'v4pro'), {'sla': values})

    def test_reject_unrelated_or_duplicate_flags(self):
        for values in (['--tp', '4'], ['--max-running-requests', '64'],
                       ['--cuda-graph-max-bs-decode', '64', '--cuda-graph-max-bs-decode', '32']):
            with self.subTest(values=values), self.assertRaises((ValueError, AssertionError)):
                validated_launch_overrides(self.record(values), 'v4pro')

    def test_reject_invalid_values(self):
        for flag, value in (('--mem-fraction-static', '0'), ('--mem-fraction-static', '1'),
                            ('--mem-fraction-static', 'nan'), ('--cuda-graph-max-bs-decode', '0'),
                            ('--cuda-graph-max-bs-decode', '-1'), ('--cuda-graph-max-bs-decode', '1.5')):
            with self.subTest(flag=flag, value=value), self.assertRaises((ValueError, AssertionError)):
                validated_launch_overrides(self.record([flag, value]), 'v4pro')

    def test_reject_wrong_model_missing_approval_or_bad_shape(self):
        for record in (self.record(['--cuda-graph-max-bs-decode', '64'], 'glm53'),
                       {**self.record(['--cuda-graph-max-bs-decode', '64']), 'authorization': ''},
                       self.record(['--cuda-graph-max-bs-decode']),
                       {**self.record(['--cuda-graph-max-bs-decode', '64']), 'strategies': {'unknown': ['x', '1']}}):
            with self.subTest(record=record), self.assertRaises(AssertionError):
                validated_launch_overrides(record, 'v4pro')


if __name__ == '__main__':
    unittest.main()
