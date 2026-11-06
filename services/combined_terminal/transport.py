"""Signed, bounded, redirect-free local worker transport with durable nonce guard."""
import hashlib
import hmac
import json
import math
import secrets
import sqlite3
import time
import httpx
from .contracts import WorkerResult, MUTATIONS

PATH = '/broker-worker/api/command'
MAX_BODY = 1024 * 1024


def sign(secret, body, path, *, now=None, nonce=None):
    at = str(time.time() if now is None else now)
    nonce = nonce or secrets.token_hex(24)
    message = b'POST\n' + path.encode() + b'\n' + at.encode() + b'\n' + nonce.encode() + b'\n' + body
    return {'X-Worker-Time': at, 'X-Worker-Nonce': nonce,
            'X-Worker-Signature': hmac.new(secret, message, hashlib.sha256).hexdigest()}


class ReplayGuard:
    def __init__(self, path):
        self.path = str(path)
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE IF NOT EXISTS worker_nonce (nonce TEXT PRIMARY KEY, expires REAL NOT NULL)')

    def verify(self, secret, body, path, headers, *, now=None):
        now = time.time() if now is None else now
        headers = {k.lower(): v for k, v in headers.items()}
        at, nonce, digest = (headers.get(k, '') for k in ('x-worker-time','x-worker-nonce','x-worker-signature'))
        try:
            value = float(at)
        except (TypeError, ValueError):
            raise PermissionError('Invalid worker authentication') from None
        if not math.isfinite(value) or abs(now-value) > 30 or not isinstance(nonce, str) or not 1 <= len(nonce) <= 128 or len(body) > MAX_BODY:
            raise PermissionError('Invalid worker authentication')
        expected = sign(secret, body, path, now=at, nonce=nonce)['X-Worker-Signature']
        if not isinstance(digest, str) or not hmac.compare_digest(expected, digest):
            raise PermissionError('Invalid worker authentication')
        # Include the key identity so independent configured workers may use the same nonce.
        key = hashlib.sha256(secret).hexdigest() + ':' + nonce
        try:
            with sqlite3.connect(self.path, timeout=5) as db:
                db.execute('DELETE FROM worker_nonce WHERE expires < ?', (now,))
                db.execute('INSERT INTO worker_nonce VALUES (?, ?)', (key, value+31))
        except sqlite3.IntegrityError:
            raise PermissionError('Replayed worker authentication') from None


class Transport:
    def __init__(self, registry, client=None, clock=time.time):
        self.registry, self.clock = registry, clock
        self.client = client or httpx.Client(trust_env=False, follow_redirects=False)

    def call(self, command):
        config = self.registry.config(command.connection)
        body = json.dumps(command.to_dict(), allow_nan=False, separators=(',', ':')).encode()
        headers = {'Content-Type': 'application/json', **sign(config.secret, body, PATH, now=self.clock())}
        try:
            response = self.client.post(config.url.rstrip('/')+PATH, content=body, headers=headers,
                                        timeout=httpx.Timeout(5, connect=2), follow_redirects=False)
        except httpx.HTTPError:
            return self._unavailable(command)
        if response.status_code != 200:
            return self._unavailable(command)
        if len(response.content) > MAX_BODY:
            raise ValueError('Invalid worker response')
        try:
            result = WorkerResult.from_dict(response.json())
        except (ValueError, KeyError, TypeError):
            raise ValueError('Invalid worker response') from None
        if result.connection != command.connection or result.operation_id != command.operation_id:
            raise ValueError('Worker response identity mismatch')
        return result

    def _unavailable(self, command):
        state = 'unknown' if command.action in MUTATIONS else 'rejected'
        return WorkerResult(command.operation_id, command.connection, state, {}, self.clock(),
                            'Worker unavailable; reconcile before retrying' if state == 'unknown' else 'Worker unavailable')
