import asyncio
import json
import unittest
from benchmark import core
from experiment import PROFILES, MODEL
from report import revenue
from warning_policy import classify_log
from adaptive_sampling import dispatch, early_decision


class TestExperiment(unittest.TestCase):
    def test_adaptive_checks_scheduled_prefix_not_fastest(self):
        rows=[{'id': i, 'success': True, 'ttft_s': .5, 'tpot_ms': 5,
               'cached_tokens': 945, 'input_tokens': 1000, 'start_clock': i*4.}
              for i in range(101)]
        self.assertIsNone(early_decision(rows[1:], PROFILES[MODEL], .94532, .25))
        self.assertTrue(early_decision(rows[:100], PROFILES[MODEL], .94532, .25)['eligible'])
        rows[0]['tpot_ms']=2000
        self.assertFalse(early_decision(rows[:100], PROFILES[MODEL], .94532, .25)['eligible'])

    def test_adaptive_drains_all_sent_requests(self):
        async def check():
            sent, finished = [], []
            async def send(i, planned):
                sent.append(i)
                await asyncio.sleep(.035 if i!=3 else .09)
                finished.append(i)
                return {'id': i}
            def decision(rows):
                return {'eligible': True} if all(i in [r['id'] for r in rows] for i in range(3)) else None
            rows, duration, result = await dispatch(12, 50, send, lambda *args: None, decision)
            self.assertTrue(result['early_stopped'])
            self.assertGreaterEqual(len(rows),3)
            self.assertLess(len(rows),12)
            self.assertEqual(sorted(sent),sorted(finished))
            self.assertEqual(sorted(sent),sorted(r['id'] for r in rows))
            self.assertTrue(result['all_inflight_drained'])
        asyncio.run(check())

    def test_adaptive_failed_check_continues_to_maximum(self):
        async def check():
            async def send(i, planned):
                await asyncio.sleep(.001)
                return {'id': i}
            decision=lambda rows: {'eligible': False} if len(rows)>=3 else None
            rows, duration, result=await dispatch(8,500,send,lambda *args: None,decision)
            self.assertEqual(len(rows),8)
            self.assertFalse(result['early_stopped'])
        asyncio.run(check())

    def test_allocator_warning_is_not_fatal(self):
        warning='[rank3]:[W914 03:50:36.437786958 CUDACachingAllocator.cpp:3933] memory allocation failed with OOM on device 3 while trying to allocate 3221225472 bytes.'
        scan=classify_log(warning)
        self.assertEqual(scan['allocator_warnings'],[warning])
        self.assertEqual(scan['runtime_errors'],[])

    def test_real_runtime_error_is_not_suppressed(self):
        for line in ('torch.OutOfMemoryError: CUDA out of memory.',
                     '[2026-09-14 TP0] Scheduler hit an exception',
                     'Traceback (most recent call last):',
                     'memory allocation failed: unexpected fatal condition'):
            scan=classify_log(line)
            self.assertEqual(scan['runtime_errors'],[line])
            self.assertEqual(scan['allocator_warnings'],[])

    def test_explicit_profiles(self):
        profile=PROFILES[MODEL]
        self.assertEqual(profile['model_path'],'/volume/dev/models/GLM-5.3-NVFP4')
        self.assertIn('--disable-shared-experts-fusion',profile['common'])
        for flag,value in [('--ep-size','1'),('--mem-fraction-static','0.85'),('--moe-a2a-backend','none'),('--kv-cache-dtype','fp8_e4m3')]:
            self.assertEqual(profile['common'][profile['common'].index(flag)+1],value)
        self.assertIn('--enable-dp-attention',profile['throughput'])
        self.assertNotIn('--enable-dp-attention',profile['sla'])
        self.assertEqual(profile['sla'][profile['sla'].index('--speculative-num-steps')+1],'5')

    def test_unrestricted_200_requests(self):
        self.assertEqual(core.FORMAL_REQUESTS,200)
        async def check():
            conn=core.connector()
            try:
                self.assertEqual(conn.limit,0)
                self.assertEqual(conn.limit_per_host,0)
                self.assertTrue(conn.force_close)
            finally:
                await conn.close()
        asyncio.run(check())

    def test_stream_counts_tokens(self):
        stream=core.Stream()
        stream.feed(json.dumps({'meta_info':{'completion_tokens':3,'prompt_tokens':10,'cached_tokens':8}}),.5)
        stream.feed(json.dumps({'meta_info':{'completion_tokens':6,'prompt_tokens':10,'cached_tokens':8,'finish_reason':{'type':'length'}}}),.6)
        result=stream.result(10,6)
        self.assertTrue(result['success'])
        self.assertAlmostEqual(result['tpot_ms'],20.)

    def test_sla_dataset(self):
        profile=PROFILES[MODEL]
        array,shared,manifest=core.dataset(profile,200,72125,.94532,64,20260913)
        self.assertEqual(array.shape,(200,72125))
        self.assertLess(abs(manifest['constructed_cache_rate']-.94532),.00001)
        self.assertEqual(len(shared)%64,0)
        self.assertEqual(json.loads(core.payload([1,2],1,'seed',7))['routed_dp_rank'],7)

    def test_revenue_uses_eight_gpus(self):
        self.assertAlmostEqual(revenue({'cached_input_tpm':1e6,'uncached_input_tpm':1e6,'output_tpm':1e6,'gpus':8}),(.26+1.4+4.4)*43200/8)


if __name__=='__main__':
    unittest.main()
