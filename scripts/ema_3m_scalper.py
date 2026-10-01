"""Compare closed3m EMA9/20 scalpers as simulated PAPER research, without orders.

CSV timestamps name one-minute candle OPENs. An explicit observation cutoff
prevents unfinished minutes from entering the replay. Optional OpenAlgo access
calls only historical market data on a loopback server.
"""

import argparse
import csv
import hashlib
import ipaddress
import json
import math
import os
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

NOTICE = (
    "Simulated PAPER research only; profits are not guaranteed; not eligible for live execution."
)
TRADE_COLUMNS = [
    "variant",
    "signal_at",
    "entry_at",
    "exit_at",
    "entry_price",
    "stop_price",
    "target_price",
    "exit_price",
    "quantity",
    "gross_pnl",
    "fees",
    "net_pnl",
    "reason",
    "ambiguous",
]
REJECTION_COLUMNS = ["variant", "signal_at", "reason"]


def positive_number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError("Use a finite positive number") from None
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("Use a finite positive number")
    return number


def aware_timestamp(value):
    try:
        stamp = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise ValueError("Use an ISO timestamp including its timezone") from None
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("Timestamp requires an explicit timezone offset")
    return stamp


def parser():
    cli = argparse.ArgumentParser(description=__doc__, epilog=NOTICE)
    source = cli.add_mutually_exclusive_group(required=True)
    source.add_argument("--candles", type=Path, help="One-minute OPEN-timestamp OHLCV CSV")
    source.add_argument(
        "--fetch-openalgo", action="store_true", help="Read-only loopback history request"
    )
    cli.add_argument(
        "--as-of", help="CSV observation cutoff, ISO timestamp with timezone (required for CSV)"
    )
    cli.add_argument(
        "--symbol", help="Selected OpenAlgo option symbol; required for fetching history"
    )
    cli.add_argument("--exchange", choices=["NFO"], default="NFO")
    cli.add_argument("--start-date", help="History start date YYYY-MM-DD")
    cli.add_argument("--end-date", help="History end date YYYY-MM-DD")
    cli.add_argument(
        "--lot-size", required=True, type=int, help="Verified units in one contract lot"
    )
    cli.add_argument(
        "--tick-size", required=True, type=positive_number, help="Verified premium tick size"
    )
    cli.add_argument("--costs", required=True, type=Path, help="Explicit dated fee-schedule JSON")
    cli.add_argument("--variant", choices=["compare", "crossover", "pullback"], default="compare")
    cli.add_argument("--capital", type=positive_number, default=15000)
    cli.add_argument(
        "--max-trade-loss", type=positive_number, default=500, help="All-in planned paper loss cap"
    )
    cli.add_argument("--max-daily-loss", type=positive_number, default=1500)
    cli.add_argument(
        "--output", required=True, type=Path, help="New report folder outside the source checkout"
    )
    return cli


