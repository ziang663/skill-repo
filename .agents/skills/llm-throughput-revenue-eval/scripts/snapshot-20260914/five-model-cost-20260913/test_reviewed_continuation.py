import unittest

from run_model import throughput_disposition


class ReviewedContinuationTests(unittest.TestCase):
    def setUp(self):
        self.summary = {'model': 'v4pro', 'status': 'FAIL',
                        'failure_reasons': ['cache_rate_mismatch'], 'requests': 200, 'success': 200,
                        'health_after': {'/health': {'http': 200}}}
        self.review = {'model': 'v4pro', 'disposition': 'retain_fail_continue_independent_sla',
                       'evidence_unchanged': True, 'diagnosis': 'review.md',
                       'repeat_evidence': 'independent/summary.json'}

    def test_normal_pass_still_supported(self):
        self.assertEqual(throughput_disposition({'status': 'PASS'}, None), 'target_passed')

    def test_cache_mismatch_is_not_reclassified(self):
        self.assertEqual(throughput_disposition(self.summary, self.review), 'reviewed_cache_target_failure')
        self.assertEqual(self.summary['status'], 'FAIL')

    def test_no_implicit_failure_override(self):
        with self.assertRaises(AssertionError):
            throughput_disposition(self.summary, None)

    def test_request_failure_cannot_be_overridden(self):
        self.summary['failure_reasons'].append('request_failure')
        with self.assertRaises(AssertionError):
            throughput_disposition(self.summary, self.review)

    def test_unhealthy_engine_cannot_be_overridden(self):
        self.summary['health_after']['/health']['http'] = 503
        with self.assertRaises(AssertionError):
            throughput_disposition(self.summary, self.review)

    def test_short_sample_cannot_be_overridden(self):
        self.summary['requests'] = self.summary['success'] = 100
        with self.assertRaises(AssertionError):
            throughput_disposition(self.summary, self.review)


if __name__ == '__main__':
    unittest.main()
