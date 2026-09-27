"""Offline account replay of the frozen, screened opportunity pool. No orders/DB writes."""
import hashlib
import json
import os
import sys
from collections import Counter
from dataclasses import replace
from datetime import datetime, UTC
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ['LOG_FORMAT'] = '%(levelname)s %(message)s'
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
import pandas as pd
from services.research.costs import order_cost
from services.research.replay import _slipped
from services.risk.budget import BudgetPolicy, BudgetTrade, budget_snapshot, evaluate_budget
from services.strategy_module.portfolio_governor import GovernorPolicy, EntryFacts, evaluate_entry
from services.strategy_module.scalping import trade_context, PROFILES

OUT = Path(__file__).parent
SOURCE = ROOT / 'data/research/hundred-trades-2026-09-27'
READY = SOURCE / 'ready'
D = lambda x: Decimal(str(x))
ZERO = D(0)
POLICY = BudgetPolicy(capital=D(25000))
GOVERNOR = replace(GovernorPolicy(), cash_risk_pct=D(1), option_risk_pct=D(1),
                   high_volatility_option_risk_pct=D(1), combined_risk_pct=D(1), daily_loss_pct=D(1))
CONTRACT = {'tick_size': .05}
COSTS = {'brokerage_per_order': 20, 'exchange_rate': .0003553, 'sebi_rate': .000001,
         'gst_rate': .18, 'stamp_buy_rate': .00003, 'stt_sell_rate': .0015}
SCENARIOS = {'normal': {'slippage_bps': 10, 'delay_protective': False},
             'stress': {'slippage_bps': 30, 'delay_protective': True}}
IDS = {'ema915': 13, 'macd200': 14, 'ema5': 15, 'regime50200': 16, 'box15': 17}


def read(p):
    return json.loads(p.read_text())


def write(p, x):
    p.write_text(json.dumps(x, indent=2, default=lambda x: float(x) if isinstance(x, Decimal) else str(x), allow_nan=False))


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def window(day, exchange):
    # All accepted opportunities are on observed regular-session NSE dates.
    start = pd.Timestamp(str(day) + ' 09:15', tz='Asia/Kolkata')
    return {'start_ms': int(start.timestamp()*1000), 'end_ms': int((start+pd.Timedelta(minutes=375)).timestamp()*1000)}


def stop_points(profile, quote, units):
    return D(10) if profile == 'box15' else (min(D(800)/units, quote*D('.2'))/D('.05')).to_integral_value(rounding=ROUND_DOWN)*D('.05')


def priced(raw, slip, buy=False):
    return D(_slipped(raw, slip, CONTRACT, buy=buy))


def load():
    verified = 0
    for name, expected in read(READY/'checksums.json').items():
        assert sha(READY/name) == expected, name
        verified += 1
    installed = {r['scalp_profile']: r for r in read(OUT/'installed-rules.json')}
    rows, paths, signals = [], {}, {}
    for profile in PROFILES:
        # Deliberately discard previously computed outcome/P&L columns.
        for r in read(READY/profile/'trades.json'):
            rows.append({k: v for k,v in r.items() if k not in {'base', 'stress'}})
        f = pd.read_parquet(READY/profile/'option-paths.parquet')
        for ident, group in f.groupby('id'):
            paths[int(ident)] = {pd.Timestamp(r['bar_open']): r for r in group.to_dict('records')}
        f = pd.read_parquet(SOURCE/profile/'signals.parquet')
        signals[profile] = f.to_dict('index')
    signals['regime50200'].update(pd.read_parquet(SOURCE/'zenodo-regime-signals.parquet').to_dict('index'))
    minute = pd.concat([pd.read_parquet(READY/'NIFTY-clean-1m.parquet'),
                        pd.read_parquet(READY/'zenodo-nifty-close-labelled-1m.parquet')]).sort_index()
    minute.index -= pd.Timedelta(minutes=1)
    index = minute[['open','high','low','close']].to_dict('index')
    assert len({r['id'] for r in rows}) == len(rows)
    return rows, paths, signals, index, installed, verified


