#!/usr/bin/env python3
"""Loopback-only dashboard with local testnet signing. No credentials served to browsers."""
import argparse
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

import build_charts
from seal_results import MAX_PAYLOAD, SEAL_LOG, near, seal, verify
from thesis_result import ROOT, canonical, generate


class Handler(BaseHTTPRequestHandler):
    def reply(self, status, value, content_type='application/json'):
        body = canonical(value).encode('utf-8') if content_type == 'application/json' else value
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(body)

    def trusted(self):
        expected = f'127.0.0.1:{self.server.server_port}'
        # Check GET too: prevent DNS rebinding from exposing data or invoking views.
        return self.headers.get('Host') == expected and self.headers.get('Origin', 'http://' + expected) == 'http://' + expected

    def do_GET(self):
        if not self.trusted():
            return self.reply(403, {'error': 'Use the loopback dashboard URL printed by the server'})
        path = urlsplit(self.path)
        try:
            if path.path == '/api/config':
                return self.reply(200, {'network': 'testnet', 'contract': os.environ.get('SEALED_LOG_CONTRACT', 'redsigma.testnet'),
                                        'signer': os.environ.get('NEAR_SIGNER_ACCOUNT', ''),
                                        'signing_configured': bool(os.environ.get('NEAR_CREDENTIALS_FILE') and os.environ.get('NEAR_SIGNER_ACCOUNT'))})
            if path.path == '/api/result':
                result = generate()
                return self.reply(200, {'result': result, 'action_data': canonical(result)})
            if path.path == '/api/history':
                return self.reply(200, json.loads(SEAL_LOG.read_text(encoding='utf-8')) if SEAL_LOG.exists() else {'entries': []})
            if path.path == '/api/entries':
                args = parse_qs(path.query)
                start, limit = int(args.get('from', ['1'])[0]), int(args.get('limit', ['10'])[0])
                if start < 1 or not 1 <= limit <= 100:
                    raise ValueError('from >= 1 and 1 <= limit <= 100 required')
                return self.reply(200, {'count': near('entry_count', {}), 'page': near('get_entries_paginated', {'from': start, 'limit': limit})})
            allowed = {'/': ('dashboard/index.html', 'text/html; charset=utf-8'),
                       '/dashboard/app.js': ('dashboard/app.js', 'text/javascript; charset=utf-8')}
            if path.path in allowed:
                filename, mime = allowed[path.path]
                return self.reply(200, (ROOT / filename).read_bytes(), mime)
            # Only generated chart PNGs are exposed; never serve repository or dotfiles.
            filename = Path(path.path).name
            if path.path == '/charts/' + filename and filename.endswith('.png') and (ROOT / 'charts' / filename).is_file():
                return self.reply(200, (ROOT / 'charts' / filename).read_bytes(), 'image/png')
            return self.reply(404, {'error': 'Not found'})
        except ValueError as exc:
            self.reply(400, {'error': str(exc)})
        except Exception as exc:
            self.reply(502, {'error': str(exc)})

    def do_POST(self):
        if not self.trusted() or self.headers.get('Content-Type') != 'application/json':
            return self.reply(403, {'error': 'Same-origin JSON requests required'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= MAX_PAYLOAD * 2:
                raise ValueError('Invalid request size')
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError('JSON object required')
            if self.path == '/api/generate':
                build_charts.build(build_charts._latest_raw())
                result = generate()
                return self.reply(200, {'result': result, 'action_data': canonical(result)})
            payload = body.get('action_data')
            if not isinstance(payload, str) or len(payload.encode('utf-8')) > MAX_PAYLOAD:
                raise ValueError('Provide action_data as a UTF-8 string up to 512000 bytes')
            if self.path == '/api/seal':
                result = json.loads(payload)
                if not isinstance(result, dict) or result.get('schema') != 'near-thesis-result/v1':
                    raise ValueError('Load or generate a near-thesis-result/v1 result first')
                return self.reply(200, seal('thesis-result', payload))
            if self.path == '/api/verify':
                entry_id = body.get('entry_id')
                if type(entry_id) is not int or not 1 <= entry_id <= 9007199254740991:
                    raise ValueError('Positive safe integer entry_id required')
                return self.reply(200, verify(entry_id, payload))
            self.reply(404, {'error': 'Not found'})
        except (ValueError, TypeError) as exc:
            self.reply(400, {'error': str(exc)})
        except Exception as exc:
            self.reply(502, {'error': str(exc)})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    if os.environ.get('NEAR_NETWORK', 'testnet') != 'testnet':
        raise ValueError('Only testnet is supported')
    server = HTTPServer(('127.0.0.1', args.port), Handler)
    print(f'Dashboard: http://127.0.0.1:{server.server_port}', flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
