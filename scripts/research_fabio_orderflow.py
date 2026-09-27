"""Audit whether the supplied Fabio order-flow model can be tested from saved data.

This standalone research audit has no application, broker, credential or order imports.
It does not generate a candle proxy, signals, trades, or market-return statistics.
"""

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from zipfile import ZipFile

import duckdb

ROOT = Path(__file__).resolve().parents[1]
FIRST, LAST = "2025-01-01", "2026-04-23"
DATA = ROOT / "data/research/five-minute-2026-09-26"
SOURCE = ROOT / "data/research/ema-scalp-2026-09-26-source"
TRANSCRIPT = Path(
    "/Users/atanumridha/.codex/attachments/542969f6-dcac-4c10-91ba-7f26e823aeca/Pasted text.txt"
)


def read_json(path):
    with path.open() as stream:
        return json.load(stream)


def write_json(path, value):
    with path.open("w") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def seconds(value):
    hour, minute, second = map(int, value.split(":"))
    return hour * 3600 + minute * 60 + second


def transcript_audit(path):
    with path.open() as stream:
        text = stream.read()
    spans = re.findall(r"^\* (\d\d:\d\d:\d\d) - (\d\d:\d\d:\d\d) (.*)$", text, re.M)
    quoted = [(seconds(a), seconds(b)) for a, b, line in spans if line.startswith('"')]
    covered, previous, gaps = 0, 0, []
    for start, end in sorted(quoted):
        if start > previous:
            gaps.append({"start_seconds": previous, "end_seconds": start})
        covered += max(0, end - max(previous, start))
        previous = max(previous, end)
    return {
        "timestamped_segments": len(spans),
        "quoted_segments": len(quoted),
        "placeholder_segments": len(spans) - len(quoted),
        "last_timestamp_seconds": previous,
        "quoted_coverage_seconds": covered,
        "coverage_is_timestamp_claim_not_verified_video_transcription": True,
        "longest_unquoted_gaps": sorted(
            gaps, key=lambda g: g["end_seconds"] - g["start_seconds"], reverse=True
        )[:5],
    }


def broker_audit(paths):
    """Inspect all candle schemas and only permitted-date volume observations."""
    widths, volumes, days, count = Counter(), Counter(), set(), 0
    providers, intervals = set(), set()
    for path in paths:
        payload = read_json(path)
        providers.add(payload["source"])
        intervals.add(str(payload["interval"]))
        for row in payload["raw_candles"]:
            widths[len(row)] += 1
            if len(row) not in (6, 7):
                raise ValueError(f"Unrecognized candle shape: {path}")
            day = str(row[0])[:10]
            if not FIRST <= day <= LAST:
                continue
            count += 1
            days.add(day)
            volume = row[5]
            volumes["null" if volume is None else "zero" if volume == 0 else "nonzero"] += 1
    return {
        "files": len(paths),
        "source": sorted(providers),
        "interval": sorted(intervals),
        "raw_row_width_counts_all_input_files": dict(widths),
        "columns": ["timestamp", "open", "high", "low", "close", "source_volume", "optional_oi"],
        "permitted_raw_rows": count,
        "permitted_observed_sessions": len(days),
        "first_day": min(days),
        "last_day": max(days),
        "source_volume_counts": dict(volumes),
        "raw_rows_not_price_screened": True,
        "trade_size_or_aggressor_fields": False,
        "volume_at_price_fields": False,
    }


def parquet_schema(db, path):
    return {
        row[0]: row[1]
        for row in db.execute("DESCRIBE SELECT * FROM read_parquet(?)", [str(path)]).fetchall()
    }


def aggregate(db, query, params):
    cursor = db.execute(query, params)
    return dict(zip([c[0] for c in cursor.description], cursor.fetchone(), strict=True))


