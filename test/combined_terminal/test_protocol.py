"""Isolation/authentication boundaries, using real signing and HTTP normalization."""
import json
from dataclasses import asdict

import httpx
import pytest


def refs():
    from services.combined_terminal.contracts import ConnectionRef
    return (ConnectionRef('kotak-main', 'alice', 'kotak', 'a' * 24, 'live'),
            ConnectionRef('flat-main', 'alice', 'flattrade', 'b' * 24, 'live'))


def test_colliding_broker_ids_remain_distinct():
    from services.combined_terminal.contracts import scoped_id
    a, b = refs()
    assert scoped_id(a, 'order', '123') != scoped_id(b, 'order', '123')
    assert scoped_id(a, 'order', '123') != scoped_id(a, 'fill', '123')


def test_connection_requires_owner():
    from services.combined_terminal.registry import Registry, WorkerConfig
    a, _ = refs()
    r = Registry([WorkerConfig(a, 'http://127.0.0.1:5002', b'x' * 32)])
    assert r.connection('alice', a.id) == a
    with pytest.raises(PermissionError):
        r.connection('bob', a.id)


def test_private_fields_not_serialized():
    from services.combined_terminal.registry import Registry, WorkerConfig
    a, _ = refs()
    config = WorkerConfig(a, 'http://127.0.0.1:5002', b'secret-value-' * 4)
    result = json.dumps(Registry([config]).public('alice'))
    assert 'secret-value' not in result
    assert '127.0.0.1' not in result
    assert 'secret-value' not in repr(config)


@pytest.mark.parametrize('url', ['http://example.org:5002', 'http://127.0.0.1.evil:5002',
                                'http://user:pass@127.0.0.1:5002', 'http://127.0.0.1:5002?x=y',
                                'http://127.0.0.1:5002/proxy'])
def test_remote_worker_refused(url):
    from services.combined_terminal.registry import WorkerConfig
    with pytest.raises(ValueError):
        WorkerConfig(refs()[0], url, b'x' * 32)


def test_wrong_account_response_rejected():
    from services.combined_terminal.contracts import WorkerCommand
    from services.combined_terminal.registry import Registry, WorkerConfig
    from services.combined_terminal.transport import Transport
    a, b = refs()
    def endpoint(req):
        return httpx.Response(200, json={'operation_id': 'op1', 'connection': asdict(b),
                                        'state': 'accepted', 'data': {}, 'captured_at': 100, 'error': None})
    registry = Registry([WorkerConfig(a, 'http://127.0.0.1:5002', b'x' * 32)])
    transport = Transport(registry, httpx.Client(transport=httpx.MockTransport(endpoint)), clock=lambda: 100)
    with pytest.raises(ValueError, match='identity'):
        transport.call(WorkerCommand('op1', a, 'snapshot', {}, 100))


def test_redirected_worker_refused():
    from services.combined_terminal.contracts import WorkerCommand
    from services.combined_terminal.registry import Registry, WorkerConfig
    from services.combined_terminal.transport import Transport
    a = refs()[0]
    seen = []
    def endpoint(req):
        seen.append(str(req.url))
        return httpx.Response(307, headers={'location': 'http://example.org/leak'})
    transport = Transport(Registry([WorkerConfig(a, 'http://127.0.0.1:5002', b'x' * 32)]),
                          httpx.Client(transport=httpx.MockTransport(endpoint)))
    result = transport.call(WorkerCommand('op1', a, 'enter', {}, 100))
    assert result.state == 'unknown'
    assert len(seen) == 1


def test_signature_replay_and_tamper_refused(tmp_path):
    from services.combined_terminal.transport import sign, ReplayGuard
    secret = b'x' * 32
    path = '/broker-worker/api/command'
    body = b'{"operation_id":"op1"}'
    headers = sign(secret, body, path, now=100, nonce='first')
    guard = ReplayGuard(tmp_path / 'nonces.db')
    guard.verify(secret, body, path, headers, now=100)
    with pytest.raises(PermissionError):
        ReplayGuard(tmp_path / 'nonces.db').verify(secret, body, path, headers, now=100)
    fresh = sign(secret, body, path, now=100, nonce='second')
    with pytest.raises(PermissionError):
        guard.verify(secret, body+b'x', path, fresh, now=100)
    with pytest.raises(PermissionError):
        guard.verify(secret, body, '/another', fresh, now=100)
    with pytest.raises(PermissionError):
        guard.verify(secret, body, path, fresh, now=131)


def test_timeout_never_becomes_rejection():
    from services.combined_terminal.contracts import WorkerCommand
    from services.combined_terminal.registry import Registry, WorkerConfig
    from services.combined_terminal.transport import Transport
    a = refs()[0]
    def endpoint(req):
        raise httpx.ReadTimeout('sensitive upstream detail')
    transport = Transport(Registry([WorkerConfig(a, 'http://127.0.0.1:5002', b'x'*32)]),
                          httpx.Client(transport=httpx.MockTransport(endpoint)))
    result = transport.call(WorkerCommand('op1', a, 'enter', {}, 100))
    assert result.state == 'unknown'
    assert 'sensitive' not in result.error


@pytest.mark.parametrize('value', [float('nan'), float('inf'), -1])
def test_invalid_command_timestamp_refused(value):
    from services.combined_terminal.contracts import WorkerCommand
    with pytest.raises(ValueError):
        WorkerCommand('op1', refs()[0], 'enter', {}, value)
