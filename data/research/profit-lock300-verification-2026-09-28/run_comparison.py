#!/usr/bin/env python3
"""Compare frozen v3/v4 exits on development sessions, without a fit or live DB."""

import argparse
from collections import Counter, defaultdict
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[3]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--primary', type=Path, default=Path('/Users/atanumridha/Documents/AlgoTrading/openalgo'))
    parser.add_argument('--output', type=Path, default=ROOT / 'data/research/profit-lock300-comparison-2026-09-28')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    sys.path.insert(0, str(ROOT))
    helper_path = ROOT / 'data/research/risk-profit-verification-2026-09-28/run_comparison.py'
    spec = importlib.util.spec_from_file_location('previous_comparison', helper_path)
    helpers = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helpers)
    import dotenv
    dotenv.load_dotenv = lambda *a, **k: False
    dotenv.main.load_dotenv = dotenv.load_dotenv
    with tempfile.TemporaryDirectory(prefix='openalgo-profit-lock-study-') as name:
        scratch = Path(name)
        for key in ('DATABASE_URL', 'SANDBOX_DATABASE_URL', 'LOGS_DATABASE_URL', 'LATENCY_DATABASE_URL'):
            os.environ[key] = f'sqlite:///{scratch / (key + ".db")}'
        os.environ.update(API_KEY_PEPPER='isolated-research-fixture-pepper-00000000000000000000000000000000',
                          APP_KEY='isolated-research-only', FERNET_SALT='isolated-research-only-salt',
                          LOG_DIR=str(scratch / 'logs'), LOG_FORMAT='%(levelname)s %(message)s')
        from services.research import replay
        from services.research.dataset import validate_dataset
        from services.research.jobs import implementation_hash
        from services.risk.profit_exit import PROFIT_LOCK_RECIPE, TECHNICAL_PROFIT_RECIPE
        source = implementation_hash()
        inputs = args.primary / 'data/research/lowrisk-2026-09-28-inputs'
        frozen = args.primary / 'data/research/lowrisk-2026-09-28-fixed-study-v2'
        previous = args.primary / 'data/research/risk-profit-comparison-2026-09-28'
        input_manifest = json.loads((inputs / 'input-manifest.json').read_text())
        frozen_manifest = json.loads((frozen / 'manifest.json').read_text())
        previous_manifest = json.loads((previous / 'manifest.json').read_text())
        protected = set(frozen_manifest['protected_dates'])
        hashes = {str(p): helpers.sha(p) for p in (inputs / 'input-manifest.json', frozen / 'manifest.json',
                  previous / 'manifest.json', helper_path, Path(__file__))}
        results, scopes = [], []
        grouped = defaultdict(list)
        for index in (3, 4, 5, 6, 7):
            path = inputs / f'dataset-{index}.json'
            hashes[str(path)] = helpers.sha(path)
            assert hashes[str(path)] == input_manifest[path.name]['sha256']
            data = validate_dataset(json.loads(path.read_text()))
            relative = f'dataset-{index}/hold-15/model.json'
            path = frozen / relative
            hashes[str(path)] = helpers.sha(path)
            assert hashes[str(path)] == frozen_manifest['files'][relative]
            model = json.loads(path.read_text())['report']
            sessions = model['evaluated_sessions']
            assert not set(sessions) & protected
            assert set(at[:10] for at in model['research_signals']).issubset(set(sessions))
            scopes.append({'dataset': index, 'sessions': sessions, 'signal_count': len(model['research_signals'])})
            for variant, recipe in (('technical-v3', TECHNICAL_PROFIT_RECIPE), ('profit-lock-v4', PROFIT_LOCK_RECIPE)):
                config = dict(model['replay_configuration'])
                assert config['max_hold_minutes'] == 15 and config['pacing']['cooldown_minutes'] == 5
                config.update(risk_recipe=recipe, risk_policy_version='equity-1pct-v2',
                              engine_version=replay.ENGINE_VERSION, implementation_hash=source)
                for stress in (False, True):
                    scenario = 'stress' if stress else 'base'
                    counts = Counter()
                    original = replay.profit_open

                    def observed(risk, price, profit_config):
                        updated, decision = original(risk, price, profit_config)
                        peak = helpers.D(str(updated.highest_price or updated.entry_price))
                        gross = (peak - helpers.D(str(updated.entry_price))) * helpers.D(str(updated.quantity))
                        if gross >= 300:
                            counts['observations_at_or_above_300'] += 1
                        if decision.stop_moved and updated.stop_price > updated.entry_price:
                            counts['profit_stop_advances'] += 1
                        return updated, decision

                    replay.profit_open = observed
                    try:
                        report = replay.run_replay(data, config, sessions, stress=stress,
                                                   research_signals=model['research_signals'])
                    finally:
                        replay.profit_open = original
                    assert not report['incomplete_outcomes']
                    if variant == 'technical-v3':
                        path = previous / f'dataset-{index}-technical-v3-{scenario}.json'
                        hashes[str(path)] = helpers.sha(path)
                        assert hashes[str(path)] == previous_manifest['files'][path.name]
                        saved = json.loads(path.read_text())['report']
                        keys = ('symbol', 'entry_bar_at', 'entry_price', 'exit_at', 'exit_price', 'net_pnl')
                        assert [[t[k] for k in keys] for t in report['trades']] == [[t[k] for k in keys] for t in saved['trades']]
                    filename = f'dataset-{index}-{variant}-{scenario}.json'
                    helpers.write_json(args.output / filename, dict(configuration=config, sessions=sessions,
                        variant=variant, scenario=scenario, observations=dict(counts),
                        risk_audit=helpers.audit_equity_trades(report), report=report))
                    grouped[(variant, scenario)].append(report)
                    row = dict(dataset=index, variant=variant, scenario=scenario, file=filename,
                               metrics=report['metrics'], observations=dict(counts))
                    results.append(row)
                    print(json.dumps(row), flush=True)
        assert source == implementation_hash(), 'Source changed during study'
        assert all(helpers.sha(Path(path)) == value for path, value in hashes.items())
        aggregates = {f'{variant}/{scenario}': helpers.aggregate(reports) for (variant, scenario), reports in grouped.items()}
        manifest = dict(status='exploratory_comparison_complete', source_hash=source,
                        engine_version=replay.ENGINE_VERSION, capital_per_window=25000,
                        holding_minutes=15, cooldown_minutes=5, protected_dates=sorted(protected),
                        scopes=scopes, input_hashes=hashes, results=results, aggregates=aggregates,
                        files={r['file']: helpers.sha(args.output / r['file']) for r in results},
                        notes=['Frozen prior ML signals; no refit, threshold search or final holdout replay.',
                               'Five independent capital windows, not a continuous account return.',
                               'Historical candles ratchet on observed open/close, not unordered highs; they cannot prove live bid depth, latency or fills.',
                               'Current Kotak costs reused as the user-approved retrospective research assumption. Stress doubles slippage bps plus 10 and multiplies brokerage by 1.5.',
                               'Old v3 exactly reproduces saved entry/exit identities and net P&L. Stops have no hard profit cap; all-in entry/day/drawdown gates are unchanged.',
                               'No production DB writes, broker requests or live eligibility promotion.'])
        helpers.write_json(args.output / 'manifest.json', manifest)
        lines = ['# Profit lock from INR300: frozen-signal comparison', '',
                 '| Recipe | Costs | Trades | Wins | Win rate | Net P&L (INR) | Worst window drawdown |',
                 '|---|---|---:|---:|---:|---:|---:|']
        for key, value in aggregates.items():
            variant, scenario = key.split('/')
            lines.append(f"| {variant} | {scenario} | {value['trades']} | {value['wins']} | {value['win_rate_pct']}% | {value['net_pnl']} | {value['worst_independent_window_drawdown_pct']}% |")
        lines += ['', *manifest['notes'], '', 'Profit amounts are gross before charges. The new floor is max(INR100, peak gross minus INR300), armed at INR300. Stop orders cannot guarantee that realized giveback stays within INR300.']
        (args.output / 'README.md').write_text('\n'.join(lines) + '\n')
        print(json.dumps({'aggregates': aggregates}), flush=True)


if __name__ == '__main__':
    main()
