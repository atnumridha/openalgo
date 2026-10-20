"""Confluence adapter for the installed, journaled Delta execution engine.

Importing this module never loads credentials or connects to Delta. Production
entry uses the current OpenAlgo connection and Live + Start activation. Testnet
qualification is reported separately. Ongoing protection is independent of UI mode.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import signal
import sqlite3
import sys
import time
from contextlib import ExitStack
from dataclasses import asdict
from decimal import Decimal as D
from pathlib import Path

from .strategy import decide

BACKEND = Path.home() / ".codex/skills/delta-scalper/scripts"
DEFAULT_ROOT = Path.home() / ".local/state/delta-scalper"
REQUIRED = {
    "attached_stop",
    "partial_fill_protection",
    "stop_handover",
    "amendment",
    "reduce_only_close",
    "mode_switch",
    "restart",
    "confluence_risk",
}


class EntryNotReady(RuntimeError):
    """Readable account/configuration issue; monitoring can continue without entry."""

    def __init__(self, reasons):
        self.reasons = list(reasons)
        super().__init__("; ".join(self.reasons))


def backend():
    if not (BACKEND / "delta_scalper/live.py").is_file():
        raise ValueError("Installed Delta execution engine is missing")
    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))
    from delta_scalper import engine, live, market, rest, risk, safety, store

    return engine, live, market, rest, risk, safety, store


def build_hash():
    h = hashlib.sha256()
    for folder in (Path(__file__).parent, BACKEND / "delta_scalper"):
        for path in sorted(folder.glob("*.py")):
            h.update(path.name.encode())
            h.update(path.read_bytes())
    # Fee planning and risk behavior are part of the qualified build too.
    root = Path(__file__).resolve().parents[2]
    for path in [root / "services/crypto_fees.py", *sorted((root / "services/risk").glob("*.py"))]:
        h.update(path.name.encode())
        h.update(path.read_bytes())
    return h.hexdigest()


def execution_credentials(root):
    from .connection import connected_credentials

    if os.getenv("STRATEGY_ID"):
        return connected_credentials()
    *_, safety, _ = backend()
    try:
        return safety.load_credentials(root, "india_prod")
    except (OSError, ValueError, KeyError, TypeError):
        raise ValueError(
            "Production credentials are missing or invalid; use the existing OpenAlgo host connection or standalone secure setup"
        ) from None


def readiness(root, cfg, armed=False):
    root = Path(root)
    errors = []
    warnings = []
    if not armed:
        errors.append("Live execution is not armed")
    _, _, _, _, _, safety, _ = backend()
    try:
        credentials = execution_credentials(root)
        if not credentials.rotated:
            warnings.append("Credential rotation has not been independently verified")
    except ValueError as exc:
        errors.append(str(exc))
    proof = root / "confluence-qualification.json"
    qualified = False
    try:
        q = safety.private_json(proof)
        qualified = bool(
            q.get("environment") == "india_testnet"
            and q.get("code_hash") == build_hash()
            and q.get("config") == asdict(cfg)
            and 0 <= time.time() - q.get("completed_at", 0) < 30 * 86400
            and REQUIRED <= set(q.get("passed", []))
            and q.get("flat_confirmed") is True
            and q.get("evidence")
        )
    except (OSError, ValueError, KeyError, TypeError):
        pass
    if not qualified:
        warnings.append(
            "Exchange execution qualification is unverified for this build/configuration"
        )
    return {
        "mode": "live",
        "ready": not errors,
        "blockers": errors,
        "warnings": warnings,
        "qualification_verified": qualified,
        "preflight_verified": False,
        "credential_source": "OpenAlgo connected Delta account"
        if os.getenv("STRATEGY_ID")
        else "standalone secure setup",
    }


def recovery_needed(path):
    path = Path(path)
    if not path.exists():
        return False
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
        row = db.execute("SELECT value FROM kv WHERE key='position'").fetchone()
        return bool(
            (row and json.loads(row[0]))
            or db.execute(
                "SELECT 1 FROM intents WHERE status IN ('pending','unknown') LIMIT 1"
            ).fetchone()
        )


def live_types(cfg):
    Engine, Live, Market, Rest, Risk, Safety, Store = backend()
    profile = Risk.RiskProfile(
        "confluence",
        D(str(cfg.max_risk)),
        D(str(cfg.max_margin)),
        D(str(cfg.max_notional)),
        D("3"),
        (cfg.leverage,),
    )

    class ConfluenceStore(Store.Store):
        def profile(self):
            return profile

        def bind(self):
            prior = self.get("confluence_config")
            if prior is not None and prior != asdict(cfg):
                raise ValueError(
                    "Live ledger configuration differs; preserve the original risk settings"
                )
            self.set("confluence_config", asdict(cfg))

    class Broker(Live.LiveBroker):
        async def preflight(self):
            # Read and verify; never silently change leverage, margin mode or auto top-up.
            prefs = await self.rest.get("/users/trading_preferences", auth=True)
            accounts = await self.rest.get("/sub_accounts", auth=True)
            current = [a for a in accounts if str(a["id"]) == str(prefs["user_id"])]
            mode = current[0].get("margin_mode") if len(current) == 1 else prefs.get("margin_mode")
            reasons = []
            if mode != "isolated":
                reasons.append("Isolated margin could not be confirmed by Delta")
            if prefs.get("default_auto_topup") is not False:
                reasons.append("Auto top-up is ON; the configured margin cap requires it OFF")
            if reasons:
                raise EntryNotReady(reasons)
            position = await self.rest.get("/positions", {"product_id": self.p.id}, True)
            orders = await self.rest.pages(
                "/orders", {"product_ids": self.p.id, "states": "open,pending"}
            )
            if D(str(position["size"])) != 0 or orders:
                raise EntryNotReady(
                    ["Existing BTCUSD orders/position must be managed before a new strategy entry"]
                )
            leverage = await self.rest.get(f"/products/{self.p.id}/orders/leverage", auth=True)
            if D(str(leverage.get("leverage", 0))) != cfg.leverage:
                raise EntryNotReady([f"verify_BTCUSD_leverage_{cfg.leverage}_before_entry"])
            wallet = await self.rest.get("/wallet/balances", auth=True)
            usd = [r for r in wallet if r.get("asset_symbol") == "USD"]
            if len(usd) != 1:
                raise Rest.ExchangeError("USD_wallet_unavailable")
            return Risk.money(usd[0]["available_balance"])

    return ConfluenceStore, Broker


def sized_plan(decision, cfg):
    *_, risk, _safety, _store = backend()
    p = decision["selected_plan"]
    return risk.SizedTrade(
        side="buy" if decision["action"] == "LONG" else "sell",
        entry=D(str(p["entry"])),
        stop=D(str(p["stop"])),
        target=D(str(p["target"])),
        qty=int(p["quantity"]),
        risk=D(str(p["net_risk"])),
        reward=D(str(p["net_target"])),
        margin=D(str(p["margin"])),
        slippage=D(str(p.get("slippage_reserve", cfg.slippage))),
        leverage=cfg.leverage,
        profile="confluence",
    )


def resume_live(store, origin, explicit, now):
    if explicit:
        store.resume(now)
    elif store.get("paused") and not store.daily(now)["halted"]:
        reason = store.get("pause_reason")
        if reason in ("schedule", "server_shutdown", "mode_change") or (
            origin == "manual" and reason == "operator_stop"
        ):
            store.resume(now)


async def run(args, cfg, host, feed, emit):
    from .host import shutdown_reason

    backend()
    from delta_scalper.runner import account_lock, controller_lock

    Engine, Live, Market, Rest, Risk, Safety, Store = backend()
    root = args.execution_root
    credentials = execution_credentials(root)
    path = args.db.with_name("live.sqlite")
    StoreClass, Broker = live_types(cfg)
    stopped = False
    reason = "operator_stop"

    def stop_requested(*_):
        nonlocal stopped
        stopped = True

    handlers = {sig: signal.signal(sig, stop_requested) for sig in (signal.SIGINT, signal.SIGTERM)}
    store = None
    rest = None
    engine = None
    locks = ExitStack()
    try:
        locks.enter_context(Store.InstanceLock(path.with_suffix(".lock")))
        locks.enter_context(controller_lock(root, "live", "india_prod", credentials))
        store = StoreClass(path)
        store.bind()
        account = store.get("credential_identity")
        if account is not None and account != credentials.identity:
            raise ValueError(
                "Live ledger belongs to another account; reconcile it before changing credentials"
            )
        store.set("credential_identity", credentials.identity)
        rest = Rest.DeltaREST("india_prod", credentials, store)
        locks.enter_context(await account_lock(root, rest, "india_prod"))
        product = Risk.Product.from_api(await rest.get("/products/BTCUSD"))
        book = Market.Book()
        broker = Broker(rest, product, book, store)
        engine = Engine.Engine(store, broker, book, product)
        await broker.reconcile_unknown()
        resume_live(store, os.getenv("OPENALGO_START_REASON"), args.resume, time.time())
        if store.get("position"):
            await engine.manage()
        last_log = None
        count = 0
        while not stopped and (not args.iterations or count < args.iterations):
            count += 1
            start = time.monotonic()
            try:
                requested = host.mode()
            except ValueError:
                requested = None
            try:
                q = feed.market()
                book.bids = [(D(str(p)), D(str(s))) for p, s in q["bids"]]
                book.asks = [(D(str(p)), D(str(s))) for p, s in q["asks"]]
                book.ts = q["quote_time"]
                book.received = time.time()
                decision = None
                if store.get("position"):
                    if requested != "live":
                        # Cancel pending entry remainder immediately; manage actual fills in Live.
                        t = store.get("position")
                        await broker.sync(t)
                        if t.get("entry_open"):
                            await broker.cancel_entry(t)
                    await engine.manage()
                elif requested == "paper":
                    reason = "mode_change"
                    return 90
                elif (
                    requested == "live" and not store.get("paused") and not store.daily()["halted"]
                ):
                    gate = readiness(root, cfg, args.arm_live)
                    if not gate["ready"]:
                        emit({**gate, "status": "live blocked"})
                        return 2
                    entry_wait = []
                    try:
                        collateral = await broker.preflight()
                    except EntryNotReady as exc:
                        entry_wait = exc.reasons
                        collateral = D(str(cfg.max_margin))
                    store.set("entry_wait", entry_wait)
                    context = feed.context(time.time())
                    q = feed.market()
                    decision = decide(
                        {
                            **context,
                            **q,
                            "available_collateral": float(collateral),
                            "daily_budget": float(store.daily()["budget"]),
                        },
                        cfg,
                        time.time(),
                    )
                    candle = decision.get("candle_closed", 0)
                    if (
                        not entry_wait
                        and decision["action"] in ("LONG", "SHORT")
                        and candle > store.get("last_candle", 0)
                    ):
                        # The last check after network/context work; no cached global mode.
                        if host.mode() == "live" and time.time() - q["quote_time"] <= 3:
                            current_credentials = execution_credentials(root)
                            if (
                                current_credentials.identity != credentials.identity
                                or current_credentials.secret != credentials.secret
                            ):
                                raise ValueError(
                                    "Delta connection changed; restart to reconcile the account"
                                )
                            store.set("last_candle", candle)
                            await engine.submit(
                                sized_plan(decision, cfg),
                                str(candle),
                                metadata={"funding_at": context["next_funding"]},
                            )
                key = (
                    int(time.time() // 60),
                    bool(store.get("position")),
                    store.get("pause_reason"),
                    requested,
                    tuple(store.get("entry_wait", [])),
                )
                if key != last_log:
                    emit(
                        {
                            "mode": "live",
                            "requested_mode": requested,
                            "status": "daily halt"
                            if store.daily()["halted"]
                            else "paused"
                            if store.get("paused")
                            else "monitoring"
                            if store.get("entry_wait")
                            else "running",
                            "entry_wait": store.get("entry_wait", []),
                            "capital_basis": "Planning cap only; account collateral not verified"
                            if store.get("entry_wait")
                            else "Verified account collateral",
                            "execution_enabled": requested == "live"
                            and not store.get("entry_wait")
                            and not store.get("paused")
                            and not store.daily()["halted"],
                            "pause_reason": store.get("pause_reason"),
                            "daily": store.daily(),
                            "position": store.get("position"),
                            "decision": decision,
                        }
                    )
                    last_log = key
            except Exception as exc:
                # Protection/reconciliation must still run if the public feed fails.
                if store.get("position"):
                    try:
                        await engine.manage()
                    except Exception:
                        pass
                store.pause("execution_reconciliation_required")
                emit(
                    {
                        "mode": "live",
                        "status": "entries paused; exchange protection retained",
                        "error_type": type(exc).__name__,
                    }
                )
            while not stopped and time.monotonic() - start < 1:
                await asyncio.sleep(0.05)
        reason = shutdown_reason() if stopped else "operator_stop"
        if reason == "manual":
            reason = "operator_stop"
        return 0
    finally:
        # Close/cancel owned orders only; an unresolved outcome remains journaled.
        try:
            if engine:
                shutdown_error = None
                try:
                    await engine.stop(reason)
                    for _ in range(3):
                        if not store.get("position") and not store.unresolved():
                            break
                        await engine.manage()
                except Exception as exc:
                    shutdown_error = type(exc).__name__
                unresolved = bool(shutdown_error or store.get("position") or store.unresolved())
                emit(
                    {
                        "mode": "live",
                        "status": "STOPPED WITH UNRESOLVED EXPOSURE" if unresolved else "stopped",
                        "position": store.get("position"),
                        "unresolved_intents": len(store.unresolved()),
                        "shutdown_error_type": shutdown_error,
                    }
                )
                if unresolved:
                    raise RuntimeError(
                        "Live shutdown unresolved; inspect owned exposure and intents before restart"
                    )
        finally:
            if rest:
                await rest.close()
            if store:
                store.close()
            locks.close()
            for sig, handler in handlers.items():
                signal.signal(sig, handler)
