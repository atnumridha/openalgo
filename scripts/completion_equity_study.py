"""Bounded, cache-verified US equity and Microsoft release research inputs.

The cached vendor documents are private research inputs. This module does not
put source payloads into Git or write any production database.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import re
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.request import urlopen
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from bs4 import BeautifulSoup, NavigableString

from services.research import conlan

NY = ZoneInfo("America/New_York")
SYMBOLS = ("AAPL", "MSFT", "AMZN", "GOOGL", "JPM", "XOM", "JNJ", "PG")
MAX_PRICE_BYTES = 2_000_000
MAX_RELEASE_BYTES = 1_500_000
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCES = ROOT / "data/research/completion-2026-09-27-sources"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def acquire_bounded(
    path: Path, manifest: dict, *, fetch=None, max_bytes=MAX_RELEASE_BYTES
) -> bytes:
    """Read verified cache, or fetch one allowlisted HTTPS URL without overwriting.

    A mismatch is fatal and never triggers a redownload. `fetch` permits offline
    fixture testing; its returned bytes receive the same size and hash checks.
    """
    path = Path(path)
    url = manifest["url"]
    parsed = urlparse(url)
    yahoo = (
        parsed.hostname == "query1.finance.yahoo.com"
        and re.fullmatch(r"/v8/finance/chart/[A-Z]+", parsed.path)
        and parse_qs(parsed.query) == {"interval": ["1d"], "range": ["10y"]}
    )
    microsoft = (
        parsed.hostname == "www.microsoft.com"
        and re.fullmatch(
            r"/en-us/Investor/earnings/FY-20\d{2}-Q[1-4]/press-release-webcast", parsed.path
        )
        and not parsed.query
    )
    if (
        parsed.scheme != "https"
        or not (yahoo or microsoft)
        or path.name != manifest.get("file", path.name)
    ):
        raise ValueError("Source URL or cache path is not permitted")
    if path.exists():
        with path.open("rb") as cached:
            data = cached.read(max_bytes + 1)
    else:
        if fetch is None:

            def fetch(source):
                with urlopen(source, timeout=15) as response:
                    if response.status != 200:
                        raise ValueError("Source HTTP status is not 200")
                    return response.read(max_bytes + 1)

        data = fetch(url)
    if len(data) > max_bytes:
        raise ValueError("Source exceeds bounded size")
    if sha256(data) != manifest["sha256"]:
        raise ValueError("Source hash mismatch")
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as target:
            target.write(data)
    return data


def _manifest(source_dir: Path, name: str) -> list[dict]:
    rows = json.loads((source_dir / name).read_text())
    if not isinstance(rows, list) or len({r["file"] for r in rows}) != len(rows):
        raise ValueError("Manifest must have unique files")
    return rows


def load_verified_prices(source_dir=DEFAULT_SOURCES, *, asof=None) -> pd.DataFrame:
    source_dir = Path(source_dir)
    cutoff = pd.Timestamp(asof or datetime.now(UTC))
    if cutoff.tz is None:
        raise ValueError("asof must be timezone-aware")
    prices = {}
    for row in _manifest(source_dir, "price-manifest.json"):
        symbol = row["file"].removeprefix("price-").removesuffix(".json")
        if symbol not in SYMBOLS or row["file"] != f"price-{symbol}.json":
            raise ValueError("Unexpected price symbol")
        raw = json.loads(acquire_bounded(source_dir / row["file"], row, max_bytes=MAX_PRICE_BYTES))
        chart = raw["chart"]["result"][0]
        if (
            chart["meta"]["symbol"] != symbol
            or chart["meta"]["currency"] != "USD"
            or chart["meta"]["instrumentType"] != "EQUITY"
            or chart["meta"]["exchangeTimezoneName"] != "America/New_York"
        ):
            raise ValueError("Price metadata mismatch")
        times = chart["timestamp"]
        values = chart["indicators"]["adjclose"][0]["adjclose"]
        if len(times) != len(values) or len(times) != row["observations"]:
            raise ValueError("Price observation count mismatch")
        # Chart timestamps mark sessions, not when that day's close was known.
        days = pd.to_datetime(times, unit="s", utc=True).tz_convert(NY).date
        index = pd.DatetimeIndex(
            [pd.Timestamp(day, tz=NY) + pd.Timedelta(hours=16) for day in days]
        )
        series = pd.Series(values, index=index, dtype=float)
        series = series[series.index <= cutoff.tz_convert(NY)]
        if (
            not series.index.is_unique
            or not series.index.is_monotonic_increasing
            or not series.map(lambda x: math.isfinite(x) and x > 0).all()
        ):
            raise ValueError("Invalid adjusted close series")
        prices[symbol] = series
    if set(prices) != set(SYMBOLS):
        raise ValueError("Incomplete price universe")
    result = pd.DataFrame(prices)[list(SYMBOLS)]
    if result.isna().any().any():
        raise ValueError("Misaligned or missing price sessions")
    return result


def _norm(value: str) -> str:
    return " ".join(value.split())


def _statement_units(table, table_text: str) -> set[str]:
    prefix = table_text.split("Three Months Ended", 1)[0]
    heading = re.search(r"\bINCOME\s+STATEMENTS\b", prefix, re.I)
    if heading:
        section = prefix[heading.start() :]
    else:
        # Some historical releases put the statement title and units in text
        # nodes immediately before the table. Stop at that title: an unrelated
        # earlier schedule must never supply units for this statement.
        preceding = []
        for element in table.previous_elements:
            if not isinstance(element, NavigableString):
                continue
            value = _norm(str(element))
            if not value:
                continue
            preceding.append(value)
            if re.search(r"\bINCOME\s+STATEMENTS\b", value, re.I):
                break
            if len(preceding) >= 20:
                return set()
        else:
            return set()
        section = " ".join(reversed(preceding)) + " " + prefix
    return {
        unit.lower()
        for unit in re.findall(r"\bIn\s+(millions|thousands|billions)\b", section, re.I)
    }


def _cells_with_positions(row) -> list[tuple[int, int, str]]:
    position = 0
    result = []
    for cell in row.find_all(["td", "th"], recursive=False):
        span = int(cell.get("colspan", 1))
        if span < 1 or span > 20:
            raise ValueError("Invalid financial table column span")
        result.append((position, position + span, _norm(cell.get_text(" ", strip=True))))
        position += span
    return result


def parse_msft_release(payload: bytes) -> dict:
    if len(payload) > MAX_RELEASE_BYTES:
        raise ValueError("Release exceeds bounded size")
    soup = BeautifulSoup(payload, "html.parser")
    text = _norm(soup.get_text(" ", strip=True))
    match = re.search(
        r"REDMOND,?\s+Wash\.?\s*[—–-]\s*([A-Z][a-z]+\s+\d{1,2},\s*\d{4})"
        r".{0,400}?quarter\s+ended\s+([A-Z][a-z]+\s+\d{1,2},\s*\d{4})",
        text,
        re.I,
    )
    if not match:
        raise ValueError("Missing publication or quarter end in release header")
    published = datetime.strptime(_norm(match.group(1)), "%B %d, %Y").date()
    period_end = datetime.strptime(_norm(match.group(2)), "%B %d, %Y").date()
    if published <= period_end:
        raise ValueError("Publication must follow period end")
    candidates = set()
    for table in soup.select("table"):
        table_text = _norm(table.get_text(" ", strip=True))
        if (
            "Three Months Ended" not in table_text
            or "Gross margin" not in table_text
            or "Cost of revenue" not in table_text
        ):
            continue
        quarter_heading = re.search(r"Three Months Ended\s+([A-Za-z]+)\s+(\d{1,2})", table_text)
        if not quarter_heading or (quarter_heading.group(1), int(quarter_heading.group(2))) != (
            period_end.strftime("%B"),
            period_end.day,
        ):
            continue
        if _statement_units(table, table_text) != {"millions"}:
            raise ValueError("Consolidated statement units must be unambiguously millions")
        rows = [_cells_with_positions(tr) for tr in table.select("tr")]
        quarter_header = next(
            (i for i, row in enumerate(rows) if any("Three Months Ended" in c[2] for c in row)),
            None,
        )
        if quarter_header is None:
            continue
        year_columns = []
        for row in rows[quarter_header + 1 : quarter_header + 4]:
            year_columns = [
                (start, int(year.group()))
                for start, _end, value in row
                if (year := re.fullmatch(r"(?:19|20)\d{2}", value))
            ]
            if len(year_columns) >= 2:
                break
        if len(year_columns) < 2 or year_columns[0][1] != period_end.year:
            continue
        if year_columns[1][1] != period_end.year - 1:
            raise ValueError("Unconfirmed previous-quarter comparison column")
        # A header may omit the leading label cell; revenue rows always have it.
        shift = 1 if year_columns[0][0] == 0 else 0
        current_start = year_columns[0][0] + shift
        previous_start = year_columns[1][0] + shift
        for row in rows:
            if row and row[0][2].lower() in {"revenue", "total revenue"}:
                if not any(value for _start, _end, value in row[1:]):
                    continue  # A section label, not a consolidated value row.
                current = [
                    value
                    for start, end, value in row[1:]
                    if current_start <= start < previous_start and end <= previous_start
                ]
                meaningful = [value for value in current if value not in {"", "$"}]
                if len(meaningful) != 1 or not (
                    number := re.fullmatch(r"\$?\s*([\d,]+)", meaningful[0])
                ):
                    raise ValueError("Missing or invalid current-quarter revenue column")
                candidates.add(int(number.group(1).replace(",", "")) * 1_000_000)
    if len(candidates) != 1:
        raise ValueError(f"Ambiguous consolidated current-quarter revenue: {sorted(candidates)}")
    available = datetime.combine(published + timedelta(days=1), datetime.min.time(), NY)
    return {
        "period_end": datetime.combine(period_end, datetime.min.time(), NY).isoformat(),
        "published_date": published.isoformat(),
        "available_at": available.isoformat(),
        "revenue": candidates.pop(),
        "currency": "USD",
        "unit": "USD",
    }


def load_verified_revenues(source_dir=DEFAULT_SOURCES) -> list[dict]:
    source_dir = Path(source_dir)
    result = []
    for row in _manifest(source_dir, "revenue-manifest.json"):
        if not re.fullmatch(r"MSFT-FY20\d{2}-Q[1-4]\.html", row["file"]):
            raise ValueError("Unexpected revenue source")
        fact = parse_msft_release(acquire_bounded(source_dir / row["file"], row))
        result.append(
            {
                **fact,
                "symbol": "MSFT",
                "source_file": row["file"],
                "source_url": row["url"],
                "source_sha256": row["sha256"],
                "retrieved_at": row["retrieved_at"],
            }
        )
    result.sort(key=lambda r: r["period_end"])
    if len({r["period_end"] for r in result}) != len(result):
        raise ValueError("Duplicate fiscal quarter")
    return result


def rule_asset_signals(closes: pd.DataFrame, family: str, *, band_window=20) -> pd.DataFrame:
    """Long-only daily stock interpretation of the original mathematical rules."""
    if family == "sma_macd":
        difference = closes.rolling(5).mean() - closes.rolling(34).mean()
        state = np.sign(difference)
        signals = state.where(state.ne(state.shift()), 0).fillna(0)
    elif family == "bollinger":
        if type(band_window) is not int or not 2 <= band_window <= 200:
            raise ValueError("Invalid Bollinger window")
        middle = closes.rolling(band_window).mean()
        deviation = closes.rolling(band_window).std(ddof=1)
        signals = pd.DataFrame(
            np.where(
                closes < middle - 2 * deviation, 1, np.where(closes > middle + 2 * deviation, -1, 0)
            ),
            index=closes.index,
            columns=closes.columns,
        )
    else:
        raise ValueError("Unknown stock rule family")
    return signals.astype(int)


def passive_equal_weight(closes: pd.DataFrame, *, fee_bps: float) -> dict:
    """Buy equal fractional USD stakes at first close, liquidate at final close."""
    if closes.empty or not 0 <= fee_bps < 10000:
        raise ValueError("Invalid passive benchmark input")
    fee = fee_bps / 10_000
    units = {
        symbol: 1 / len(closes.columns) / (float(closes.iloc[0][symbol]) * (1 + fee))
        for symbol in closes
    }
    curve = (closes * pd.Series(units)).sum(axis=1)
    curve.iloc[0] = 1.0
    curve.iloc[-1] *= 1 - fee
    trades = [
        {
            "symbol": symbol,
            "signal_at": closes.index[0].isoformat(),
            "entry_at": closes.index[0].isoformat(),
            "exit_at": closes.index[-1].isoformat(),
            "units": units[symbol],
            "cost": 1 / len(closes.columns),
            "net_pnl": units[symbol] * float(closes.iloc[-1][symbol]) * (1 - fee)
            - 1 / len(closes.columns),
        }
        for symbol in closes
    ]
    return {
        "metrics": conlan.equity_metrics(curve),
        "equity": [
            {"timestamp": at.isoformat(), "equity": float(value)} for at, value in curve.items()
        ],
        "trades": trades,
        "abstract_asset_simulation": True,
    }


def trade_cost_breakdown(trade: dict, closes: pd.DataFrame, *, fee_bps: float) -> dict:
    """Annotate a completed fractional trade with auditable two-sided costs."""
    symbol = trade["symbol"]
    entry = float(closes.loc[pd.Timestamp(trade["entry_at"]), symbol])
    exit_price = float(closes.loc[pd.Timestamp(trade["exit_at"]), symbol])
    units = float(trade["units"])
    fee = fee_bps / 10_000
    detail = {
        **trade,
        "entry_price": entry,
        "exit_price": exit_price,
        "gross_pnl": units * (exit_price - entry),
        "entry_fee": units * entry * fee,
        "exit_fee": units * exit_price * fee,
    }
    if not math.isclose(
        detail["net_pnl"],
        detail["gross_pnl"] - detail["entry_fee"] - detail["exit_fee"],
        abs_tol=1e-9,
    ):
        raise ValueError("Trade fee ledger does not reconcile")
    return detail


def _control_preferences(closes, base, *, kind, repeats, seed, window):
    rng = np.random.default_rng(seed)
    returns = closes.pct_change(fill_method=None)
    for repeat in range(repeats):
        if kind == "white_noise":
            preference = pd.DataFrame(
                rng.normal(size=closes.shape), index=closes.index, columns=closes.columns
            ).where(base.notna())
        else:
            preference = pd.DataFrame(np.nan, index=closes.index, columns=closes.columns)
            for symbol in closes:
                values = returns[symbol].to_numpy()
                windows = np.lib.stride_tricks.sliding_window_view(values, window)
                draw = rng.integers(0, window, size=windows.shape)
                samples = np.take_along_axis(windows, draw, axis=1)
                std = samples.std(axis=1, ddof=1)
                preference.loc[closes.index[window - 1 :], symbol] = np.divide(
                    samples.mean(axis=1), std, out=np.full(len(std), np.nan), where=std > 0
                )
        yield repeat, preference


def control_provenance(family: str, kind: str, *, repeat: int) -> dict:
    """Identify a draw's position in its one shared per-group RNG stream."""
    if family not in conlan.FAMILIES or kind not in {"white_noise", "bootstrap_preference"}:
        raise ValueError("Unknown control group")
    if type(repeat) is not int or repeat < 0:
        raise ValueError("Invalid control repeat position")
    return {
        "group_rng_seed": 42
        + (0 if family == "sma_macd" else 1000)
        + (0 if kind == "white_noise" else 100),
        "repeat_position": repeat,
        "rng_sequence": "shared_generator_advanced_across_repeats",
    }


