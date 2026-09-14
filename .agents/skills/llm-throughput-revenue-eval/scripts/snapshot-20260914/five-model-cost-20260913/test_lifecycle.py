import socket
import unittest
from unittest.mock import patch

import engine_lifecycle as lifecycle


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.record = {'name': 'test-owned', 'pid': 123, 'port': 30480}
        self.ready = {'live_group_pids': [], 'port_released': True, 'gpus_released': True}

    def check_sequence(self, blocked):
        with patch.object(lifecycle, 'release_state', side_effect=[blocked, self.ready]) as read:
            with patch.object(lifecycle.time, 'sleep') as sleep:
                result = lifecycle.wait_for_release(self.record, 2)
        self.assertTrue(result['port_released'])
        self.assertEqual(read.call_count, 2)
        sleep.assert_called_once()

    def test_waits_for_process_after_gpu_release(self):
        self.check_sequence({**self.ready, 'live_group_pids': [123]})

    def test_waits_for_port_after_gpu_and_process_release(self):
        self.check_sequence({**self.ready, 'port_released': False})

    def test_waits_for_gpu_after_port_release(self):
        self.check_sequence({**self.ready, 'gpus_released': False})

    def test_timeout_does_not_signal_any_process(self):
        with patch.object(lifecycle, 'release_state', return_value={**self.ready, 'port_released': False}):
            with self.assertRaises(TimeoutError):
                lifecycle.wait_for_release(self.record, 2, timeout=0)

    def test_real_bound_port_is_not_available(self):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen()
            port = listener.getsockname()[1]
            self.assertFalse(lifecycle.port_released(port))
        self.assertTrue(lifecycle.port_released(port))


if __name__ == '__main__':
    unittest.main()
