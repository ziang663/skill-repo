import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from compare_token_ids import compare, read_ids, select


class ComparisonTests(unittest.TestCase):
    def test_equal_and_empty_arrays(self):
        for ids in ([], [1, 2, 3, 4]):
            result = compare(ids, ids, 2)
            self.assertTrue(result["equal"])
            self.assertIsNone(result["first_difference_index"])
            self.assertEqual(result["router_sha256"], result["backend_sha256"])

    def test_order_and_length_are_significant(self):
        for backend in ([1, 2, 4, 3], [1, 2]):
            result = compare([1, 2, 3, 4], backend, 2)
            self.assertFalse(result["equal"])
            self.assertEqual(result["first_difference_index"], 2)
            self.assertEqual(result["common_complete_pages"], 1)
        result = compare([1, 2], [1, 2, 3], 2)
        self.assertTrue(result["router_is_backend_prefix"])
        self.assertFalse(result["equal"])

    def test_bigram_requires_overlapping_boundary_token(self):
        for length, pages in ((0, 0), (2, 0), (3, 1), (4, 1), (5, 2)):
            ids = list(range(length))
            self.assertEqual(
                compare(ids, ids, 2, "bigram")["common_complete_pages"], pages
            )

    def test_escaped_pointer_and_array_index(self):
        self.assertEqual(select({"a/b": {"~key": [[7]]}}, "/a~1b/~0key/0"), [7])

    def test_cli_exit_codes_and_invalid_inputs(self):
        script = Path(__file__).with_name("compare_token_ids.py")
        with tempfile.TemporaryDirectory() as directory:
            router, backend = [
                Path(directory) / name for name in ("router.json", "backend.json")
            ]
            router.write_text(json.dumps([1, 2]))
            for value, expected in (
                ([1, 2], 0),
                ([1, 3], 1),
                ([True], 2),
                ([-1], 2),
                ({}, 2),
            ):
                backend.write_text(json.dumps(value))
                result = subprocess.run(
                    [
                        sys.executable,
                        str(script),
                        "--router",
                        str(router),
                        "--backend",
                        str(backend),
                        "--page-size",
                        "2",
                    ],
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, expected, result.stderr)
            with self.assertRaises(KeyError):
                read_ids(backend, "/missing")
        with self.assertRaises(ValueError):
            compare([1], [1], 0)


if __name__ == "__main__":
    unittest.main()
