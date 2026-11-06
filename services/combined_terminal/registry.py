"""Private fixed worker allowlist. Never serialize credentials or service URLs."""
from dataclasses import dataclass, field
import ipaddress
from urllib.parse import urlsplit
from .contracts import ConnectionRef


@dataclass(frozen=True)
class WorkerConfig:
    connection: ConnectionRef
    url: str = field(repr=False)
    secret: bytes = field(repr=False)

    def __post_init__(self):
        try:
            url = urlsplit(self.url)
            local = ipaddress.ip_address(url.hostname).is_loopback
            port = url.port
        except (ValueError, TypeError):
            raise ValueError('Worker must use a fixed loopback origin') from None
        if url.scheme != 'http' or not local or not port or url.username or url.password or url.query or url.fragment or url.path not in ('', '/'):
            raise ValueError('Worker must use a fixed loopback origin')
        if not isinstance(self.secret, bytes) or len(self.secret) < 32:
            raise ValueError('Worker signing key unavailable')
        if not isinstance(self.connection, ConnectionRef):
            raise ValueError('Invalid worker identity')


class Registry:
    def __init__(self, workers):
        self._workers = {}
        for worker in workers:
            if worker.connection.id in self._workers:
                raise ValueError('Duplicate connection ID')
            self._workers[worker.connection.id] = worker

    def config(self, connection):
        worker = self._workers.get(connection.id)
        if worker is None or worker.connection != connection:
            raise PermissionError('Connection identity mismatch')
        return worker

    def connection(self, user, connection_id):
        worker = self._workers.get(connection_id)
        if worker is None or worker.connection.owner != user:
            raise PermissionError('Connection unavailable')
        return worker.connection

    def connections(self, user):
        return [w.connection for w in self._workers.values() if w.connection.owner == user]

    def public(self, user):
        return [{'id': c.id, 'broker': c.broker, 'account': c.account, 'mode': c.mode}
                for c in self.connections(user)]