def nonidentifiability_example():
    """Constructive proof only: synthetic tapes, never historical market returns."""
    prices = [100, 101, 99, 100.5]
    tapes = [
        list(zip(prices, [10, 80, 5, 5], [1, 1, -1, 1], strict=True)),
        list(zip(prices, [10, 5, 80, 5], [-1, -1, -1, 1], strict=True)),
    ]
    observations = []
    for tape in tapes:
        profile = Counter()
        for price, size, _side in tape:
            profile[price] += size
        observations.append(
            {
                "synthetic_ticks_price_size_aggressor_sign": tape,
                "ohlcv": [prices[0], max(prices), min(prices), prices[-1], sum(profile.values())],
                "volume_at_price": dict(profile),
                "point_of_control": max(profile, key=profile.get),
                "signed_volume_delta": sum(size * side for _price, size, side in tape),
                "signed_volume_from_trades_at_least_20": sum(
                    size * side for _price, size, side in tape if size >= 20
                ),
            }
        )
    assert observations[0]["ohlcv"] == observations[1]["ohlcv"]
    assert observations[0]["point_of_control"] != observations[1]["point_of_control"]
    assert observations[0]["signed_volume_delta"] == -observations[1]["signed_volume_delta"]
    assert observations[0]["signed_volume_from_trades_at_least_20"] == 80
    assert observations[1]["signed_volume_from_trades_at_least_20"] == -80
    return observations


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    broker_paths = {
        "nifty_1m": sorted(SOURCE.glob("NIFTY-1m-*.json")),
        "banknifty_5m": sorted(SOURCE.glob("BANKNIFTY-5m-*.json")),
    }
    option_paths = [DATA / "public-options/raw" / f"NIFTY_{year}.parquet" for year in (2025, 2026)]
    spot_path = DATA / "NIFTY-spot-5m.parquet"
    inputs = [spot_path, *option_paths, *(p for paths in broker_paths.values() for p in paths)]
    manifest = {
        "purpose": "Data identifiability audit, not an accuracy backtest",
        "first": FIRST,
        "last": LAST,
        "protected_outcome_rows_used": 0,
        "comparison_assumptions": {
            "capital_inr": 25000,
            "cash_buffer_fraction": 0.2,
            "one_itm_lot": True,
            "index_reward_multiple": 2,
            "maximum_hold_minutes": 15,
        },
        "source_sha256": sha256(Path(__file__)),
        "transcript_sha256": sha256(TRANSCRIPT),
        "input_sha256": {str(p.relative_to(ROOT)): sha256(p) for p in inputs},
        "duckdb_version": duckdb.__version__,
        "forbidden_substitutes": [
            "OHLC spread uniformly across price as a true volume profile",
            "candle colour as observed aggressor direction",
            "minute total volume as a single large trade",
            "options open interest as aggressor buying or selling",
        ],
    }
    # Freeze scope and inputs before any statistical query. File hashing inspects bytes,
    # not protected-period price outcomes. All row queries below have a date predicate.
    write_json(out / "registered-audit.json", manifest)
    audit = {key: broker_audit(paths) for key, paths in broker_paths.items()}
    with duckdb.connect() as db:
        db.execute("SET memory_limit='256MB'")
        db.execute("SET threads=2")
        db.execute("SET TimeZone='Asia/Kolkata'")
        audit["nifty_5m"] = {
            "schema": parquet_schema(db, spot_path),
            **aggregate(
                db,
                """SELECT count(*) AS row_count, count(DISTINCT CAST(bar_start AS DATE)) sessions,
                CAST(min(CAST(bar_start AS DATE)) AS VARCHAR) first_day,
                CAST(max(CAST(bar_start AS DATE)) AS VARCHAR) last_day,
                count(*) FILTER (WHERE volume IS NULL) volume_null,
                count(*) FILTER (WHERE source_volume=0) source_volume_zero
                FROM read_parquet(?) WHERE CAST(bar_start AS DATE) BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)""",
                [str(spot_path), FIRST, LAST],
            ),
        }
        audit["options_1m"] = []
        for path in option_paths:
            audit["options_1m"].append(
                {
                    "path": str(path.relative_to(ROOT)),
                    "schema": parquet_schema(db, path),
                    **aggregate(
                        db,
                        """SELECT count(*) AS row_count, count(DISTINCT date) sessions,
                        min(date) first_day, max(date) last_day,
                        count(*) FILTER (WHERE volume=0) volume_zero,
                        count(*) FILTER (WHERE volume>0) volume_positive,
                        count(*) FILTER (WHERE volume<0) volume_negative,
                        count(*) FILTER (WHERE volume IS NULL) volume_null,
                        list(DISTINCT underlying) underlyings,
                        list(DISTINCT source) sources, list(DISTINCT granularity) granularities
                        FROM read_parquet(?) WHERE date BETWEEN ? AND ?""",
                        [str(path), FIRST, LAST],
                    ),
                }
            )
    older_archive = ROOT / "data/research/zenodo-10899828/Nifty spot and futures data.zip"
    with ZipFile(older_archive) as archive:
        audit["older_futures_archive_members"] = archive.namelist()
    audit["scope_note"] = (
        "Designated broker/index/option sources plus filenames of older futures archive; not a claim about every possible vendor or local database."
    )
    write_json(out / "data-audit.json", audit)
    write_json(out / "transcript-audit.json", transcript_audit(TRANSCRIPT))
    write_json(out / "synthetic-nonidentifiability.json", nonidentifiability_example())
    write_json(
        out / "results.json",
        {
            "status": "not_measurable_from_audited_inputs",
            "eligible_evaluable_trades": 0,
            "positive_index_wins": None,
            "full_2r_target_hits": None,
            "index_win_rate": None,
            "base_option_positive_returns": None,
            "stress_option_positive_returns": None,
            "base_option_pnl": None,
            "stress_option_pnl": None,
            "protected_outcome_rows_used": 0,
            "proxy_test_run": False,
            "live_qualified": False,
            "reason": "No tick volume-at-price, aggressor trade-size observations or complete deterministic rule specification. Zero evaluable trades means unavailable, not a zero percent win rate.",
        },
    )


if __name__ == "__main__":
    main()
