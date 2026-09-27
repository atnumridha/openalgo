"""Bounded, public-data Nifty inclusion event study; no trading integration."""

import argparse
import hashlib
import json
import math
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from curl_cffi import requests

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "docs/plans/2026-09-27-groww-algorithmic-ranking.md"
EVENTS = [
    {
        "announcement": "2025-02-21",
        "entry": "2025-02-24",
        "exit": "2025-03-27",
        "symbols": ["JIOFIN.NS", "ETERNAL.NS"],
        "notice": "https://www.niftyindices.com/Press_Release/ind_prs21022025.pdf",
        "symbol_note": "ETERNAL is the current Yahoo symbol for announcement name ZOMATO.",
    },
    {
        "announcement": "2025-08-22",
        "entry": "2025-08-25",
        "exit": "2025-09-29",
        "symbols": ["INDIGO.NS", "MAXHEALTH.NS"],
        "notice": "https://nsearchives.nseindia.com/web/pressrelease/2025-08/ind_prs22082025_20250822194818.pdf",
    },
]


def fingerprint(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False, default=str))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    out = parser.parse_args().output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    save(
        out / "registered-experiment.json",
        {
            "registered_at": datetime.now(UTC).isoformat(),
            "events": EVENTS,
            "plan_sha256": fingerprint(PLAN),
            "runner_sha256": fingerprint(Path(__file__)),
            "capital_per_campaign": 25000,
            "gross_funding_per_stock": 10000,
            "roundtrip_cost_scenarios_bps": [30, 60],
            "not_scalping": True,
            "not_portfolio_risk_qualified": True,
        },
    )
    benchmark = pd.read_csv(ROOT / "data/research/yahoo/NIFTY-1d-full-history.csv")
    benchmark["day"] = benchmark.timestamp.str[:10]
    benchmark = benchmark.set_index("day")
    rows, receipts = [], []
    with requests.Session(impersonate="chrome") as session:
        for event in EVENTS:
            response = session.get(event["notice"], timeout=30)
            response.raise_for_status()
            assert response.content.startswith(b"%PDF"), "Official notice did not return PDF"
            notice = out / f"notice-{event['announcement']}.pdf"
            notice.write_bytes(response.content)
            receipts.append(
                {"url": event["notice"], "file": notice.name, "sha256": fingerprint(notice)}
            )
            for symbol in event["symbols"]:
                params = {
                    "period1": int(
                        pd.Timestamp(event["announcement"], tz="Asia/Kolkata").timestamp()
                    ),
                    "period2": int(
                        (
                            pd.Timestamp(event["exit"], tz="Asia/Kolkata") + pd.Timedelta(days=1)
                        ).timestamp()
                    ),
                    "interval": "1d",
                    "events": "div,splits",
                }
                url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
                response = session.get(url, params=params, timeout=30)
                response.raise_for_status()
                data = response.json()
                raw = out / f"{symbol}.json"
                save(raw, data)
                receipts.append(
                    {
                        "url": url,
                        "params": params,
                        "file": raw.name,
                        "sha256": fingerprint(raw),
                        "retrieved_at": datetime.now(UTC).isoformat(),
                    }
                )
                save(out / "receipts.json", receipts)
                result = data["chart"]["result"][0]
                q = result["indicators"]["quote"][0]
                frame = pd.DataFrame(
                    q,
                    index=pd.to_datetime(result["timestamp"], unit="s", utc=True).tz_convert(
                        "Asia/Kolkata"
                    ),
                )
                frame.index = frame.index.strftime("%Y-%m-%d")
                assert frame.index.is_unique
                assert event["entry"] in frame.index and event["exit"] in frame.index
                path = frame.loc[event["entry"] : event["exit"]]
                assert path[["open", "high", "low", "close"]].notna().all().all()
                assert path[["open", "high", "low", "close"]].gt(0).all().all()
                assert path.low.le(path[["open", "close"]].min(axis=1)).all()
                assert path.high.ge(path[["open", "close"]].max(axis=1)).all()
                actions = result.get("events", {})
                assert not actions.get("splits"), (
                    "Split needs explicit adjustment; abort instead of mispricing"
                )
                dividend = sum(
                    float(a["amount"])
                    for a in actions.get("dividends", {}).values()
                    if event["entry"]
                    < pd.Timestamp(a["date"], unit="s", tz="UTC")
                    .tz_convert("Asia/Kolkata")
                    .strftime("%Y-%m-%d")
                    <= event["exit"]
                )
                entry, exit_price = float(path.iloc[0].open), float(path.iloc[-1].close)
                shares = math.floor(10000 / entry)
                assert shares > 0
                gross = shares * (exit_price - entry + dividend)
                row = {
                    "announcement": event["announcement"],
                    "symbol": symbol,
                    "entry_date": event["entry"],
                    "exit_date": event["exit"],
                    "sessions": len(path),
                    "entry": entry,
                    "exit": exit_price,
                    "shares": shares,
                    "entry_notional": shares * entry,
                    "dividends_per_share": dividend,
                    "gross_pnl": gross,
                    "gross_return": (exit_price - entry + dividend) / entry,
                    "benchmark_return": float(
                        benchmark.loc[event["exit"], "Close"]
                        / benchmark.loc[event["entry"], "Open"]
                        - 1
                    ),
                }
                for bps in (30, 60):
                    cost = (entry + exit_price) * shares * bps / 20000
                    row[f"cost_{bps}bps"], row[f"net_{bps}bps"] = cost, gross - cost
                rows.append(row)
                print(symbol, round(row["net_30bps"], 2), round(row["net_60bps"], 2), flush=True)
    campaigns = []
    for event in EVENTS:
        group = [r for r in rows if r["announcement"] == event["announcement"]]
        campaigns.append(
            {
                "announcement": event["announcement"],
                "trades": len(group),
                **{
                    k: sum(r[k] for r in group)
                    for k in ("entry_notional", "gross_pnl", "net_30bps", "net_60bps")
                },
            }
        )
    save(
        out / "results.json",
        {
            "trades": rows,
            "campaigns": campaigns,
            "independent_campaigns": 2,
            "costs_are_illustrative_not_broker_quotes": True,
            "live_qualified": False,
            "benchmark_sha256": fingerprint(ROOT / "data/research/yahoo/NIFTY-1d-full-history.csv"),
        },
    )


if __name__ == "__main__":
    main()
