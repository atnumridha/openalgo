"""Continuous paper runner and read-only live signal inspection."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import time
from pathlib import Path

import httpx

from .account import read_connected_snapshot
from .connection import hosted_activation
from .data import DeltaPublic
from .host import Host, resume_host_paper, shutdown_reason
from .paper import Ledger, PaperBook, wallet_seed
from .strategy import Config, decide


def emit(value):
    print(json.dumps(value, allow_nan=False), flush=True)


def parser():
    p = argparse.ArgumentParser(
        description="BTCUSD eight-indicator strategy. Follows OpenAlgo Analyze/Live mode; Live + Start activates the connected Delta account."
    )
    p.add_argument(
        "command", nargs="?", choices=["run", "report", "status", "readiness"], default="run"
    )
    p.add_argument(
        "--once",
        action="store_true",
        help="Print current indicators and plans, without creating a paper ledger",
    )
    p.add_argument(
        "--mode",
        choices=["auto", "paper", "live"],
        default="auto" if os.getenv("STRATEGY_ID") else "paper",
    )
    p.add_argument(
        "--arm-live",
        action="store_true",
        default=hosted_activation() or os.getenv("CONFLUENCE_ARM_LIVE") == "1",
        help="Standalone live activation; hosted runs use Live mode + Start",
    )
    p.add_argument(
        "--execution-root", type=Path, default=Path.home() / ".local/state/delta-scalper"
    )
    p.add_argument("--leverage", type=int, default=int(os.getenv("CONFLUENCE_LEVERAGE", "25")))
    p.add_argument(
        "--db",
        type=Path,
        default=Path(
            os.getenv("CONFLUENCE_DB", "~/.local/state/delta-confluence/paper.sqlite")
        ).expanduser(),
    )
    p.add_argument("--wallet-snapshot", type=Path, default=os.getenv("CONFLUENCE_WALLET_SNAPSHOT"))
    p.add_argument(
        "--account-balance",
        action="store_true",
        default=bool(os.getenv("STRATEGY_ID")),
        help="Seed the first paper run from the connected Delta USD wallet; automatic in the OpenAlgo host",
    )
    p.add_argument(
        "--capital-usd",
        type=float,
        help="Explicit hypothetical paper capital; never described as account balance",
    )
    p.add_argument(
        "--iterations",
        type=int,
        default=0,
        help="0 runs continuously; positive number stops after that many polls",
    )
    p.add_argument(
        "--resume",
        action="store_true",
        help="Explicitly resume a paused ledger; daily halt requires a later IST day",
    )
    return p


def prepare_paper(ledger, args, cfg):
    paper = ledger.load(cfg)
    if paper is not None:
        if args.wallet_snapshot or args.capital_usd is not None:
            raise ValueError(
                "Existing ledger balance is preserved. Omit initialization arguments on restart."
            )
        return paper
    snapshot = None
    if args.wallet_snapshot:
        with open(args.wallet_snapshot) as file:
            snapshot = json.load(file)
    elif args.capital_usd is None and args.account_balance:
        emit(
            {
                "mode": "paper",
                "status": "Reading connected Delta USD available balance for first initialization",
            }
        )
        snapshot = read_connected_snapshot()
    if snapshot is not None:
        capital = wallet_seed(snapshot, time.time())
        source = "Delta read-only USD wallet snapshot"
    elif args.capital_usd is not None:
        capital = args.capital_usd
        source = "explicit hypothetical paper capital"
    else:
        raise ValueError(
            "First paper run requires --account-balance or --wallet-snapshot with a fresh sanitized Delta USD balance; --once needs no balance"
        )
    paper = PaperBook.fresh(capital, time.time(), cfg, source)
    if snapshot is not None:
        usd = next(r for r in snapshot["result"] if r["asset_symbol"] == "USD")
        paper.state["seed_snapshot"] = {
            "environment": "india_prod",
            "captured_at": snapshot["captured_at"],
            "available_usd": str(usd["available_balance"]),
        }
    ledger.save(paper)
    return paper


def main(argv=None):
    args = parser().parse_args(argv)
    cfg = Config(leverage=args.leverage)
    if args.iterations < 0:
        raise ValueError("Iterations must be nonnegative")
    if args.wallet_snapshot and args.capital_usd is not None:
        raise ValueError("Choose account snapshot or explicit hypothetical capital, not both")
    if args.command in ("report", "status"):
        if not args.db.exists():
            emit({"mode": "paper", "status": "not initialized", "trade_count": 0})
            return 0
        with Ledger(args.db, readonly=True) as ledger:
            emit(ledger.report())
        return 0
    if args.command == "readiness":
        from .live import readiness

        emit(readiness(args.execution_root, cfg, args.arm_live))
        return 0
    if args.mode == "paper" or args.once:
        return run_paper(args, cfg)
    return run_host(args, cfg)


def run_host(args, cfg):
    from .live import backend, readiness, recovery_needed
    from .live import run as run_live

    with Host() as host:
        while True:
            requested = host.mode()
            emit(
                {
                    "requested_mode": requested,
                    "mode_source": "OpenAlgo Analyze/Live",
                    "selection": args.mode,
                }
            )
            if args.mode == "live" and requested != "live":
                raise ValueError("OpenAlgo is in Analyze mode; explicit live execution is blocked")
            recovery = recovery_needed(args.db.with_name("live.sqlite"))
            if recovery:
                emit(
                    {
                        "mode": "live",
                        "requested_mode": requested,
                        "status": "Recovering owned live exposure before accepting entries",
                    }
                )
                backend()
                with DeltaPublic() as feed:
                    result = asyncio.run(run_live(args, cfg, host, feed, emit))
            elif requested == "paper":
                result = run_paper(args, cfg, host)
            else:
                # The independent paper ledger never supplies live size or simulated positions.
                if args.db.exists():
                    with Ledger(args.db) as ledger:
                        p = ledger.load(cfg)
                        if p:
                            resume_host_paper(p, os.getenv("OPENALGO_START_REASON"), time.time())
                            if args.resume:
                                p.resume(time.time())
                            ledger.save(p)
                    if p and (p.state["position"] or p.state["pending"]):
                        # Finish managing the existing paper trade before switching accounts.
                        result = run_paper(args, cfg, host)
                        if result != 90:
                            return result
                        continue
                    if p and (p.state["halt_day"] is not None or p.state["paused"]):
                        emit(
                            {
                                "mode": "live",
                                "status": "blocked",
                                "message": "Paper pause/daily halt must be explicitly resolved before changing mode; a daily halt requires a later India-time day",
                            }
                        )
                        return 2
                gate = readiness(args.execution_root, cfg, args.arm_live)
                if not gate["ready"]:
                    from .observer import run as observe

                    result = observe(args, cfg, host, emit)
                    if result != 90:
                        return result
                    continue
                emit(
                    {**gate, "status": "Live activation accepted; checking account and trade risk"}
                )
                backend()
                with DeltaPublic() as feed:
                    result = asyncio.run(run_live(args, cfg, host, feed, emit))
            if result != 90:
                return result


def run_paper(args, cfg, host=None):
    with DeltaPublic() as feed:
        if args.once:
            start = time.monotonic()
            context = feed.context(time.time())
            quote = feed.market()
            now = time.time()
            result = decide({**context, **quote}, cfg, now)
            result.update(
                mode="analysis_only",
                capital_basis="Planning cap $5; account balance not read",
                data_load_latency_ms=(time.monotonic() - start) * 1000,
                quote_age_seconds=now - quote["quote_time"],
                public_poll_latency_ms=quote["public_poll_latency_ms"],
            )
            emit(result)
            return 0
        with Ledger(args.db) as ledger:
            paper = prepare_paper(ledger, args, cfg)
            if os.getenv("STRATEGY_ID"):
                resume_host_paper(paper, os.getenv("OPENALGO_START_REASON"), time.time())
                ledger.save(paper)
            if args.resume:
                paper.resume(time.time())
                ledger.save(paper)
            if (paper.state["paused"] or paper.state["halt_day"] is not None) and not paper.state[
                "position"
            ]:
                emit(
                    {
                        "mode": "paper",
                        "status": paper.state["status"],
                        "message": "Use --resume explicitly; same-day daily halt cannot be resumed.",
                    }
                )
                return 0
            stopped = False

            def stop_requested(*_):
                nonlocal stopped
                stopped = True

            previous = {
                sig: signal.signal(sig, stop_requested) for sig in (signal.SIGINT, signal.SIGTERM)
            }
            # Cancel old simulated entries; their fill path during downtime is unknown.
            if paper.state["pending"]:
                paper.disconnect(time.time())
                ledger.save(paper)
            last_log = None
            iterations = 0
            last_quote = {}
            mode_change = False
            emit(
                {
                    "mode": "paper",
                    "status": "started",
                    "ledger": str(args.db),
                    "capital_source": paper.state["capital_source"],
                    "poll_seconds": 1,
                    "note": "No exchange orders. Stop with Ctrl+C or Python Strategies Stop.",
                }
            )
            try:
                while not stopped and (not args.iterations or iterations < args.iterations):
                    started = time.monotonic()
                    iterations += 1
                    decision = None
                    requested = "paper"
                    if host:
                        try:
                            requested = host.mode()
                        except ValueError:
                            requested = None
                        if requested != "paper":
                            # Cancel queued simulated entries. Existing fills stay paper until flat.
                            if paper.state["pending"]:
                                paper.disconnect(time.time())
                            if requested == "live" and not paper.state["position"]:
                                mode_change = True
                                break
                    try:
                        # Do not wait for option/history requests while managing exposure.
                        if not paper.state["position"] and not paper.state["pending"]:
                            try:
                                context = feed.context(time.time())
                            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                                context = None
                        else:
                            context = None
                        last_quote = feed.market()
                        now = time.time()
                        if context is not None and requested == "paper":
                            decision = decide(
                                {
                                    **context,
                                    **last_quote,
                                    "available_collateral": paper.state["cash"],
                                    "daily_budget": paper.budget(now),
                                },
                                cfg,
                                now,
                            )
                        elif not paper.state["position"] and not paper.state["pending"]:
                            decision = {
                                "action": "HOLD",
                                "asof": now,
                                "reason": "Public candle, product or option context unavailable",
                            }
                        if decision is not None:
                            # Bounded latest snapshot; no accumulation of minute DataFrames.
                            paper.state["latest_decision"] = decision
                        if requested != "paper":
                            decision = {
                                "action": "HOLD",
                                "asof": now,
                                "reason": "OpenAlgo mode changed or unavailable; finishing paper exposure",
                            }
                        paper.step(last_quote, decision, now)
                        paper.state["public_poll_latency_ms"] = last_quote["public_poll_latency_ms"]
                        key = (
                            paper.state["status"],
                            bool(paper.state["position"]),
                            bool(paper.state["pending"]),
                            decision.get("action") if decision else None,
                            decision.get("reason") if decision else None,
                            int(now // 60),
                        )
                        if key != last_log or paper.events:
                            emit(
                                {
                                    "at": now,
                                    "mode": "paper",
                                    "status": paper.state["status"],
                                    "decision": decision,
                                    "events": paper.events,
                                    "position": paper.state["position"],
                                    "pending": paper.state["pending"] is not None,
                                    "cash_usd": paper.state["cash"],
                                }
                            )
                            last_log = key
                    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                        paper.disconnect(time.time())
                        error = (type(exc).__name__, "public_data_error", int(time.time() // 60))
                        if error != last_log:
                            emit(
                                {
                                    "mode": "paper",
                                    "status": "public data unavailable; entries suspended",
                                    "error_type": type(exc).__name__,
                                }
                            )
                            last_log = error
                    ledger.save(paper)
                    # Short sleeps allow host Stop/Ctrl+C to be processed promptly.
                    while not stopped and time.monotonic() - started < 1:
                        time.sleep(0.05)
            finally:
                try:
                    try:
                        last_quote = feed.market()
                    except (httpx.HTTPError, ValueError, KeyError, TypeError):
                        last_quote = {}
                    paper.stop(
                        last_quote,
                        time.time(),
                        reason="mode_change" if mode_change else shutdown_reason(),
                    )
                    ledger.save(paper)
                    emit(ledger.report())
                finally:
                    for sig, handler in previous.items():
                        signal.signal(sig, handler)
            return 2 if paper.state["position"] else 90 if mode_change else 0


if __name__ == "__main__":
    raise SystemExit(main())
