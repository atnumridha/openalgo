#!/usr/bin/env python3
"""Frozen-signal, development-only risk comparison; no fit, broker or live DB work.

Run with the project's .venv Python. Re-running overwrites only this helper's
reports under --output. Immutable source inputs and earlier studies stay read-only.
"""

import argparse
import ast
from collections import Counter, defaultdict, deque
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_CEILING
import hashlib
import inspect
import json
import os
from pathlib import Path
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[3]
PRIMARY = Path('/Users/atanumridha/Documents/AlgoTrading/openalgo')
DATASETS = (3, 4, 5, 6, 7)
D = Decimal


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + '\n')


def prior_bar_atr(data, sessions, period=10):
    """SMA true range of 10 preceding complete minute bars; reset every session.

    A value at bar T excludes all of T's OHLC, even when called at T's close.
    Require 11 contiguous preceding bars to calculate ten true ranges. This
    deliberately conservative convention needs no intrabar high/low ordering.
    """
    histories = defaultdict(lambda: deque(maxlen=period + 1))
    result = {}
    minutes = data['metadata'].get('execution_bar_minutes', data['metadata']['bar_minutes'])
    interval = timedelta(minutes=minutes)
    underlying = data['metadata']['underlying_symbol']
    for row in sorted(data['rows'], key=lambda value: (value['timestamp'], value['symbol'])):
        at, symbol = row['timestamp'], row['symbol']
        if at[:10] not in sessions or symbol == underlying:
            continue
        history = histories[(at[:10], symbol)]
        if history and datetime.fromisoformat(at) - datetime.fromisoformat(history[-1]['timestamp']) != interval:
            history.clear()
        if len(history) == period + 1:
            ranges = [max(D(str(current['high'])) - D(str(current['low'])),
                          abs(D(str(current['high'])) - D(str(previous['close']))),
                          abs(D(str(current['low'])) - D(str(previous['close']))))
                      for previous, current in zip(history, list(history)[1:])]
            result[(symbol, at)] = sum(ranges, D('0')) / period
        history.append(row)
    return result


def verify_causal_atr():
    start = datetime.fromisoformat('2026-01-01T09:16:00+05:30')
    rows = [{'timestamp': (start + timedelta(minutes=i)).isoformat(), 'symbol': 'OPTION',
             'open': 100, 'high': 102, 'low': 99, 'close': 100}
            for i in range(12)]
    fixture = {'metadata': {'underlying_symbol': 'INDEX', 'bar_minutes': 1}, 'rows': rows}
    at = rows[-1]['timestamp']
    before = prior_bar_atr(fixture, {'2026-01-01'})[('OPTION', at)]
    rows[-1].update(high=10000, low=1, close=9000)
    after = prior_bar_atr(fixture, {'2026-01-01'})[('OPTION', at)]
    assert before == after == D('3'), 'ATR must exclude the current bar'
    assert ('OPTION', rows[10]['timestamp']) not in prior_bar_atr(fixture, {'2026-01-01'})


