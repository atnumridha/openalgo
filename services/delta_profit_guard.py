"""Durable, explicitly adopted Delta protection; never submits an entry."""
import hashlib
import json
import math
import time
import uuid
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
import threading

from sqlalchemy import Boolean, Column, String, Text, select
from sqlalchemy.orm import DeclarativeBase, Session

from services.risk.profit_protection import evaluate
from utils.smart_order_guard import SymbolLocks

locks = SymbolLocks(name='delta-profit-protection')


class ProtectionError(ValueError):
    """An explanation safe to display to the operator."""


class ProtectionChanged(ProtectionError):
    """Ownership or protection changed; explicit re-adoption is required."""


class NotSubmitted(ProtectionError):
    """Preflight failed before any broker mutation was attempted."""


class UnsentProtectionChanged(ProtectionChanged):
    """Ownership changed during exit preflight; no POST was attempted."""


class Base(DeclarativeBase):
    pass


class Protection(Base):
    __tablename__ = 'delta_profit_protection'
    user = Column(String(80), primary_key=True)
    symbol = Column(String(60), primary_key=True)
    enabled = Column(Boolean, nullable=False, default=False, index=True)
    body = Column(Text, nullable=False, default='{}')


class Repository:
    def __init__(self, engine):
        self.engine = engine
        Base.metadata.create_all(engine)

    def get(self, user, symbol):
        with Session(self.engine) as session:
            row = session.get(Protection, (user, symbol))
            return json.loads(row.body) if row else None

    def put(self, user, symbol, value):
        body = json.dumps(value, allow_nan=False)
        with Session(self.engine) as session:
            row = session.get(Protection, (user, symbol))
            if row is None:
                row = Protection(user=user, symbol=symbol)
                session.add(row)
            row.enabled, row.body = bool(value.get('enabled') or value.get('exit_intent')), body
            session.commit()

    def list(self, user=None, active=False):
        with Session(self.engine) as session:
            query = select(Protection)
            if user is not None:
                query = query.where(Protection.user == user)
            if active:
                query = query.where(Protection.enabled.is_(True))
            return [(r.user, r.symbol, json.loads(r.body)) for r in session.scalars(query.limit(100))]


def public(plan):
    return {k: v for k, v in plan.items() if k not in ('account', 'user')}


