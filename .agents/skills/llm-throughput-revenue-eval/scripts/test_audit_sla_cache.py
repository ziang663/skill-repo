"""Offline synthetic tests; never send HTTP requests or start GPU workloads."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from audit_sla_cache import audit_point, dataset_check, flush_events
from verify_snapshot import verify


class CacheAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.point = self.root / "benchmarks" / "point"
        self.point.mkdir(parents=True)
        self.log = self.root / "runs" / "engine" / "engine.log"
        self.log.parent.mkdir(parents=True)
        self.manifest = {"scenario": "sla", "n": 2, "input_tokens": 4, "output_tokens": 2,
                         "target_cache_rate": .5, "per_request_prefix_lengths": [2, 2],
                         "prefix_length_max": 2, "dp_attention_units": 1,
                         "active_engine": {"name": "engine", "model": "test"},
                         "client": {"script_sha256": "known"}, "dataset_sha256": "unused"}
        self.write("manifest.json", self.manifest)
        self.write("warmup.json", {"utc": "2026-09-14T00:00:10+00:00", "e2e_s": .2})
        self.write("flush.json", {"http": 200})
        self.seed = {"success": True, "input_tokens": 2, "output_tokens": 1, "cached_tokens": 0,
                     "utc": "2026-09-14T00:00:11+00:00"}
        self.write("cache-preseed.json", [self.seed])
        self.log.write_text("[2026-09-14 00:00:10 TP0] Cache flushed successfully!\n")

    def write(self, name, value):
        path = self.point / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))

    def check(self):
        flush_events.cache_clear()
        return audit_point(self.root, self.point / "manifest.json", {"known": ["frozen.py"]}, False)

    def test_no_summary_is_incomplete_not_pass(self):
        row = self.check()
        self.assertEqual(row["audit_status"], "INCOMPLETE")
        self.assertIn("no_final_summary", row["missing"])
        self.assertEqual(len(row["flush_log"]["events"]), 1)

    def test_http_200_does_not_prove_flush(self):
        self.log.write_text("[2026-09-14 00:00:00 TP0] Cache flushed successfully!\n")
        row = self.check()
        self.assertEqual(row["flush_log"]["events"], [])
        self.assertIn("successful_flush_log_not_verified_for_all_units", row["missing"])

    def test_dirty_preseed_flagged(self):
        self.seed["cached_tokens"] = 2
        self.write("cache-preseed.json", [self.seed])
        self.assertIn("preseed_nonzero_cache_requires_investigation", self.check()["errors"])

    def test_unexpected_cache_exceeds_prefix(self):
        self.write("requests/0000.json", {"id": 0, "success": True, "input_tokens": 4,
                                         "output_tokens": 2, "cached_tokens": 4})
        row = self.check()
        self.assertEqual(len(row["excess_cache_requests"]), 1)
        self.assertEqual(row["audit_status"], "FAIL")

    def test_dataset_exact_prefix_and_hash(self):
        data = np.asarray([[10, 20, 30, 40], [10, 20, 31, 41]], dtype=np.int32)
        shared = np.asarray([10, 20], dtype=np.int32)
        self.manifest["dataset_sha256"] = hashlib.sha256(data.tobytes()).hexdigest()
        path = self.point / "input_ids.npz"
        np.savez_compressed(path, input_ids=data, shared_prefix=shared)
        self.assertEqual(dataset_check(path, self.manifest)["errors"], [])
        data[1, 2] = 30
        np.savez_compressed(path, input_ids=data, shared_prefix=shared)
        problems = dataset_check(path, self.manifest)["errors"]
        self.assertIn("dataset_hash_mismatch", problems)
        self.assertIn("non_unique_tail_start", problems)

    def test_snapshot_tampering_is_detected_without_import(self):
        path = self.root / "frozen.py"
        content = b'raise RuntimeError("must not be executed")\n'
        path.write_bytes(content)
        (self.root / "SOURCES.json").write_text(json.dumps({"files": [
            {"path": "frozen.py", "sha256": hashlib.sha256(content).hexdigest()}]}))
        self.assertEqual(verify(self.root)["errors"], [])
        path.write_text("pass\n")
        self.assertEqual(verify(self.root)["errors"][0]["error"], "snapshot_hash_mismatch")


if __name__ == "__main__":
    unittest.main()