@contextmanager
def volatility_overlay(replay, atr_values, evaluate_position):
    """Process-local overlay: retain every v3 floor, additionally tighten to 2 ATR.

    The replay calls _liquidation_equity with its active contract before each
    profit_open evaluation. Capture only that contract and timestamp; ATR lookup
    uses strictly earlier bars. No price, fee, entry or policy calculation changes.
    """
    original_open = replay.profit_open
    original_equity = replay._liquidation_equity
    context = {}
    counts = Counter()
    touched = set()

    def capture(active, *args, **kwargs):
        context['symbol'] = active['contract']['symbol']
        context['at'] = active['last_bar_at']
        context['entry_at'] = active['entry_bar_at']
        return original_equity(active, *args, **kwargs)

    def tightened(risk, price, config):
        base_risk, base_decision = original_open(risk, price, config)
        if base_decision.breached:
            return base_risk, base_decision
        peak = D(str(base_risk.highest_price or base_risk.entry_price))
        gross_peak = (peak - D(str(base_risk.entry_price))) * D(str(base_risk.quantity))
        if gross_peak < 600:
            return base_risk, base_decision
        counts['evaluations_at_or_above_600'] += 1
        atr = atr_values.get((context.get('symbol'), context.get('at')))
        if atr is None:
            counts['evaluations_without_prior_atr'] += 1
            return base_risk, base_decision
        tick = D(config['tick_size'])
        candidate = ((peak - 2 * atr) / tick).to_integral_value(rounding=ROUND_CEILING) * tick
        candidate = min(peak, candidate)
        stop = max(D(str(base_risk.stop_price)), candidate)
        assert stop >= D(str(base_risk.stop_price)), 'Research overlay must never loosen a v3 floor'
        if stop == D(str(base_risk.stop_price)):
            return base_risk, base_decision
        counts['additional_tightenings'] += 1
        touched.add((context['symbol'], context['entry_at']))
        advanced = replace(base_risk, stop_price=float(stop), target_price=None, trailing_enabled=False)
        decision = evaluate_position(advanced, price)
        decision = replace(decision, stop_moved=advanced.stop_price != risk.effective_stop,
                           trail_armed=True)
        advanced = replace(advanced, highest_price=decision.highest_price)
        return advanced, decision

    replay._liquidation_equity = capture
    replay.profit_open = tightened
    try:
        yield counts, touched
    finally:
        replay._liquidation_equity = original_equity
        replay.profit_open = original_open


def source_files(function):
    tree = ast.parse(inspect.getsource(function))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'sources' for t in node.targets):
            return {relative: sha(ROOT / relative) for relative in ast.literal_eval(node.value)}
    raise RuntimeError('Cannot identify implementation fingerprint sources')


def audit_equity_trades(report):
    """Independent arithmetic checks of all-in admission and nonrefilling day loss."""
    equity = peak = D('25000')
    opening = {}
    losses = Counter()
    reduced = 0
    for trade in report['trades']:
        day = trade['completion_day']
        opening.setdefault(day, equity)
        cap = min(D('300'), equity * D('0.01'))
        if (peak - equity) / peak >= D('0.05'):
            cap *= D('0.5')
            reduced += 1
        assert D(str(trade['planned_risk'])) <= cap + D('0.000001'), 'All-in entry exceeds current equity cap'
        net = D(str(trade['net_pnl']))
        losses[day] += max(D('0'), -net)
        snapshot = trade['budget_after_close']
        assert D(str(snapshot['day_start_equity'])) == opening[day]
        allowance = min(D('2000'), opening[day] * D('0.03'))
        assert D(str(snapshot['daily_limit'])) == allowance
        assert abs(D(str(snapshot['daily_remaining'])) - max(D('0'), allowance - losses[day])) < D('0.000001')
        equity += net
        peak = D(str(snapshot['peak_equity']))
    return {'audited_admissions': len(report['trades']), 'reduced_risk_admissions': reduced,
            'all_in_caps_and_nonrefilling_daily_allowance_verified': True}