class Manager:
    def __init__(self, repository, gateway, clock=time.time):
        self.repo, self.g, self.clock = repository, gateway, clock

    def preview(self, user, symbol, config):
        p = self.g.prepare(user, symbol)
        rr = float(config.get('reward_multiple', 3))
        initial = float(config.get('initial_stop') or p['stop'])
        risk = p['side'] * (p['entry'] - initial)
        gap = float(config.get('gap') or risk / 2)
        if rr not in (1.5, 2, 3, 4, 5, 6) or not all(math.isfinite(v) for v in (initial, risk, gap)) or min(initial, risk, gap) <= 0 or gap < p['tick']:
            raise ProtectionError('Choose an original stop on the loss side, a valid reward multiple, and a gap of at least one tick')
        target = p['entry'] + p['side'] * risk * rr
        target = float((Decimal(str(target)) / Decimal(str(p['tick']))).to_integral_value(
            rounding=ROUND_CEILING if p['side'] > 0 else ROUND_FLOOR) * Decimal(str(p['tick'])))
        if target <= 0:
            raise ProtectionError('This risk/reward target is not a valid positive price')
        p.update(initial_stop=initial, target=target, gap=gap, reward_multiple=rr, symbol=symbol)
        mode = config.get('trailing_mode', 'price')
        if mode not in ('price', 'net_usd'):
            raise ProtectionError('Choose a supported trailing policy')
        p['trailing_mode'] = mode
        if mode == 'net_usd':
            arm, lock, cash_gap = [float(config.get(k, default)) for k, default in
                (('profit_arm_usd', 2), ('profit_lock_usd', 1.5), ('profit_gap_usd', .5))]
            if not all(math.isfinite(x) for x in (arm, lock, cash_gap)) or not 0 < lock < arm or not 0 < cash_gap <= arm-lock+1e-8:
                raise ProtectionError('Net-profit activation must exceed the lock; choose a positive trailing gap')
            p.update(profit_arm_usd=arm, profit_lock_usd=lock, profit_gap_usd=cash_gap,
                     peak_net_usd=0, profit_armed=False, protected_net_usd=0)
        fields = ('symbol', 'account', 'quantity', 'entry', 'opened_at', 'stop_id', 'stop',
                  'initial_stop', 'target', 'gap', 'reward_multiple', 'tick', 'units',
                  'opening_cost', 'exit_rate', 'eligible', 'exit_at', 'window_end')
        fields += ('trailing_mode',)
        if mode == 'net_usd':
            fields += ('profit_arm_usd', 'profit_lock_usd', 'profit_gap_usd', 'funding')
        p['preview_id'] = hashlib.sha256(json.dumps({k:p[k] for k in fields}, sort_keys=True).encode()).hexdigest()
        return p

    def enable(self, user, symbol, config, expected):
        with locks.hold(symbol, 'CRYPTO', user) as held:
            if not held:
                raise ProtectionError('Protection is busy; refresh before trying again')
            old = self.repo.get(user, symbol)
            if old and (old.get('enabled') or (old.get('exit_intent') and old.get('state') != 'closed')):
                raise ProtectionError('Existing protection or exit must be reconciled before starting another plan')
            if hasattr(self.repo, 'list') and len(self.repo.list(active=True)) >= 10:
                raise ProtectionError('At most ten profit-protection plans may be active')
            p = self.preview(user, symbol, config)
            if p['preview_id'] != expected:
                raise ProtectionError('Position, stop or settings changed; review a fresh preview')
            p.update(enabled=True, state='watching', message='Waiting for a fresh server check',
                     enabled_at=self.clock(), checked_at=0, remaining_quantity=abs(p['quantity']))
            self.repo.put(user, symbol, p)
            return p

    def disable(self, user, symbol):
        with locks.hold(symbol, 'CRYPTO', user) as held:
            if not held:
                raise ProtectionError('Protection is busy; refresh before trying again')
            p = self.repo.get(user, symbol)
            if p:
                p.update(enabled=False, state='exit_pending' if p.get('exit_intent') else 'paused',
                         message='Automation paused; pending exits still reconcile; broker orders remain')
                self.repo.put(user, symbol, p)
            return p

    def poll(self, user, symbol):
        with locks.hold(symbol, 'CRYPTO', user) as held:
            if not held:
                return
            p = self.repo.get(user, symbol)
            if not p or not (p.get('enabled') or p.get('exit_intent')):
                return
            try:
                o = self.g.reconcile(user, p) if p.get('exit_intent') else self.g.load(user, p)
                now = self.clock()
                if not 0 <= now - o['asof'] <= 5:
                    raise ProtectionError('Broker snapshot is stale; protection was not changed')
                p['checked_at'] = now
                if o.get('account') != p.get('account'):
                    raise ProtectionChanged('Account changed; review broker orders before restarting')
                if p.get('exit_intent'):
                    outcome = self.g.exit_status(user, p)
                    p.update(state='exit_pending', message='Exit submitted; awaiting terminal broker confirmation')
                    if outcome.get('state') in ('cancelled', 'rejected', 'closed', 'filled'):
                        p['last_exit'] = {**p.pop('exit_intent'), 'outcome':outcome.get('state')}
                        if not o['quantity']:
                            p.update(enabled=False, state='closed', message='Exit reconciled and broker confirms the position is flat')
                        else:
                            p.update(enabled=False, state='paused', message='Exit reconciled with a remaining position; review broker protection before restarting')
                elif not o['quantity']:
                    p.update(enabled=False, state='closed', message='Broker confirms the position is flat')
                elif (any(o.get(k) != p.get(k) for k in ('account', 'entry', 'opened_at'))
                      or o['quantity'] * p['quantity'] <= 0 or abs(o['quantity']) > abs(p['quantity'])
                      or o.get('added') or not o.get('order_open')):
                    p.update(enabled=False, state='paused', message='Position or broker protection changed; review before restarting')
                else:
                    sign = p['side']
                    observed_stop = float(o['stop'])
                    p['stop'] = max(p['stop'], observed_stop) if sign > 0 else min(p['stop'], observed_stop)
                    p.update(units=o['units'], opening_cost=o['opening_cost'], funding=o.get('funding', 0),
                             remaining_quantity=abs(o['quantity']), price=o['price'], exit_rate=o['exit_rate'])
                    if p.get('eligible') and o.get('eligible'):
                        p['window_end'] = min(p['window_end'], o['window_end'])
                        p['exit_at'] = min(p['exit_at'], o['exit_at'])
                    p['eligible'] = bool(p.get('eligible') and o.get('eligible'))
                    result = evaluate(p, o['price'], now, eligible=o['eligible'] and p.get('eligible', True))
                    p.update(estimated_net=result['net'], state='watching', message=result['reason'].replace('_', ' '))
                    for key in ('peak_net_usd', 'profit_armed', 'protected_net_usd', 'conservative_net_usd'):
                        if key in result:
                            p[key] = result[key]
                    if result['action'] == 'exit':
                        # The durable identity precedes the only POST. Unknown outcomes
                        # are reconciled, including after a restart; never blindly retried.
                        p['exit_intent'] = dict(client_id='pg-' + uuid.uuid4().hex[:27], reason=result['reason'])
                        p.update(state='exit_pending', message='Exit submission in progress; broker stop retained')
                        self.repo.put(user, symbol, p)
                        oid = self.g.close(user, p, p['exit_intent']['client_id'])
                        p['exit_intent']['order_id'] = oid
                    else:
                        desired = result['stop']
                        if sign * (desired-observed_stop) > 0 and sign * (o['price']-desired) >= p['tick']:
                            # Commit the earned cash peak before any broker I/O:
                            # a process death must not erase an unacknowledged floor.
                            if p.get('trailing_mode') == 'net_usd':
                                self.repo.put(user, symbol, p)
                            acknowledged = self.g.tighten(user, p, desired)
                            if sign * (acknowledged-desired) < -p['tick']/100:
                                raise ProtectionError('Broker did not confirm the requested protective stop')
                            p['stop'] = acknowledged
                            p['message'] = 'Profit protection tightened; pullbacks cannot loosen it'
                self.repo.put(user, symbol, p)
            except UnsentProtectionChanged as exc:
                p.pop('exit_intent', None)
                p.update(enabled=False, state='paused', message=str(exc))
                self.repo.put(user, symbol, p)
            except ProtectionChanged as exc:
                p.update(enabled=False, state='paused', message=str(exc))
                self.repo.put(user, symbol, p)
            except NotSubmitted as exc:
                p.pop('exit_intent', None)
                p.update(state='watching', message=str(exc))
                self.repo.put(user, symbol, p)
            except Exception as exc:
                p.update(state='exit_pending' if p.get('exit_intent') else 'error',
                         message=str(exc) if isinstance(exc, ProtectionError) else
                         'Protection could not be updated. Verify broker orders; no duplicate exit will be sent')
                self.repo.put(user, symbol, p)


_repo = None
_repo_lock = threading.Lock()
last_cycle = 0.0


def repository():
    global _repo
    with _repo_lock:
        if _repo is None:
            from database.engine_factory import create_db_engine
            _repo = Repository(create_db_engine())
    return _repo


def manager():
    from services.delta_profit_gateway import Gateway
    return Manager(repository(), Gateway())


def poll_active():
    global last_cycle
    try:
        service = manager()
        for user, symbol, _ in service.repo.list(active=True):
            service.poll(user, symbol)
        last_cycle = time.time()
    finally:
        from utils.db_sessions import remove_all_scoped_sessions
        remove_all_scoped_sessions()


def start():
    repository()
    from services.strategy_module.scheduler import start as start_scheduler
    scheduler = start_scheduler()
    scheduler.add_job(poll_active, 'interval', seconds=1, id='delta-profit-protection',
                      replace_existing=True, max_instances=1, coalesce=True, misfire_grace_time=5)