class Account:
    def __init__(self, scenario):
        self.costs = COSTS | {'slippage_bps': SCENARIOS[scenario]['slippage_bps']}
        self.slip = self.costs['slippage_bps']/10000
        self.delay = SCENARIOS[scenario]['delay_protective']
        self.cash = self.peak = POLICY.capital
        self.paused = False
        self.pause_at = None
        self.max_dd = ZERO
        self.max_dd_pct = ZERO
        self.closed = []
        self.trades = []
        self.curve = []
        self.skips = []
        self.busy_until = None
        self.unresolved = None

    def mark(self, at, pnl, row=None, bucket=None, planned=None, reason='mark'):
        ledger = list(self.closed)
        if row is not None:
            ledger.append(BudgetTrade(str(row['id']), row['day'], bucket, 'open', planned, pnl, True))
        eq = self.cash+pnl
        snapshot = budget_snapshot(POLICY, ledger, str(at.date()), eq, self.peak, self.paused)
        self.peak = snapshot['peak_equity']
        if snapshot['paused'] and not self.paused:
            self.pause_at = at.isoformat()
        self.paused = snapshot['paused']
        self.max_dd = max(self.max_dd, self.peak-eq)
        self.max_dd_pct = max(self.max_dd_pct, (self.peak-eq)/self.peak)
        self.curve.append({'timestamp': at.isoformat(), 'equity': eq, 'peak': self.peak,
                           'drawdown': self.peak-eq, 'reason': reason})
        return snapshot

    def admission(self, row, at, quote, points, context):
        units = row['lot_size']
        raw_debit = quote*units
        fee = order_cost(raw_debit, 'BUY', self.costs)
        planned = points*units + fee + order_cost(raw_debit, 'SELL', self.costs) + raw_debit*D(self.slip)*2
        today = [r for r in self.closed if r.session_day == row['day']]
        consecutive = 0
        for t in reversed(today):
            if t.net_pnl >= 0:
                break
            consecutive += 1
        facts = EntryFacts(mode='live', available_cash=self.cash, session_capital=POLICY.capital,
            open_cash_positions=0, open_nifty_option_positions=0, open_derivative_positions=0,
            entry_nifty_option_positions=1, entry_derivative_positions=1,
            entry_cash_risk=ZERO, entry_option_lot_risk=points*units, entry_risk=points*units,
            open_risk=ZERO, estimated_debit=raw_debit, minimum_reward_risk=D(2),
            reward_risk_basis='premium' if row['profile']=='box15' else 'underlying_index',
            session_pnl=sum((r.net_pnl for r in today),ZERO), consecutive_stopped_runs=consecutive,
            last_stopped_at=pd.Timestamp(self.trades[-1]['exit_at']).to_pydatetime() if today else None,
            has_option_entry=True, entry_exchanges=('NFO',))
        # Exercise production's pure governor without opening the application DB.
        with patch.dict(sys.modules, {'database.market_calendar_db': SimpleNamespace(get_effective_session_window=window)}):
            decision = evaluate_entry(facts, GOVERNOR, at.to_pydatetime())
        if not decision.allowed:
            return decision.code, None, planned
        decision = evaluate_budget(POLICY, self.closed, row['day'], self.cash, self.peak, planned, self.paused)
        if not decision.allowed:
            return decision.code, decision.bucket, planned
        entry = priced(quote, self.slip, True)
        debit = entry*units + order_cost(entry*units, 'BUY', self.costs)
        if debit > min(D(20000), self.cash*(1-POLICY.cash_buffer_pct)):
            return 'cash_buffer_or_premium_ceiling', decision.bucket, planned
        return None, decision.bucket, planned

    def trade(self, row, at, path, index, context, points, bucket, planned):
        units = row['lot_size']
        entry = priced(path[at]['open'], self.slip, True)
        entry_fee = order_cost(entry*units, 'BUY', self.costs)
        stop = entry-points
        target = entry+D(20) if row['profile']=='box15' else None
        deadline = at+pd.Timedelta(minutes=15)
        before, peak_before = self.cash, self.peak
        pending, triggered, ambiguity = None, None, False

        def net(raw):
            price = priced(raw, self.slip)
            return (price-entry)*units-entry_fee-order_cost(price*units,'SELL',self.costs)

        def close(raw, timestamp, why):
            price = priced(raw, self.slip)
            pnl = net(raw)
            self.mark(timestamp, pnl, row, bucket, planned, 'exit')
            self.cash += pnl
            self.closed.append(BudgetTrade(str(row['id']),row['day'],bucket,'closed',planned,pnl,True))
            self.busy_until = timestamp
            result = {'id': row['id'], 'profile': row['profile'], 'day': row['day'],
                'data_source': row['data_source'], 'entry_at': at.isoformat(), 'exit_at': timestamp.isoformat(),
                'entry_price': entry, 'exit_price': price, 'units': units, 'premium_stop': stop,
                'premium_target': target, 'context': context, 'bucket': bucket, 'planned_risk': planned,
                'entry_fee': entry_fee, 'exit_fee': order_cost(price*units,'SELL',self.costs),
                'gross_pnl': (price-entry)*units, 'net_pnl': pnl, 'cash_before': before,
                'cash_after': self.cash, 'peak_before': peak_before, 'peak_after': self.peak,
                'reason': why, 'triggered_at': triggered, 'ambiguous': ambiguity,
                'loss_over_bucket_limit': pnl < -D(1000), 'paused_after': self.paused}
            self.trades.append(result)
            return result

        for stamp in pd.date_range(at, deadline, freq='min'):
            bar = path.get(stamp)
            if bar is None or not bar['volume'] > 0:
                self.unresolved = {'id': row['id'], 'timestamp': stamp.isoformat(), 'reason': 'missing_or_zero_volume_option_bar_after_entry'}
                return None
            o,h,l,c = [D(bar[k]) for k in ['open','high','low','close']]
            if not ZERO < l <= min(o,c) <= max(o,c) <= h:
                raise ValueError('invalid option candle')
            if pending:
                return close(o, stamp, pending)
            if stamp == deadline:
                return close(o, stamp, 'time')
            snapshot = self.mark(stamp, net(o), row, bucket, planned, 'open')
            if snapshot['paused'] or bucket in snapshot['exit_buckets']:
                return close(o, stamp, 'account_guard_gap')
            if o <= stop:
                return close(o, stamp, 'premium_stop_gap')
            if target and o >= target:
                return close(o, stamp, 'premium_target_gap')
            ib = index.get(stamp) if row['profile'] != 'box15' else None
            if row['profile'] != 'box15' and ib is None:
                self.unresolved = {'id': row['id'], 'timestamp': stamp.isoformat(), 'reason': 'missing_index_bar_after_entry'}
                return None
            sign = 1 if row['direction']=='CE' else -1
            if ib and stamp != at:
                if sign*(ib['open']-context['stop']) <= 0:
                    return close(o, stamp, 'index_stop_gap')
                if sign*(ib['open']-context['target']) >= 0:
                    return close(o, stamp, 'index_target_gap')
            # Use account loss/peak limits to find a fee-inclusive raw-price barrier.
            base = budget_snapshot(POLICY,self.closed,row['day'],self.cash,self.peak,self.paused)
            max_loss = min(base[f'{bucket}_remaining'],base['daily_remaining'])
            min_net = max(-max_loss, self.peak*(1-POLICY.drawdown_pct)-self.cash)
            boundary = ZERO
            if net(l) <= min_net:
                lo,hi = l,o
                for _ in range(32):
                    mid = (lo+hi)/2
                    if net(mid) <= min_net:
                        lo=mid
                    else:
                        hi=mid
                boundary=hi
            effective_stop = max(stop,boundary)
            premium_loss = l <= effective_stop
            index_loss = bool(ib and sign*((ib['low'] if sign==1 else ib['high'])-context['stop']) <= 0)
            index_win = bool(ib and sign*((ib['high'] if sign==1 else ib['low'])-context['target']) >= 0)
            premium_win = bool(target and h >= target)
            ambiguity |= (premium_loss or index_loss) and (premium_win or index_win)
            reason = ('account_guard' if boundary > stop else 'premium_stop') if premium_loss else (
                'index_stop' if index_loss else ('premium_target' if premium_win else ('index_target' if index_win else None)))
            if reason:
                triggered = stamp.isoformat()
                # Underlying and option OHLC do not reveal synchronized tick prices.
                # Always fill index-triggered exits at the next option minute OPEN.
                if self.delay or reason.startswith('index'):
                    pending = reason
                    self.mark(stamp+pd.Timedelta(seconds=59),net(l),row,bucket,planned,'adverse_mark_before_delayed_exit')
                    self.mark(stamp+pd.Timedelta(minutes=1),net(c),row,bucket,planned,'close_before_delayed_exit')
                    continue
                return close(effective_stop if premium_loss else target, stamp+pd.Timedelta(minutes=1),reason)
            self.mark(stamp+pd.Timedelta(minutes=1),net(c),row,bucket,planned,'close')
        raise AssertionError('A resolved trade must close by deadline')

    def summary(self, opportunities):
        pnls = [r['net_pnl'] for r in self.trades]
        gains = sum((max(ZERO,p) for p in pnls),ZERO)
        losses = sum((max(ZERO,-p) for p in pnls),ZERO)
        daily = {}
        for t in self.trades:
            daily[t['day']] = daily.get(t['day'],ZERO)+t['net_pnl']
        return {'opportunities': opportunities, 'trades': len(pnls), 'wins': sum(p>0 for p in pnls),
            'win_rate': sum(p>0 for p in pnls)/len(pnls) if pnls else None,
            'net_pnl': self.cash-POLICY.capital, 'ending_cash': self.cash,
            'return_pct': (self.cash/POLICY.capital-1)*100,
            'profit_factor': gains/losses if losses else None,
            'max_drawdown': self.max_dd, 'max_drawdown_pct': self.max_dd_pct*100,
            'paused': self.paused, 'pause_at': self.pause_at, 'unresolved': self.unresolved,
            'worst_trade': min(pnls) if pnls else None, 'worst_day': min(daily.values()) if daily else None,
            'first_trade': self.trades[0]['entry_at'] if pnls else None,
            'last_trade': self.trades[-1]['entry_at'] if pnls else None,
            'losses_over_1000': sum(p < -1000 for p in pnls),
            'skips': dict(Counter(r['reason'] for r in self.skips)),
            'exits': dict(Counter(r['reason'] for r in self.trades)),
            'ambiguous': sum(r['ambiguous'] for r in self.trades)}


