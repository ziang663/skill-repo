"""CPU-only regression for a socket closed during synchronous dataset preparation."""
import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import time
import unittest

import aiohttp


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def setup(self):
        super().setup()
        self.connection.settimeout(.15)

    def log_message(self, *_):
        pass

    def do_GET(self):
        data = b'{"ok":true}'
        self.send_response(200)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        self.rfile.read(int(self.headers.get('Content-Length', 0)))
        self.do_GET()


async def exercise(url, force_close):
    connector = aiohttp.TCPConnector(limit=0, limit_per_host=0, force_close=force_close)
    async with aiohttp.ClientSession(connector=connector, trust_env=False) as session:
        async with session.get(url) as response:
            await response.read()
        # Simulates CPU-bound token/dataset construction blocking the event loop.
        # The server runs on a separate thread and expires the idle connection.
        time.sleep(.4)
        try:
            async with session.post(url, data=b'{}') as response:
                await response.read()
                return {'http': response.status}
        except aiohttp.ClientError as exc:
            return {'error': repr(exc)}


class TestTransport(unittest.TestCase):
    def test_no_stale_keepalive_reuse_after_dataset_build(self):
        with ThreadingHTTPServer(('127.0.0.1', 0), Handler) as server:
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                url = f'http://127.0.0.1:{server.server_port}/'
                original = asyncio.run(exercise(url, False))
                revised = asyncio.run(exercise(url, True))
                print(json.dumps({'original': original, 'force_close': revised}), flush=True)
                self.assertIn('ServerDisconnectedError', original.get('error', ''))
                self.assertEqual(revised, {'http': 200})
            finally:
                server.shutdown()
                worker.join()


if __name__ == '__main__':
    unittest.main()
