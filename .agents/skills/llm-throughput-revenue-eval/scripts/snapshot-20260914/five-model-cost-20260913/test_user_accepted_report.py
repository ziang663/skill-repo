"""Read-only regression checks for the explicitly accepted V4 Pro result."""
import copy
import unittest

from summarize_campaign import chosen, formal_results, user_accepted_throughput


class AcceptedReportingTests(unittest.TestCase):
    def setUp(self):
        self.results = formal_results()

    def test_first_run_selected_without_reclassifying_fail(self):
        before = copy.deepcopy(self.results)
        selected = user_accepted_throughput(self.results)
        self.assertEqual(selected['evidence'],
                         'benchmarks/v4pro-resume-04-throughput-inf/summary.json')
        self.assertEqual(selected['status'], 'FAIL')
        self.assertIsNone(chosen(self.results, 'v4pro', 'throughput'))
        self.assertEqual(self.results, before)

    def test_does_not_accept_request_failure(self):
        selected = user_accepted_throughput(self.results)
        selected['success'] = 199
        with self.assertRaises(AssertionError):
            user_accepted_throughput(self.results)

    def test_does_not_accept_additional_failure_reason(self):
        selected = user_accepted_throughput(self.results)
        selected['failure_reasons'].append('TTFT')
        with self.assertRaises(AssertionError):
            user_accepted_throughput(self.results)

    def test_sla_selection_unchanged(self):
        user_accepted_throughput(self.results)
        selected = chosen(self.results, 'v4pro', 'sla')
        self.assertEqual(selected['request_rate'], 0.75)
        self.assertEqual(selected['status'], 'PASS')


if __name__ == '__main__':
    unittest.main()