def replay(rows,paths,signals,index,installed,scenario,profiles,first,last):
    account=Account(scenario)
    candidates=sorted((r for r in rows if r['profile'] in profiles and first<=r['day']<=last),
                      key=lambda r:(r['timestamp'],IDS[r['profile']]))
    for row in candidates:
        at=pd.Timestamp(row['timestamp'])
        code=None
        if account.unresolved:
            code='account_unresolved'
        elif account.paused:
            code='portfolio_paused'
        elif account.busy_until and at < account.busy_until:
            code='one_nifty_position_limit'
        elif at.strftime('%H:%M:%S') < installed[row['profile']]['entry_time'][:8]:
            code='strategy_entry_window'
        elif at not in paths[row['id']]:
            code='missing_entry_bar'
        if code:
            account.skips.append({'id':row['id'],'timestamp':row['timestamp'],'reason':code})
            continue
        signal=signals[row['profile']][at] | {'timestamp':at.isoformat()}
        try:
            context=trade_context(row['profile'],signal,None if row['profile']=='box15' else index[at]['open'])
        except (KeyError,ValueError):
            account.skips.append({'id':row['id'],'timestamp':row['timestamp'],'reason':'invalid_index_entry'})
            continue
        quote=D(paths[row['id']][at]['open'])
        points=stop_points(row['profile'],quote,row['lot_size'])
        if points<=0 or points>=quote or quote*row['lot_size']>20000:
            code,bucket,planned='invalid_premium_or_ceiling',None,ZERO
        else:
            code,bucket,planned=account.admission(row,at,quote,points,context)
        if code:
            account.skips.append({'id':row['id'],'timestamp':row['timestamp'],'reason':code})
        else:
            account.trade(row,at,paths[row['id']],index,context,points,bucket,planned)
    return account,account.summary(len(candidates))