def aggregate(reports):
    trades = [trade for report in reports for trade in report['trades']]
    pnls = [D(str(trade['net_pnl'])) for trade in trades]
    skips = Counter()
    for report in reports:
        skips.update(report['rejections'])
    return {'trades': len(trades), 'wins': sum(value > 0 for value in pnls),
            'losses': sum(value < 0 for value in pnls), 'flat': sum(value == 0 for value in pnls),
            'win_rate_pct': round(100 * sum(value > 0 for value in pnls) / len(trades), 2) if trades else None,
            'net_pnl': str(sum(pnls, D('0')).quantize(D('0.01'))),
            'gross_pnl': str(sum((D(str(t['gross_pnl'])) for t in trades), D('0')).quantize(D('0.01'))),
            'costs': str(sum((D(str(t['costs'])) for t in trades), D('0')).quantize(D('0.01'))),
            'worst_independent_window_drawdown_pct': max(r['metrics']['max_drawdown_pct'] for r in reports),
            'paused_windows': sum(r['metrics']['drawdown_paused'] for r in reports),
            'incomplete_outcomes': sum(len(r['incomplete_outcomes']) for r in reports),
            'max_planned_risk': max((t['planned_risk'] for t in trades), default=None),
            'max_realized_trade_loss': str(max((max(D('0'), -value) for value in pnls), default=D('0'))),
            'skip_events': dict(sorted(skips.items()))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--primary', type=Path, default=PRIMARY)
    parser.add_argument('--output', type=Path, default=ROOT / 'data/research/risk-profit-comparison-2026-09-28')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(ROOT))
    import dotenv
    dotenv.load_dotenv = lambda *args, **kwargs: False
    dotenv.main.load_dotenv = dotenv.load_dotenv
    with tempfile.TemporaryDirectory(prefix='openalgo-risk-profit-') as scratch_name:
        scratch = Path(scratch_name)
        for key in ('DATABASE_URL', 'SANDBOX_DATABASE_URL', 'LOGS_DATABASE_URL', 'LATENCY_DATABASE_URL'):
            os.environ[key] = f'sqlite:///{scratch / (key + ".db")}'
        os.environ.update(API_KEY_PEPPER='isolated-research-fixture-pepper-00000000000000000000000000000000',
                          APP_KEY='isolated-research-only', FERNET_SALT='isolated-research-only-salt',
                          LOG_DIR=str(scratch / 'logs'), LOG_FORMAT='%(levelname)s %(message)s')
        from services.research import replay
        from services.research.jobs import implementation_hash
        from services.research.dataset import validate_dataset
        from services.risk.profit_exit import PROFIT_RECIPE, TECHNICAL_PROFIT_RECIPE
        from services.risk.position import evaluate_position
        verify_causal_atr()
        source_start = implementation_hash()
        files_start = source_files(implementation_hash)
        prior = args.primary / 'data/research/lowrisk-2026-09-28-fixed-study-v2'
        inputs = args.primary / 'data/research/lowrisk-2026-09-28-inputs'
        baseline_dir = args.primary / 'data/research/profit-trail-comparison-2026-09-28'
        input_manifest = json.loads((inputs / 'input-manifest.json').read_text())
        prior_manifest = json.loads((prior / 'manifest.json').read_text())
        baseline_manifest = json.loads((baseline_dir / 'manifest.json').read_text())
        protected = set(prior_manifest['protected_dates'])
        input_hashes = []
        for path in (inputs / 'input-manifest.json', prior / 'manifest.json', baseline_dir / 'manifest.json'):
            input_hashes.append({'path': str(path), 'sha256': sha(path)})
        results = []
        grouped = defaultdict(list)
        scopes = []
        for index in DATASETS:
            dataset_path = inputs / f'dataset-{index}.json'
            assert sha(dataset_path) == input_manifest[dataset_path.name]['sha256']
            data = validate_dataset(json.loads(dataset_path.read_text()))
            relative = f'dataset-{index}/hold-15/model.json'
            model_path = prior / relative
            assert sha(model_path) == prior_manifest['files'][relative]
            model = json.loads(model_path.read_text())['report']
            sessions = model['evaluated_sessions']
            assert not set(sessions) & protected, 'Protected sessions must not be evaluated'
            assert set(at[:10] for at in model['research_signals']).issubset(set(sessions))
            assert model['replay_configuration']['max_hold_minutes'] == 15
            assert model['replay_configuration']['pacing']['cooldown_minutes'] == 5
            input_hashes.extend({'path': str(path), 'sha256': sha(path)} for path in (dataset_path, model_path))
            scopes.append({'dataset': index, 'sessions': sessions,
                           'frozen_signal_count': len(model['research_signals']),
                           'signal_hash': model['replay_configuration']['research_signal_hash'],
                           'model_hash': model['replay_configuration']['research_model_hash']})
            atr_values = prior_bar_atr(data, set(sessions))
            for variant in ('old-profit-v2', 'technical-v3', 'technical-v3-tight-2atr'):
                config = dict(model['replay_configuration'])
                config.update(risk_recipe=PROFIT_RECIPE if variant == 'old-profit-v2' else TECHNICAL_PROFIT_RECIPE,
                              risk_policy_version='shared-300-3r-v1' if variant == 'old-profit-v2' else 'equity-1pct-v2',
                              engine_version=replay.ENGINE_VERSION, implementation_hash=source_start)
                for stress in (False, True):
                    label = 'stress' if stress else 'base'
                    extra = {}
                    if variant == 'technical-v3-tight-2atr':
                        with volatility_overlay(replay, atr_values, evaluate_position) as (counts, touched):
                            report = replay.run_replay(data, config, sessions, stress=stress,
                                                       research_signals=model['research_signals'])
                        extra = dict(counts, trades_with_additional_tightening=len(touched))
                    else:
                        report = replay.run_replay(data, config, sessions, stress=stress,
                                                   research_signals=model['research_signals'])
                    assert not report['incomplete_outcomes'], 'Do not aggregate incomplete outcomes as complete P&L'
                    if variant == 'old-profit-v2':
                        saved_path = baseline_dir / f'dataset-{index}-trailing-{label}.json'
                        assert sha(saved_path) == baseline_manifest['files'][saved_path.name]
                        saved = json.loads(saved_path.read_text())['report']
                        keys = ('symbol', 'entry_bar_at', 'entry_price', 'exit_at', 'exit_price', 'net_pnl')
                        identity = lambda value: [tuple(t[key] for key in keys) for t in value['trades']]
                        assert identity(report) == identity(saved), f'Legacy baseline differs: dataset {index} {label}'
                        input_hashes.append({'path': str(saved_path), 'sha256': sha(saved_path)})
                    risk_audit = audit_equity_trades(report) if variant != 'old-profit-v2' else None
                    name = f'dataset-{index}-{variant}-{label}.json'
                    write_json(args.output / name, {'configuration': config, 'sessions': sessions,
                               'stress': stress, 'variant': variant, 'research_overlay': extra,
                               'risk_audit': risk_audit, 'report': report})
                    grouped[(variant, label)].append(report)
                    row = {'dataset': index, 'variant': variant, 'scenario': label, 'file': name,
                           'metrics': report['metrics'], 'rejections': report['rejections'],
                           'research_overlay': extra}
                    results.append(row)
                    print(json.dumps({key: row[key] for key in ('dataset', 'variant', 'scenario', 'metrics')}), flush=True)
        aggregates = {f'{variant}/{scenario}': aggregate(reports)
                      for (variant, scenario), reports in grouped.items()}
        assert aggregates['old-profit-v2/base']['trades'] == 380
        assert aggregates['old-profit-v2/base']['net_pnl'] == '-16955.74'
        assert aggregates['old-profit-v2/stress']['trades'] == 287
        assert aggregates['old-profit-v2/stress']['net_pnl'] == '-21670.78'
        for item in input_hashes:
            assert sha(Path(item['path'])) == item['sha256'], 'An immutable source input changed during the study'
        source_end = implementation_hash()
        files_end = source_files(implementation_hash)
        changed = sorted(path for path in files_start if files_start[path] != files_end[path])
        source_changed = bool(changed) or source_start != source_end
        notes = [
            'Same frozen prior ML signals, fixed contracts, holds and cooldown; no refit, threshold or parameter search.',
            'Five independent capital windows of INR25000; aggregate net is not one continuous account return.',
            'Full immutable dataset files are hashed and structurally validated; replay and ATR calculations only use listed development sessions. Protected final sessions are not evaluated.',
            'Historical candles cannot establish executable bid/ask depth, latency, spread or actual fills; these results do not qualify production deployment.',
            'Base fees reuse the saved user-approved retrospective Kotak cost assumption; stress doubles slippage bps plus 10 and multiplies brokerage by 1.5, as in run_replay.',
            'ATR overlay is research-only: simple mean of ten true ranges from eleven contiguous preceding option minute bars, reset by session; current-bar high/low/close excluded even at close.',
            'ATR overlay activates only after observed-open/close gross peak reaches INR600; stop is max(v3 stop, tick-ceiling(observed peak minus 2ATR)). It never widens stops or weakens INR1000-to-INR900 floor.',
            'An open/close observation already below a newly tightened stop exits at that observation; previously established stops use replay gap/low stop-first handling. No high-before-low ordering is assumed.',
            'ATR overlay only monkeypatches standalone-process replay functions; it is not a production recipe or configuration option.',
            'Rejection counts are replay decision events, not a full partition of frozen signals: signals while a position is active are not separately classified.',
            'Tighter admission and different exits can change subsequent admissions through cash, drawdown and cooldown; comparisons share signals but need not share executed trades.',
        ]
        manifest = {'status': 'rerun_required_source_changed' if source_changed else 'exploratory_comparison_complete',
                    'source_hash_start': source_start, 'source_hash_end': source_end,
                    'source_changed': source_changed, 'changed_source_files': changed,
                    'source_files_start': files_start, 'source_files_end': files_end,
                    'helper': {'path': str(Path(__file__).resolve()), 'sha256': sha(Path(__file__))},
                    'engine_version': replay.ENGINE_VERSION,
                    'capital_per_window': 25000, 'holding_minutes': 15, 'cooldown_minutes': 5,
                    'protected_dates': sorted(protected), 'development_scopes': scopes,
                    'input_files': input_hashes, 'notes': notes, 'aggregates': aggregates, 'results': results,
                    'files': {row['file']: sha(args.output / row['file']) for row in results}}
        write_json(args.output / 'manifest.json', manifest)
        lines = ['# Frozen-signal risk and profit comparison', '',
                 f"Status: {manifest['status']}. Source start `{source_start}`, end `{source_end}`.", '',
                 '| Variant | Fees | Trades | Wins | Win rate | Net P&L (INR) | Worst window drawdown |',
                 '|---|---|---:|---:|---:|---:|---:|']
        for key, result in aggregates.items():
            variant, scenario = key.split('/')
            lines.append(f"| {variant} | {scenario} | {result['trades']} | {result['wins']} | {result['win_rate_pct']}% | {result['net_pnl']} | {result['worst_independent_window_drawdown_pct']}% |")
        lines += ['', 'These are independent development windows, not a continuous portfolio or evidence of live executable profitability.', '',
                  'The old baseline matches every saved entry/exit identity and net result. All report and input hashes are in `manifest.json`.', '',
                  '## Method and limits', ''] + ['- ' + note for note in notes]
        overlay_events = sum(r['research_overlay'].get('evaluations_at_or_above_600', 0)
                             for r in results if r['variant'] == 'technical-v3-tight-2atr')
        lines += ['', '## Interpretation', '',
                  'The new technical policy remains loss-making in both fee scenarios. Smaller losses coincide with far fewer admitted trades and do not establish a better predictive edge.',
                  'Stress can change entry prices, stops, and subsequent drawdown/cooldown admission; a lower aggregate stress loss does not mean higher costs improve the same trades.',
                  f'The volatility overlay had {overlay_events} observations eligible to activate at INR600 gross profit.']
        if overlay_events == 0:
            lines += ['It never activated. Identical volatility-variant results provide no comparative evidence about that trail or the advanced INR1000-to-INR900 profit floor. No production promotion is supported.']
        lines += ['', '## Rejection events', '']
        for key, result in aggregates.items():
            lines += [f"- {key}: `{json.dumps(result['skip_events'], sort_keys=True)}`"]
        (args.output / 'README.md').write_text('\n'.join(lines) + '\n')
        print(json.dumps({'status': manifest['status'], 'aggregates': aggregates}, sort_keys=True), flush=True)


if __name__ == '__main__':
    main()
