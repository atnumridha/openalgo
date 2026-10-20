"""Hosted controller: one-second management, durable state, no UI-owned timers."""

import asyncio
import hashlib
import json
import os
import signal
import time
from contextlib import AsyncExitStack
from dataclasses import asdict
from decimal import Decimal as D

from strategies.confluence.account import read_connected_snapshot
from strategies.confluence.connection import hosted_activation
from strategies.confluence.host import Host
from strategies.confluence.live import EntryNotReady, backend, execution_credentials
from strategies.confluence.paper import wallet_seed

from .execution import Engine, types
from .feed import Feed
from .paper import broker_type
from .setup import VERSION, advance, plan_order
from .state import directory, plan_revision, settings


def main():
    sid = os.environ.get("STRATEGY_ID", "")
    cfg = settings(sid)
    return asyncio.run(run(sid, cfg))


async def run(sid, cfg, iterations=0):
    _, _, Market, Rest, Risk, _, Store = backend()
    from delta_scalper.runner import account_lock, controller_lock

    Ledger, Broker = types(cfg)
    folder = directory(sid)
    path = folder / (cfg.mode + ".sqlite")
    other = folder / ("paper.sqlite" if cfg.mode == "live" else "live.sqlite")
    from strategies.confluence.live import recovery_needed

    if recovery_needed(other):
        raise ValueError("Other mode has unresolved exposure; reconcile it first")
    halted = False

    def stop(*_):
        nonlocal halted
        halted = True

    handlers = {sig: signal.signal(sig, stop) for sig in (signal.SIGTERM, signal.SIGINT)}
    ledger = rest = None
    engine = None
    try:
        async with AsyncExitStack() as stack:
            stack.enter_context(Store.InstanceLock(folder / "controller.lock"))
            ledger = Ledger(path)
            stack.callback(ledger.close)
            ledger.bind()
            # A scheduled restart must not silently clear a manual/daily pause.
            if os.getenv("OPENALGO_START_REASON") == "manual" and ledger.get("pause_reason") in (
                "operator_stop",
                "server_shutdown",
            ):
                try:
                    ledger.resume()
                except ValueError:
                    pass  # A daily halt must not prevent recovery of an existing trade.
            host = stack.enter_context(Host())
            feed = stack.enter_context(Feed())
            product_data = feed.product("BTCUSD")
            p = Risk.Product.from_api(product_data)
            book = Market.Book()
            if cfg.mode == "live":
                if not hosted_activation():
                    raise ValueError("Start this strategy from the signed-in OpenAlgo host")
                credentials = execution_credentials(folder)
                # Same global controller/account lock root as the existing executor.
                from strategies.confluence.live import DEFAULT_ROOT

                stack.enter_context(
                    controller_lock(DEFAULT_ROOT, "live", "india_prod", credentials)
                )
                rest = Rest.DeltaREST("india_prod", credentials, ledger)
                stack.push_async_callback(rest.close)
                stack.enter_context(await account_lock(DEFAULT_ROOT, rest, "india_prod"))
                identity = ledger.get("credential_identity")
                if identity and identity != credentials.identity:
                    raise ValueError("Account changed; reconcile the saved trade first")
                ledger.set("credential_identity", credentials.identity)
                broker = Broker(rest, p, book, ledger)
                await broker.reconcile_unknown()
            else:
                broker = broker_type()(p, book, ledger)
                if ledger.get("paper_seed") is None:
                    wallet = read_connected_snapshot()
                    amount = wallet_seed(wallet, time.time())
                    ledger.set(
                        "paper_seed",
                        {
                            "capital": amount,
                            "source": "Connected Delta available USD at first paper start",
                        },
                    )
                if ledger.get("position"):
                    broker.restore(ledger.get("position"))
            engine = Engine(ledger, broker, book, p, cfg)

            async def finish():
                error = None
                try:
                    await engine.stop("operator_stop")
                    for _ in range(3):
                        if not ledger.get("position") and not ledger.unresolved():
                            break
                        await engine.manage()
                except Exception as exc:
                    error = type(exc).__name__
                unresolved = bool(error or ledger.get("position") or ledger.unresolved())
                view = {
                    "mode": cfg.mode,
                    "asof": time.time(),
                    "status": "unresolved" if unresolved else "stopped",
                    "position": ledger.get("position"),
                    "execution_enabled": False,
                    "message": error,
                }
                ledger.set("view", view)
                print(json.dumps(view), flush=True)

            stack.push_async_callback(finish)
            count = 0
            last_emit = 0
            state = ledger.get("setup", {})
            # Never deliver a disconnected historical price crossing as a live trigger.
            if state.get("candidate") and state["candidate"]["stage"] in ("WATCHING", "TRIGGERED"):
                state["candidate"]["stage"] = "DATA_GAP"
            while not halted and (not iterations or count < iterations):
                count += 1
                start = time.monotonic()
                now = time.time()
                plan = {}
                problem = None
                try:
                    cmd = ledger.take_command()
                    if cmd:
                        if cmd["action"] == "pause":
                            ledger.pause("operator_pause")
                        elif cmd["action"] == "resume":
                            try:
                                ledger.resume()
                            except ValueError as exc:
                                problem = str(exc)
                        elif cmd["action"] == "close":
                            ledger.set("close_requested", True)
                    if ledger.get("close_requested"):
                        await engine.stop("operator_pause")
                        if not ledger.get("position") and not ledger.unresolved():
                            ledger.set("close_requested", False)
                    requested = host.mode()
                    if requested != cfg.mode:
                        ledger.pause("mode_changed")
                    q = feed.market()
                    now = time.time()
                    book.bids = [(D(str(px)), D(str(size))) for px, size in q["bids"]]
                    book.asks = [(D(str(px)), D(str(size))) for px, size in q["asks"]]
                    book.ts = q["quote_time"]
                    book.received = now
                    if ledger.get("position"):
                        await engine.manage()
                        if cfg.mode == "paper" and ledger.get("position"):
                            broker.restore(ledger.get("position"))
                            for x in sorted(q["trades"], key=lambda t: t["timestamp"]):
                                # Stable tuple ID: REST tape has no exchange trade ID.
                                xid = hashlib.sha256(
                                    json.dumps(x, sort_keys=True).encode()
                                ).hexdigest()
                                broker.on_trade(
                                    {
                                        "id": xid,
                                        "price": D(str(x["price"])),
                                        "size": D(str(x["size"])),
                                        "side": x["side"],
                                        "ts": x["timestamp"],
                                    }
                                )
                            await engine.manage()
                    else:
                        context = feed.context(now)
                        q = feed.market()
                        now = time.time()
                        quote = {"bid": q["bid"], "ask": q["ask"], "time": q["quote_time"]}
                        refs = context["references"]
                        if cfg.manual_level:
                            refs = [r for r in refs if r["side"] != cfg.manual_side]
                            known = ledger.get("manual_known")
                            if known is None:
                                known = now
                                ledger.set("manual_known", known)
                            refs.append(
                                {
                                    "id": f"manual:{cfg.manual_side}:{cfg.manual_level}:{known}",
                                    "frame": "Manual",
                                    "side": cfg.manual_side,
                                    "price": cfg.manual_level,
                                    "known": known,
                                }
                            )
                        advance(state, context["bars"], refs, quote, cfg, now)
                        ledger.set("setup", state)
                        collateral = float(cfg.max_margin)
                        if cfg.mode == "paper":
                            seed = ledger.get("paper_seed")["capital"]
                            realised = ledger.db.execute(
                                "SELECT COALESCE(SUM(CAST(json_extract(value,'$.net') AS REAL)),0) FROM trades"
                            ).fetchone()[0]
                            collateral = max(0, float(seed) + realised)
                        candidate = state.get("candidate")
                        if candidate and candidate["stage"] == "TRIGGERED" and cfg.mode == "live":
                            try:
                                collateral = float(await broker.preflight())
                            except EntryNotReady as exc:
                                problem = "; ".join(exc.reasons)
                        plan = plan_order(
                            candidate, quote, product_data, cfg, time.time(), collateral
                        )
                        permitted = cfg.entry_mode == "auto" or bool(
                            cmd
                            and cmd["action"] == "approve"
                            and 0 <= now - cmd["at"] <= 5
                            and cmd.get("setup_id") == plan.get("setup_id")
                            and cmd.get("approved_plan") == plan
                        )
                        daily = ledger.daily(now)
                        if (
                            not plan.get("blocked")
                            and permitted
                            and not problem
                            and not ledger.get("paused")
                            and not daily["halted"]
                            and host.mode() == cfg.mode
                        ):
                            if (
                                cfg.mode == "live"
                                and execution_credentials(folder).identity != credentials.identity
                            ):
                                raise ValueError("Account changed; entries paused")
                            # Network preflight may move the market. Reprice and require
                            # the same plan; review approval cannot authorize a new size.
                            latest = feed.market()
                            fresh = {
                                "bid": latest["bid"],
                                "ask": latest["ask"],
                                "time": latest["quote_time"],
                            }
                            checked = plan_order(
                                candidate, fresh, product_data, cfg, time.time(), collateral
                            )
                            if checked != plan:
                                problem = "Quote changed; reviewing the updated plan next second"
                            else:
                                interval = int(
                                    product_data["product_specs"]["rate_exchange_interval"]
                                )
                                if (
                                    interval != 28800
                                    or (int(now) // interval + 1) * interval - now
                                    < cfg.max_hold_seconds + 60
                                ):
                                    problem = "Too close to the funding window"
                                else:
                                    await engine.submit(
                                        plan,
                                        plan["setup_id"],
                                        metadata={
                                            "funding_at": (int(now) // interval + 1) * interval
                                        },
                                    )
                    view = {
                        "mode": cfg.mode,
                        "asof": time.time(),
                        "version": VERSION,
                        "config": asdict(cfg),
                        "candidate": state.get("candidate"),
                        "plan": plan,
                        "plan_revision": plan_revision(plan),
                        "position": ledger.get("position"),
                        "daily": ledger.daily(),
                        "status": "paused" if ledger.get("paused") else "running",
                        "message": problem or ledger.get("pause_reason"),
                        "execution_enabled": not ledger.get("paused") and not problem,
                        "feed": "One-second REST snapshots; intervening ticks may be missed",
                    }
                    ledger.set("view", view)
                    if time.time() - last_emit >= 10:
                        print(json.dumps(view, allow_nan=False), flush=True)
                        last_emit = time.time()
                except Exception as exc:
                    ledger.pause("reconciliation_required")
                    ledger.set(
                        "view",
                        {
                            "mode": cfg.mode,
                            "asof": time.time(),
                            "status": "error",
                            "message": type(exc).__name__ + ": " + str(exc)
                            if isinstance(exc, ValueError)
                            else type(exc).__name__
                            + "; check execution logs and broker protection",
                            "position": ledger.get("position"),
                            "execution_enabled": False,
                        },
                    )
                    # Existing exchange protection survives. Continue reconciliation
                    # even when entries are paused or public history is unavailable.
                    if ledger.get("position"):
                        try:
                            await engine.manage()
                        except Exception:
                            pass
                await asyncio.sleep(max(0.05, 1 - (time.monotonic() - start)))
    finally:
        for sig, handler in handlers.items():
            signal.signal(sig, handler)