def run_study(source_dir=DEFAULT_SOURCES, output_dir=None, *, control_repeats=100):
    """Run fixed studies; every portfolio candidate receives its full ledger."""
    source_dir = Path(source_dir)
    output_dir = Path(output_dir or ROOT / "data/research/completion-2026-09-27-study")
    output_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = output_dir / "all-candidate-ledgers.jsonl.gz"
    if ledger_path.exists():
        raise FileExistsError(f"Refusing to overwrite {ledger_path}")
    closes = load_verified_prices(source_dir)
    releases = load_verified_revenues(source_dir)
    revenue_frame = pd.DataFrame(releases)[["period_end", "available_at", "revenue"]]
    msft_model = conlan.alternative_data_study(
        closes.MSFT, revenue_frame, threshold=5.0, horizon="90D", seed=42
    )
    summary = {
        "source_count": len(releases),
        "price_rows": len(closes),
        "price_start": closes.index[0].isoformat(),
        "price_end": closes.index[-1].isoformat(),
        "source_provenance": {
            "price_manifest_sha256": sha256((source_dir / "price-manifest.json").read_bytes()),
            "revenue_manifest_sha256": sha256((source_dir / "revenue-manifest.json").read_bytes()),
            "price_sources": _manifest(source_dir, "price-manifest.json"),
            "revenue_sources": _manifest(source_dir, "revenue-manifest.json"),
        },
        "code_sha256": {
            "runner": sha256(Path(__file__).read_bytes()),
            "conlan": sha256(Path(conlan.__file__).read_bytes()),
        },
        "fixed_config": {
            "currency": "USD",
            "price_field": "adjusted_close",
            "observed_close_timezone": "America/New_York",
            "signal_fill": "next_observed_close",
            "release_available_at": "next_calendar_day_midnight_America/New_York",
            "rule_families": list(conlan.FAMILIES),
            "reference_sharpe_window": 100,
            "reference_max_positions": 3,
            "bollinger_window": 20,
            "fee_bps_per_side": {"gross": 0, "base": 10, "stress": 30},
            "control_repeats_per_type_per_family": control_repeats,
            "control_seed_base": 42,
            "grid_sharpe_windows": [50, 100, 150],
            "grid_max_positions": [1, 3, 5],
            "revenue_cusum_threshold": 5.0,
            "revenue_barrier_horizon": "90D",
            "model_seed": 42,
        },
        "msft_model": {k: v for k, v in msft_model.items() if k != "portfolio"},
        "candidate_metrics": [],
        "controls": {},
    }

    with (
        ledger_path.open("xb") as raw_output,
        gzip.GzipFile(fileobj=raw_output, mode="wb") as compressed,
    ):

        def record(name, family, scenario, result, *, control=None, config=None):
            fee_bps = {"gross": 0, "base": 10, "stress": 30}[scenario]
            row = {
                "name": name,
                "family": family,
                "scenario": scenario,
                "fee_bps_per_side": fee_bps,
                "control": control,
                "config": config,
                "metrics": result["metrics"],
                "trades": [
                    trade_cost_breakdown(t, closes, fee_bps=fee_bps) for t in result["trades"]
                ],
                "equity": result["equity"],
            }
            compressed.write(
                (json.dumps(row, separators=(",", ":"), allow_nan=False) + "\n").encode()
            )
            summary["candidate_metrics"].append(
                {
                    k: row[k]
                    for k in (
                        "name",
                        "family",
                        "scenario",
                        "fee_bps_per_side",
                        "control",
                        "config",
                        "metrics",
                    )
                }
            )

        for scenario, fee in [("gross", 0), ("base", 10), ("stress", 30)]:
            record(
                "passive_equal_weight",
                "benchmark",
                scenario,
                passive_equal_weight(closes, fee_bps=fee),
            )

        predictions = msft_model["predictions"]
        target = closes.MSFT.loc[pd.Timestamp(predictions[0]["timestamp"]) :].to_frame("MSFT")
        for scenario, fee in [("gross", 0), ("base", 10), ("stress", 30)]:
            record(
                "msft_passive_matched_window",
                "benchmark",
                scenario,
                passive_equal_weight(target, fee_bps=fee),
            )
        event_signals = pd.DataFrame(0, index=target.index, columns=target.columns)
        for prediction in predictions:
            event_signals.loc[pd.Timestamp(prediction["timestamp"]), "MSFT"] = (
                1 if prediction["label"] == 1 else -1
            )
        preference = pd.DataFrame(1.0, index=target.index, columns=target.columns)
        for scenario, fee in [("gross", 0), ("base", 10), ("stress", 30)]:
            record(
                "msft_revenue_event",
                "alternative_data",
                scenario,
                conlan.preference_portfolio(
                    target, event_signals, preference, max_positions=1, fee_bps=fee
                ),
            )

        base_preference = conlan.rolling_sharpe(closes, 100)
        for family in conlan.FAMILIES:
            signals = rule_asset_signals(closes, family)
            for scenario, fee in [("gross", 0), ("base", 10), ("stress", 30)]:
                record(
                    f"{family}_sharpe100_p3",
                    family,
                    scenario,
                    conlan.preference_portfolio(
                        closes, signals, base_preference, max_positions=3, fee_bps=fee
                    ),
                    config={"sharpe_window": 100, "max_positions": 3, "band_window": 20},
                )
            # Prespecified exploratory grid. It is not a final model selection.
            for window in (50, 100, 150):
                pref = conlan.rolling_sharpe(closes, window)
                for positions in (1, 3, 5):
                    for scenario, fee in [("gross", 0), ("base", 10), ("stress", 30)]:
                        record(
                            f"{family}_grid_w{window}_p{positions}",
                            family,
                            scenario,
                            conlan.preference_portfolio(
                                closes, signals, pref, max_positions=positions, fee_bps=fee
                            ),
                            config={
                                "sharpe_window": window,
                                "max_positions": positions,
                                "band_window": 20,
                            },
                        )
            summary["controls"][family] = {}
            for kind in ("white_noise", "bootstrap_preference"):
                returns = []
                group_seed = control_provenance(family, kind, repeat=0)["group_rng_seed"]
                for repeat, pref in _control_preferences(
                    closes,
                    base_preference,
                    kind=kind,
                    repeats=control_repeats,
                    seed=group_seed,
                    window=100,
                ):
                    for scenario, fee in [("base", 10), ("stress", 30)]:
                        result = conlan.preference_portfolio(
                            closes, signals, pref, max_positions=3, fee_bps=fee
                        )
                        record(
                            f"{family}_{kind}_{repeat:03d}",
                            family,
                            scenario,
                            result,
                            control=kind,
                            config={
                                "sharpe_window": 100,
                                "max_positions": 3,
                                **control_provenance(family, kind, repeat=repeat),
                            },
                        )
                        if scenario == "base":
                            returns.append(result["metrics"]["return_pct"])
                summary["controls"][family][kind] = {
                    "repeats": control_repeats,
                    "group_rng_seed": group_seed,
                    "rng_sequence": "shared_generator_advanced_across_repeats",
                    "median_base_return_pct": float(np.median(returns)),
                    "interval_95_base_return_pct": np.quantile(returns, [0.025, 0.975]).tolist(),
                }
    summary["ledger_path"] = str(ledger_path)
    summary["ledger_sha256"] = sha256(ledger_path.read_bytes())
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False))
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", type=Path, default=DEFAULT_SOURCES)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--controls", type=int, default=100)
    args = parser.parse_args()
    print(
        json.dumps(
            {
                k: v
                for k, v in run_study(
                    args.sources, args.output, control_repeats=args.controls
                ).items()
                if k != "candidate_metrics"
            },
            indent=2,
        )
    )
