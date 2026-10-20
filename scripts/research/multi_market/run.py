"""Run the fixed 600-candidate protocol. Run from the repository root:

LOG_FORMAT='%(message)s' uv run python -m scripts.research.multi_market.run
The outputs are research artifacts; this script has no broker execution path.
"""

from dataclasses import asdict
import hashlib
import json
import logging
from pathlib import Path

import pandas as pd

from .data import snapshot, resample_complete, IST
from .engine import (
    candidates,
    features,
    signal_series,
    simulate,
    summarize,
    choose_development,
    factor_at_least,
)

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "workspace/backtests/multi-market-20261017"
LOG = logging.getLogger("multi_market_research")


def split_dates(d):
    dates = sorted(d.day.unique())
    n = len(dates)
    one = max(1, int(n * 0.6))
    two = max(one + 1, int(n * 0.8))
    return {"development": dates[:one], "validation": dates[one:two], "test": dates[two:]}


def qualified(metrics, stress, sessions):
    return (
        sessions >= 60
        and metrics["trades"] >= 100
        and metrics["win_rate"] >= 0.8
        and metrics["expectancy"] > 0
        and factor_at_least(metrics, 1.2)
        and metrics["unresolved"] == 0
        and stress["unresolved"] == 0
        and stress["net"] > 0
    )


def run():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    OUT.mkdir(parents=True, exist_ok=True)
    if (OUT / "data/coverage.json").exists():
        coverage = json.loads((OUT / "data/coverage.json").read_text())
        data = {s: pd.read_parquet(OUT / "data" / f"{s}.parquet") for s in coverage}
        for s in coverage:
            assert (
                hashlib.sha256((OUT / "data" / f"{s}.parquet").read_bytes()).hexdigest()
                == coverage[s]["sha256"]
            )
    else:
        data, coverage = snapshot(ROOT, OUT / "data")
    search = candidates()
    by_id = {c.id: c for c in search}
    result = {
        "protocol_version": "chart-combinations-v1",
        "configurations_per_market": len(search),
        "coverage": coverage,
        "markets": {},
        "sources": sources(),
        "limitations": limitations(),
    }
    result["code_sha256"] = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in Path(__file__).parent.glob("*.py")
    }
    for symbol, d in data.items():
        LOG.info("%s: preparing %s minute candles", symbol, len(d))
        indian = symbol != "BTCUSD"
        d["day"] = (
            pd.to_datetime(d.time, unit="s", utc=True).dt.tz_convert(IST).dt.strftime("%Y-%m-%d")
        )
        split = split_dates(d)
        subsets = {k: d[d.day.isin(days)].reset_index(drop=True) for k, days in split.items()}
        sigs = {}
        for tf in [5, 15]:
            b = features(resample_complete(d, tf, indian), indian)
            for family in ["pullback", "retest", "range", "sweep", "regime"]:
                for selective in [False, True]:
                    sides = signal_series(b, family, selective, indian)
                    s = b.loc[sides != 0, ["time", "end", "atr"]].copy()
                    s["side"] = sides[sides != 0]
                    s["day"] = (
                        pd.to_datetime(s.end, unit="s", utc=True)
                        .dt.tz_convert(IST)
                        .dt.strftime("%Y-%m-%d")
                    )
                    sigs[(tf, family, selective)] = s

        def evaluate(c, period, stress=False):
            s = sigs[(c.timeframe, c.family, c.selective)]
            s = s[s.day.isin(split[period])]
            kwargs = (
                {"slippage": 2.0 if indian else 0.0002, "fee_rate": 0 if indian else 0.00118}
                if stress
                else {}
            )
            trades = simulate(subsets[period], s, c, indian, **kwargs)
            return summarize(trades), trades

        leaderboard = []
        for count, c in enumerate(search, 1):
            summary, _ = evaluate(c, "development")
            leaderboard.append(dict(id=c.id, **asdict(c), **summary))
            if count % 100 == 0:
                LOG.info("%s: %s/%s development candidates complete", symbol, count, len(search))
        pd.DataFrame(leaderboard).to_csv(OUT / f"{symbol}-development.csv", index=False)
        shortlist = choose_development(leaderboard)
        diagnostic = not bool(shortlist)
        if diagnostic:
            # Clearly failed fallback, selected only on the development period.
            usable = [r for r in leaderboard if r["trades"] >= 5] or leaderboard
            shortlist = sorted(
                usable, key=lambda r: (r["expectancy_r"], r["trades"]), reverse=True
            )[:1]
        validation = []
        for row in shortlist:
            m, _ = evaluate(by_id[row["id"]], "validation")
            validation.append(dict(id=row["id"], **m))
        passing = [
            r
            for r in validation
            if r["trades"] >= 15
            and r["expectancy"] > 0
            and factor_at_least(r, 1.1)
            and r["unresolved"] == 0
        ]
        if not passing:
            diagnostic = True
        chosen = max(
            passing or validation,
            key=lambda r: (r["win_rate"] if passing else r["expectancy_r"], r["trades"]),
        )
        c = by_id[chosen["id"]]
        # Persist the selection before evaluating the final period. The final
        # test is not used for parameter changes or selection.
        frozen = {
            "candidate": asdict(c),
            "id": c.id,
            "diagnostic_only": diagnostic,
            "validation": validation,
            "split": split,
        }
        (OUT / f"{symbol}-selection.json").write_text(json.dumps(frozen, indent=2))
        metrics, final_trades = evaluate(c, "test")
        stress, _ = evaluate(c, "test", True)
        development = next(r for r in leaderboard if r["id"] == c.id)
        pd.DataFrame(final_trades).to_csv(OUT / f"{symbol}-final-trades.csv", index=False)
        # One named strategy plus a full signal export for later premium-data replay.
        chosen_signals = sigs[(c.timeframe, c.family, c.selective)].copy()
        chosen_signals.to_csv(OUT / f"{symbol}-chosen-signals.csv", index=False)
        result["markets"][symbol] = dict(
            candidate=asdict(c),
            id=c.id,
            diagnostic_only=diagnostic,
            unit="USD per 0.001 BTC" if not indian else "index points; not tradable option P&L",
            split={k: dict(first=v[0], last=v[-1], sessions=len(v)) for k, v in split.items()},
            development=development,
            validation=chosen,
            final=metrics,
            stress=stress,
            meets_research_screen=(
                not diagnostic and qualified(metrics, stress, len(d.day.unique()))
            ),
            development_above_80=sum(
                r["trades"] >= 30 and r["win_rate"] >= 0.8 for r in leaderboard
            ),
            top_development=sorted(
                leaderboard,
                key=lambda r: (r["win_rate"] if r["trades"] >= 30 else -1, r["expectancy"]),
                reverse=True,
            )[:10],
        )
        (OUT / "results.json").write_text(json.dumps(result, indent=2, allow_nan=False))
        LOG.info(
            "%s: frozen %s; final %s trades, %.1f%% wins, net %.3f",
            symbol,
            c.id,
            metrics["trades"],
            100 * metrics["win_rate"],
            metrics["net"],
        )
    from .options import diagnostic

    diagnostic(result, OUT)
    from .report import render

    render(result, OUT)
    LOG.info("Report saved: %s", OUT / "report.html")


