from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
D = Decimal


@dataclass(frozen=True)
class Candle:
    time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal = D(0)
    confirmed: bool = True
    repaired: bool = False


@dataclass(frozen=True)
class NeoPreset:
    profile: str
    label: str
    model: str
    ema_filter: bool = False
    controlled: bool = False
    research_only: bool = False
    reward_risk: Decimal = D(6)
    entry_length: int = 20
    last_entry_minute: int = 915
    square_off_minute: int = 929


@dataclass(frozen=True)
class Setup:
    profile: str
    candle_open: datetime
    execute_at: datetime
    direction: str
    index_reference: Decimal
    initial_stop: Decimal
    target: Decimal
    atr: Decimal
    structure_stop: Decimal | None = None

    @property
    def key(self):
        return self.profile + ":" + self.execute_at.isoformat() + ":" + self.direction


@dataclass(frozen=True)
class Contract:
    symbol: str
    exchange: str
    expiry: date
    strike: Decimal
    option_type: str
    lot_size: int
    tick_size: Decimal


@dataclass(frozen=True)
class Quote:
    symbol: str
    bid: Decimal
    ask: Decimal
    bid_qty: int
    ask_qty: int
    received_at: datetime
    exchange_time: datetime | None
    verified_depth_snapshot: bool = False

    def fresh(self, now):
        if (
            now.tzinfo is None
            or self.received_at.tzinfo is None
            or not 0 <= (now - self.received_at).total_seconds() <= 5
        ):
            return False
        if self.exchange_time is None:
            return self.verified_depth_snapshot
        return (
            self.exchange_time.tzinfo is not None
            and 0 <= (now - self.exchange_time).total_seconds() <= 5
        )


@dataclass(frozen=True)
class Selection:
    ok: bool
    contract: Contract | None = None
    quote: Quote | None = None
    quantity: int = 0
    limit_price: Decimal = D(0)
    entry_cost: Decimal = D(0)
    option_stop: Decimal | None = None
    error: str | None = None


@dataclass(frozen=True)
class EntryResult:
    ok: bool
    run_id: int | None = None
    error: str | None = None


@dataclass(frozen=True)
class NeoDeskConfig:
    profile: str = "orb_trail"
    activation: str = "Stopped"
    mode: str = "sandbox"
    last_entry_minute: int = 915
    square_off_minute: int = 929