def read_candles(path):
    import pandas as pd

    try:
        frame = pd.read_csv(path)
    except (OSError, ValueError, pd.errors.ParserError):
        raise ValueError("Could not read the candle CSV") from None
    required = {"timestamp", "open", "high", "low", "close", "volume"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError("Candle CSV requires columns: " + ", ".join(sorted(missing)))
    stamps = [aware_timestamp(value) for value in frame.pop("timestamp")]
    frame.index = pd.DatetimeIndex(pd.to_datetime(stamps, utc=True)).tz_convert("Asia/Kolkata")
    frame.index.name = "timestamp"
    return frame


def loopback_host(value):
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
        local = hostname == "localhost" or ipaddress.ip_address(hostname).is_loopback
    except (TypeError, ValueError):
        raise ValueError("OPENALGO_HOST must be a loopback HTTP(S) server") from None
    if (
        not local
        or parsed.scheme not in {"http", "https"}
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or port == 0
    ):
        raise ValueError("OPENALGO_HOST must be a loopback HTTP(S) server")
    return value.rstrip("/")


def fetch_history(symbol, exchange, start_date, end_date):
    """Fetch only history; never inspect account mode, books, or order endpoints."""
    import pandas as pd

    host = loopback_host(os.environ.get("OPENALGO_HOST", "http://127.0.0.1:5001"))
    key = os.environ.get("OPENALGO_API_KEY")
    if not key or not key.strip():
        raise ValueError("Set OPENALGO_API_KEY in the process environment for read-only history")
    # The cutoff precedes the request, even if retrieval crosses a minute boundary.
    as_of = pd.Timestamp.now(tz="UTC")
    try:
        from openalgo import api

        with api(api_key=key, host=host, timeout=30) as client:
            result = client.history(
                symbol=symbol,
                exchange=exchange,
                interval="1m",
                start_date=start_date,
                end_date=end_date,
            )
    except Exception:
        # An upstream error can contain request credentials; never echo it.
        raise ValueError(
            "OpenAlgo history request failed; check the local server connection"
        ) from None
    if not isinstance(result, pd.DataFrame) or not isinstance(result.index, pd.DatetimeIndex):
        raise ValueError("OpenAlgo history returned no usable candle DataFrame")
    if result.index.tz is None:
        raise ValueError("OpenAlgo history requires timezone-aware candle timestamps")
    return result, as_of


def read_costs(path, exchange):
    from services.research.costs import validate_cost_schedule

    try:
        raw = json.loads(path.read_text())
    except (OSError, ValueError):
        raise ValueError("Could not read the explicit cost schedule JSON") from None
    try:
        costs = validate_cost_schedule(raw)
    except ValueError as error:
        raise ValueError(f"Invalid cost schedule: {error}") from None
    if costs.get("exchange", exchange) != exchange or costs.get("broker", "kotak") != "kotak":
        raise ValueError("Cost schedule broker/exchange does not match the selected contract")
    return costs


def output_folder(path):
    output = path.expanduser().resolve()
    if output.is_relative_to(ROOT):
        raise ValueError("Report output must be outside the source checkout")
    if output.exists():
        raise ValueError("Report output folder already exists; choose a new folder")
    return output


def write_csv(path, records, required_columns):
    columns = required_columns + sorted(
        {key for row in records for key in row} - set(required_columns)
    )
    with path.open("x", newline="", encoding="utf-8") as stream:
        os.chmod(path, 0o600)
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(records)


def write_report(output, report):
    output.mkdir(parents=True, mode=0o700, exist_ok=False)
    path = output / "report.json"
    with path.open("x", encoding="utf-8") as stream:
        os.chmod(path, 0o600)
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write("\n")
    trades, rejected = [], []
    for variant, replay in report["variants"].items():
        trades.extend({"variant": variant, **record} for record in replay["trades"])
        rejected.extend({"variant": variant, **record} for record in replay["rejected"])
    write_csv(output / "trades.csv", trades, TRADE_COLUMNS)
    write_csv(output / "rejections.csv", rejected, REJECTION_COLUMNS)


def main(argv=None):
    cli = parser()
    args = cli.parse_args(argv)
    try:
        output = output_folder(args.output)
        costs = read_costs(args.costs, args.exchange)
        if args.candles:
            if not args.as_of:
                raise ValueError("--as-of is required for candle CSV input")
            as_of = aware_timestamp(args.as_of)
            frame = read_candles(args.candles)
            source = {
                "kind": "csv",
                "sha256": hashlib.sha256(args.candles.read_bytes()).hexdigest(),
            }
        else:
            if args.as_of:
                raise ValueError(
                    "--as-of applies to CSV; fetched history captures its cutoff before the request"
                )
            if not args.symbol or not args.start_date or not args.end_date:
                raise ValueError("Fetching requires --symbol, --start-date, and --end-date")
            try:
                first = datetime.strptime(args.start_date, "%Y-%m-%d").date()
                last = datetime.strptime(args.end_date, "%Y-%m-%d").date()
            except ValueError:
                raise ValueError("History dates must use YYYY-MM-DD") from None
            if first > last:
                raise ValueError("History start date is after its end date")
            frame, as_of = fetch_history(args.symbol, args.exchange, args.start_date, args.end_date)
            source = {
                "kind": "openalgo_history",
                "interval": "1m",
                "start_date": args.start_date,
                "end_date": args.end_date,
            }

        from services.research.ema_3m_paper import PaperConfig, run_paper

        config_values = {
            "lot_size": args.lot_size,
            "tick_size": args.tick_size,
            "capital": args.capital,
            "max_trade_loss": args.max_trade_loss,
            "max_daily_loss": args.max_daily_loss,
        }
        config = PaperConfig(**config_values)
        variants = ["crossover", "pullback"] if args.variant == "compare" else [args.variant]
        results = {
            variant: run_paper(frame, as_of=as_of, variant=variant, config=config, costs=costs)
            for variant in variants
        }
        report = {
            "mode": "PAPER",
            "live_eligible": False,
            "notice": NOTICE,
            "symbol": args.symbol,
            "exchange": args.exchange,
            "source": source,
            "as_of": as_of.isoformat(),
            "costs": costs,
            "config": config_values
            | {
                "cooldown_minutes": config.cooldown_minutes,
                "entry_start": config.entry_start,
                "entry_cutoff": config.entry_cutoff,
                "flatten_at": config.flatten_at,
            },
            "variants": results,
        }
        write_report(output, report)
        for variant, replay in results.items():
            summary = replay["summary"]
            net = summary["net_pnl"]
            rendered = f"{net:.2f}" if net is not None else "unavailable (unresolved exposure)"
            print(
                f"PAPER {variant}: trades={summary['trade_count']} modeled_net={rendered} "
                f"modeled_costs={summary['total_costs']:.2f} complete={replay['complete']}"
            )
        return 0
    except (ValueError, TypeError, OSError) as error:
        cli.exit(2, f"PAPER input error: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
