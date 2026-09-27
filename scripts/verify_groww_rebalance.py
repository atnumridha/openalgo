"""Reconcile the four inclusion trades independently from archived public responses."""

import argparse
import csv
import hashlib
import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]


def load(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    folder = parser.parse_args().folder.resolve()
    m = load(folder / "registered-experiment.json")
    assert sha(ROOT / "scripts/research_groww_rebalance.py") == m["runner_sha256"]
    assert sha(ROOT / "docs/plans/2026-09-27-groww-algorithmic-ranking.md") == m["plan_sha256"]
    receipts = load(folder / "receipts.json")
    for r in receipts:
        assert sha(folder / r["file"]) == r["sha256"]
    report = load(folder / "results.json")
    benchmark = ROOT / "data/research/yahoo/NIFTY-1d-full-history.csv"
    assert sha(benchmark) == report["benchmark_sha256"]
    with benchmark.open() as stream:
        daily = {r["timestamp"][:10]: r for r in csv.DictReader(stream)}
    assert len(report["trades"]) == 4
    expected_symbols = {s for e in m["events"] for s in e["symbols"]}
    assert {r["symbol"] for r in report["trades"]} == expected_symbols
    for trade in report["trades"]:
        event = next(e for e in m["events"] if trade["symbol"] in e["symbols"])
        assert trade["entry_date"] == event["entry"] and trade["exit_date"] == event["exit"]
        benchmark_return = (
            Decimal(daily[event["exit"]]["Close"]) / Decimal(daily[event["entry"]]["Open"]) - 1
        )
        assert abs(float(benchmark_return) - trade["benchmark_return"]) < 1e-10
        source = load(folder / f"{trade['symbol']}.json")["chart"]["result"][0]
        dates = [
            datetime.fromtimestamp(t, ZoneInfo("Asia/Kolkata")).date().isoformat()
            for t in source["timestamp"]
        ]
        q = source["indicators"]["quote"][0]
        entry = Decimal(str(q["open"][dates.index(event["entry"])]))
        exit_px = Decimal(str(q["close"][dates.index(event["exit"])]))
        assert not source.get("events", {}), (
            "These four bounded downloads must have no corporate actions"
        )
        shares = int(Decimal("10000") / entry)
        assert trade["shares"] == shares
        assert trade["entry"] == float(entry) and trade["exit"] == float(exit_px)
        gross = (exit_px - entry) * shares
        assert abs(float(gross) - trade["gross_pnl"]) < 1e-8
        for bps in (30, 60):
            net = gross - (entry + exit_px) * shares * Decimal(bps) / 20000
            assert abs(float(net) - trade[f"net_{bps}bps"]) < 1e-8
    for c in report["campaigns"]:
        rows = [t for t in report["trades"] if t["announcement"] == c["announcement"]]
        assert c["trades"] == len(rows) == 2
        for k in ("entry_notional", "gross_pnl", "net_30bps", "net_60bps"):
            assert abs(c[k] - sum(t[k] for t in rows)) < 1e-8
    result = {
        "verified_trades": 4,
        "verified_campaigns": 2,
        "source_hashes_verified": len(receipts),
        "verifier_sha256": sha(Path(__file__)),
        "profitability_proven": False,
    }
    (folder / "verification.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
