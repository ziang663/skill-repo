import asyncio
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from standard_sla import instrument_native, parser, validate_prefixes


class PrefixTest(unittest.TestCase):
    def test_mixed_prefix_lengths_remain_cold_in_random_tails(self):
        seed = list(range(8))
        rows = [seed[:4] + [100] * 8, seed + [101] * 4]
        validate_prefixes(rows, seed, [4, 8], 4)

    def test_rejects_tail_page_reuse(self):
        with self.assertRaises(ValueError):
            validate_prefixes([list(range(12))] * 2, list(range(8)), [8, 8], 4)

    def test_rejects_wrong_declared_hit(self):
        with self.assertRaises(ValueError):
            validate_prefixes([list(range(12))], list(range(8)), [4], 4)

    def test_defaults_are_safe_and_native_arrivals(self):
        args = parser().parse_args([])
        self.assertFalse(args.execute)
        self.assertEqual(args.arrival, 'poisson')
        self.assertEqual(args.dataset, 'legacy-ids')


class NativeParityTest(unittest.TestCase):
    def compare(self, events):
        from sglang.benchmark import serving

        clock = [0.0]
        class Response:
            status = 200
            @property
            def content(self):
                async def chunks():
                    for elapsed, frame in events:
                        clock[0] = elapsed
                        body = frame if isinstance(frame, str) else json.dumps(frame)
                        yield ('data: ' + body + '\n\n').encode()
                return chunks()
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass

        class Session:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass
            def post(self, **kwargs):
                return Response()

        args = SimpleNamespace(temperature=0, disable_ignore_eos=False, top_p=1,
                               disable_stream=False, return_logprob=False,
                               return_routed_experts=False, logprob_start_len=-1,
                               top_logprobs_num=0, token_ids_logprob=None, cache_report=True)
        request = serving.RequestFuncInput(model='local', prompt=[1, 2], prompt_len=2,
                                          output_len=6, api_url='http://localhost/generate',
                                          lora_name=None, image_data=None, extra_request_body={})
        observers = []
        with patch.object(serving, 'args', args, create=True), \
             patch.object(serving, '_create_bench_client_session', Session), \
             patch.object(serving, 'get_request_headers', lambda: {}), \
             patch.object(serving.time, 'perf_counter', lambda: clock[0]):
            native = asyncio.run(serving.async_request_sglang_generate(request))
            clock[0] = 0.0
            observed, _ = instrument_native(serving, observers)
            actual = asyncio.run(observed(request))
        self.assertEqual(vars(native), vars(actual))
        self.assertEqual(len(observers), 1)
        self.assertEqual(observers[0].result['ttft_s'], native.ttft)
        return native, observers[0].result

    @staticmethod
    def frame(text, count):
        return {'text': text, 'meta_info': {'completion_tokens': count,
                                          'prompt_tokens': 2, 'cached_tokens': 0}}

    def test_empty_first_token_does_not_count_as_sla_ttft(self):
        native, audit = self.compare([
            (.2, self.frame('', 1)), (1.2, self.frame('a', 2)),
            (1.4, self.frame('abcdef', 6)), (1.41, '[DONE]'),
        ])
        self.assertEqual(native.ttft, 1.2)
        self.assertEqual(audit['legacy_first_token_ttft_s'], .2)
        self.assertEqual(audit['first_visible_completion_count'], 2)
        self.assertAlmostEqual(audit['tpot_ms'], 42)
        self.assertAlmostEqual(audit['legacy_token_to_token_tpot_ms'], 240)

    def test_multi_token_frames_and_protocol_tail(self):
        native, audit = self.compare([
            (.5, self.frame('abc', 3)), (.6, self.frame('abcdef', 6)), (.61, '[DONE]'),
        ])
        self.assertEqual(len(native.itl), 3)
        self.assertAlmostEqual(audit['tpot_ms'], 22)
        self.assertAlmostEqual(audit['legacy_token_to_token_tpot_ms'], 20)

    def test_usage_only_frame_not_first_text(self):
        native, audit = self.compare([
            (.1, {'meta_info': {'completion_tokens': 0}}),
            (.5, self.frame('abc', 3)), (.6, self.frame('abcdef', 6)), (.61, '[DONE]'),
        ])
        self.assertEqual(native.ttft, .5)
        self.assertEqual(audit['legacy_first_token_ttft_s'], .5)


if __name__ == '__main__':
    unittest.main()