def sources():
    return [
        [
            "Support/resistance and retests",
            "https://www.cmegroup.com/education/courses/technical-analysis/support-and-resistance",
        ],
        [
            "ATR volatility and stops",
            "https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/atr",
        ],
        [
            "ADX trend strength",
            "https://www.fidelity.com/viewpoints/active-investor/average-directional-index-ADX",
        ],
        [
            "RSI momentum and trend dependence",
            "https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/rsi",
        ],
        [
            "Bollinger: band tags alone are not signals",
            "https://www.bollingerbands.com/bollinger-band-rules",
        ],
        [
            "VWAP requires valid traded volume",
            "https://www.tradingview.com/support/solutions/43000502018-volume-weighted-average-price-vwap/",
        ],
        ["Backtest overfitting", "https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf"],
        ["Backtest assumptions and metrics", "https://www.freqtrade.io/en/stable/backtesting/"],
        ["Delta fees and GST", "https://www.delta.exchange/fees"],
    ]


def limitations():
    return [
        "80% is a research goal. Parameter search cannot promise future returns.",
        "600 fixed candidates per market; 60/20/20 chronological selection. Historical dates can overlap previous research, so this is not a pristine prospective holdout.",
        "Indian underlying results are directional index-point studies, not CE/PE premium returns. Index instruments cannot be traded directly.",
        "Base Indian study charges 1 index point slippage each side (stress: 2); no fictitious option taxes or premiums are applied to index points.",
        "BTC uses 0.001 BTC, 0.059% fees each side including assumed GST, 0.01% adverse slippage each side; stress doubles these. No fee promotions assumed.",
        "BTC funding is a disclosed reserve of 0.01% entry notional per crossed 00:00/08:00/16:00 UTC boundary, not historical booked funding. Actual funding can differ.",
        "No margin/liquidation model or live dollar-profit trailing guard is simulated. Larger size may change fills and costs.",
        "Missing-minute exposure is unresolved and blocks qualification; no forward-filled candles. Reported P&L sums resolved trades and must not conceal unresolved counts.",
        "Session dates are observed history, not an independently verified exchange holiday calendar. Indian normal weekday session 09:15–15:30 only; exits by 15:15.",
        "Trades crossing a period boundary close at that known boundary. Missing end-of-period minutes are unresolved, never force-filled at an earlier quote. Indicators reset on unexpected intraday gaps.",
        "Wilson intervals are descriptive and assume independent trades; serially correlated trades can make them overconfident. Drawdown is closed-trade drawdown, not intratrade equity drawdown.",
        "No FVG, order-book imbalance or smart-money identity is inferred from index zero-volume candles. Reversal labels describe observable price structure only.",
        "Extra BANKNIFTY/SENSEX retrieval failed: alternate history service unavailable; saved Kotak session did not return successful BANKNIFTY history and SENSEX request was rate-limited. Existing data retained.",
    ]


if __name__ == "__main__":
    run()
