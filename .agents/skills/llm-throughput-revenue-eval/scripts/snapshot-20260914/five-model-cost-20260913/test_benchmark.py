import json
import asyncio
import unittest

from benchmark import Stream, dataset, PROFILES, payload, effective_args, connector, FORMAL_REQUESTS
from report_results import peak_hours, revenue


class TestMeasurement(unittest.TestCase):
    def test_formal_samples_and_no_connection_pool_cap(self):
        self.assertEqual(FORMAL_REQUESTS, 200)
        async def check():
            conn = connector()
            try:
                self.assertEqual(conn.limit, 0)
                self.assertEqual(conn.limit_per_host, 0)
                self.assertTrue(conn.force_close)
            finally:
                await conn.close()
        asyncio.run(check())

    def test_server_info_layouts(self):
        args = {"model_path": "/m", "tp_size": 8}
        self.assertEqual(effective_args(args), args)
        self.assertEqual(effective_args({"server_args": args}), args)
        d = {**args, "disable_chunked_prefix_cache": False,
             "internal_states": [{**args, "disable_chunked_prefix_cache": True}]}
        self.assertTrue(effective_args(d)["disable_chunked_prefix_cache"])
        with self.assertRaises(RuntimeError):
            effective_args({"error": "bad"})

    def test_revenue_uses_actual_gpus_and_peak_calendar(self):
        self.assertEqual(peak_hours("weekdays_01_04_06_10_utc"), 147)
        self.assertEqual(peak_hours("daily_01_04_06_10_utc"), 210)
        s = {"model": "glm53flash", "gpus": 4, "cached_input_tpm": 1000000,
             "uncached_input_tpm": 1000000, "output_tpm": 1000000}
        self.assertAlmostEqual(revenue(s)["weighted"], (.03+.15+.5)*43200/4)

    def test_speculative_stream_counts_tokens_not_chunks(self):
        stream = Stream()
        stream.feed(json.dumps({"text":"abc", "meta_info":{"completion_tokens":3,"prompt_tokens":10,"cached_tokens":8}}), .5)
        stream.feed(json.dumps({"text":"abcdef", "meta_info":{"completion_tokens":6,"prompt_tokens":10,"cached_tokens":8,"finish_reason":{"type":"length"}}}), .6)
        stream.feed("[DONE]", .61)
        row = stream.result(10, 6)
        self.assertTrue(row['success'])
        self.assertAlmostEqual(row['tpot_ms'], 20.)
        self.assertEqual(len(row['token_events']), 2)

    def test_failed_and_short_outputs_are_not_success(self):
        for finish in ('abort','length'):
            stream = Stream()
            stream.feed(json.dumps({'meta_info':{'completion_tokens':3,'prompt_tokens':10,'finish_reason':{'type':finish}}}), .5)
            self.assertFalse(stream.result(10, 6)['success'])

    def test_error_event(self):
        stream = Stream()
        stream.feed('{"error":"failure"}', .1)
        self.assertFalse(stream.result(10,6)['success'])

    def test_exact_lengths_and_weighted_page_rounding(self):
        array, shared, meta = dataset(PROFILES['v41'], 200, 8000, .932, 256, 1)
        self.assertEqual(array.shape, (200, 8000))
        self.assertAlmostEqual(meta['constructed_cache_rate'], .932)
        for ids, n in zip(array, meta['per_request_prefix_lengths']):
            self.assertEqual(n%256, 0)
            self.assertTrue((ids[:n] == shared[:n]).all())
            if n < len(shared):
                self.assertNotEqual(ids[n], shared[n])

    def test_payload(self):
        p = json.loads(payload([1,2,3], 8, 'test', 2))
        self.assertEqual(p['routed_dp_rank'], 2)
        self.assertTrue(p['sampling_params']['ignore_eos'])


if __name__ == '__main__':
    unittest.main()
