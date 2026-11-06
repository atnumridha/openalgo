"""Credential-free boundary types; all identifiers are account and mode scoped."""
from dataclasses import asdict, dataclass, field
import json
import math
import re

ACTIONS = frozenset({'receipt', 'status', 'snapshot', 'metadata', 'quote', 'history', 'ladder',
                     'preview', 'enter', 'exit', 'stop', 'cancel', 'reconcile', 'market', 'chart'})
MUTATIONS = frozenset({'enter', 'exit', 'stop', 'cancel'})


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[\w.@:+-]{1,128}', value):
        raise ValueError('Invalid identifier')
    return value


def timestamp(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError('Invalid timestamp')
    return value


@dataclass(frozen=True)
class ConnectionRef:
    id: str
    owner: str
    broker: str
    account: str
    mode: str

    def __post_init__(self):
        for value in (self.id, self.owner, self.account):
            identifier(value)
        if self.broker not in ('kotak', 'flattrade') or self.mode not in ('live', 'analyze'):
            raise ValueError('Unsupported connection')


@dataclass(frozen=True)
class WorkerCommand:
    operation_id: str
    connection: ConnectionRef
    action: str
    payload: dict
    created_at: float

    def __post_init__(self):
        identifier(self.operation_id)
        timestamp(self.created_at)
        if not isinstance(self.connection, ConnectionRef) or self.action not in ACTIONS or not isinstance(self.payload, dict):
            raise ValueError('Invalid command')
        # Reject NaN/infinite prices and values that cannot cross the JSON boundary.
        json.dumps(self.payload, allow_nan=False)

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, value):
        return cls(**{**value, 'connection': ConnectionRef(**value['connection'])})


@dataclass(frozen=True)
class WorkerResult:
    operation_id: str
    connection: ConnectionRef
    state: str
    data: dict
    captured_at: float
    error: str | None = None

    def __post_init__(self):
        identifier(self.operation_id)
        timestamp(self.captured_at)
        if not isinstance(self.connection, ConnectionRef) or self.state not in ('accepted', 'rejected', 'unknown') or not isinstance(self.data, dict):
            raise ValueError('Invalid result')
        json.dumps(self.data, allow_nan=False)
        if self.error is not None and not isinstance(self.error, str):
            raise ValueError('Invalid result error')

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, value):
        return cls(**{**value, 'connection': ConnectionRef(**value['connection'])})


@dataclass(frozen=True)
class AccountSnapshot:
    connection: ConnectionRef
    captured_at: float
    books_complete: bool
    quotes_fresh: bool
    orders: list = field(default_factory=list)
    fills: list = field(default_factory=list)
    positions: list = field(default_factory=list)
    funds: dict | None = None
    realized_net: float | None = None
    estimated_open_net: float | None = None
    error: str | None = None
    managed_trades: list = field(default_factory=list)
    charges: float | None = None
    estimated_exit_charges: float | None = None

    def __post_init__(self):
        timestamp(self.captured_at)
        if not isinstance(self.connection, ConnectionRef) or type(self.books_complete) is not bool or type(self.quotes_fresh) is not bool:
            raise ValueError('Invalid account snapshot')
        if any(not isinstance(v, list) for v in (self.orders, self.fills, self.positions, self.managed_trades)):
            raise ValueError('Invalid account books')
        for value in (self.realized_net, self.estimated_open_net, self.charges, self.estimated_exit_charges):
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int,float)) or not math.isfinite(value)):
                raise ValueError('Invalid account P&L')

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, value):
        return cls(**{**value, 'connection': ConnectionRef(**value['connection'])})


@dataclass(frozen=True)
class EntryIntent:
    operation_id: str
    connection: ConnectionRef
    preview_id: str
    payload_hash: str
    state: str


def scoped_id(connection, kind, broker_id):
    if not isinstance(broker_id, str) or not broker_id or not isinstance(kind, str) or not kind:
        raise ValueError('Missing broker identity')
    return json.dumps([connection.broker, connection.account, connection.mode, kind, broker_id], separators=(',', ':'))