def main():
    assert not (OUT/'results.json').exists(), 'Preserve previous completed results'
    rows,paths,signals,index,installed,verified=load()
    windows={'full_modern':('2021-06-01','2026-07-02'),
             'recent_2025_2026':('2025-01-01','2026-07-02')}
    windows.update({f'year_{y}':(f'{y}-01-01',min(f'{y}-12-31','2026-07-02')) for y in range(2021,2027)})
    protocol={'registered_at':datetime.now(UTC).isoformat(), 'capital':25000,
        'first_trade_loss_limit':1000,'later_trades_combined_loss_limit':1000,'daily_loss_limit':2000,
        'drawdown_pause_pct':20,'automatic_resume':False,'cash_buffer_pct':20,
        'one_nifty_position':True,'whole_historical_lot':True,'premium_ceiling':20000,
        'max_hold_minutes':15,'costs':COSTS,'scenarios':SCENARIOS,'windows':windows,
        'combined_same_time_priority':'ascending installed strategy ID (13,14,15,16,17)',
        'data_scope':'Prepared screened opportunity pool; missing/previously unaffordable paths excluded upstream. Not a complete causal replay of every market signal.',
        'earlier_pool_limits':'At most three candidates/day/profile; original no-overlap candidate screen retained. Not outcome-optimized.',
        'execution':'Entry at option minute open after signal closes; index OHLC exits next option minute open. Normal premium exits at adverse slipped barriers; stress all intraminute exits next minute open. Stop first on ambiguity.',
        'marks':'Liquidation equity at observed opens/closes; stress pending exits also use adverse bar low; no favorable intrabar high used to inflate peak.',
        'not_modeled':['native bid/ask spread gate','queue priority','partial/rejected fills','network outages','exact sub-minute polling phase','commercial data rights','live release approval'],
        'cost_status':'Hypothetical uniform current-style cost scenarios, not historical contract-note charges; brokerage plan not verified.',
        'shared_budget_functions':'services.risk.budget production code',
        'governor':'production evaluate_entry with enabled managed-budget policy; regular NFO session adapter',
        'verified_bundle_files':verified,
        'source_hashes':{n:sha(ROOT/n) for n in ['services/risk/budget.py','services/research/costs.py','services/strategy_module/scalping.py','services/strategy_module/portfolio_governor.py',str(Path(__file__).relative_to(ROOT))]},
        'installed_rules_sha256':sha(OUT/'installed-rules.json'), 'forward_holdout':False}
    write(OUT/'protocol.json',protocol)
    summaries={}
    for name,(first,last) in windows.items():
        summaries[name]={}
        for scenario in SCENARIOS:
            summaries[name][scenario]={}
            for profile in [*PROFILES,'combined']:
                ps=list(PROFILES) if profile=='combined' else [profile]
                account,summary=replay(rows,paths,signals,index,installed,scenario,ps,first,last)
                summaries[name][scenario][profile]=summary
                folder=OUT/name/scenario/profile
                folder.mkdir(parents=True,exist_ok=True)
                write(folder/'trades.json',account.trades)
                write(folder/'skips.json',account.skips)
                write(folder/'equity.json',account.curve)
                write(folder/'summary.json',summary)
            print(name,scenario,{p:(r['trades'],round(float(r['net_pnl']),2),r['paused'],r['unresolved']) for p,r in summaries[name][scenario].items()},flush=True)
    summaries['older_regime_only']={}
    for scenario in SCENARIOS:
        account,summary=replay(rows,paths,signals,index,installed,scenario,['regime50200'],'2017-01-01','2020-12-31')
        summaries['older_regime_only'][scenario]={'regime50200':summary}
        folder=OUT/'older_regime_only'/scenario/'regime50200'
        folder.mkdir(parents=True,exist_ok=True)
        write(folder/'trades.json',account.trades);write(folder/'skips.json',account.skips);write(folder/'equity.json',account.curve);write(folder/'summary.json',summary)
    write(OUT/'results.json',summaries)


if __name__=='__main__':
    main()
