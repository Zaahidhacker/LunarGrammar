"""Serve only the public browser regression fixture on loopback, never a directory."""
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


class Fixture(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != '/':
            self.send_error(404)
            return
        payload = Path(__file__).with_name('browser_fields.html').read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_args):
        pass


if __name__ == '__main__':
    HTTPServer(('127.0.0.1', 8765), Fixture).serve_forever()
