"""Read-only OpenAlgo provider: real history, broker Net limit and executable depth."""

from datetime import datetime, timedelta
from decimal import Decimal as D

from database.auth_db import get_api_key_for_tradingview, get_auth_token
from services.depth_service import get_depth
from services.expiry_service import get_expiry_dates
from services.funds_service import get_funds
from services.history_service import get_history
from services.option_chain_service import get_option_chain
from utils.thread_safe_cache import LockedTTLCache

from .runner import closed_bars, should_evaluate
from .selection import select_contract
from .signals import evaluate_setup, anchor_setup
from .types import IST, Contract, Quote


class NativeMarket:
    def __init__(self):
        self.evaluated = LockedTTLCache(maxsize=8, ttl=86400)
        self.warmup = LockedTTLCache(maxsize=8, ttl=86400)

    def snapshot(self, owner, preset, now):
        clock = now.astimezone(IST)
        close = clock.replace(second=0, microsecond=0)
        auth = get_auth_token(owner)
        key = get_api_key_for_tradingview(owner)
        if not auth or not key:
            return {
                "error": "Kotak session is unavailable. Connect with a fresh TOTP when required."
            }
        cache_key = (owner, clock.date().isoformat())
        cached = self.warmup.get(cache_key)
        if cached is None:
            ok, warm, _ = get_history(
                "NIFTY",
                "NSE_INDEX",
                "15m",
                (clock.date() - timedelta(days=35)).isoformat(),
                clock.date().isoformat(),
                auth_token=auth,
                broker="kotak",
            )
            if not ok:
                return {
                    "error": "NIFTY warmup failed. Check the broker history service before the next close."
                }
            cached = tuple(
                b
                for b in closed_bars(warm.get("data", []), now)
                if b.time.astimezone(IST).date() < clock.date()
            )
            self.warmup[cache_key] = cached
        if not should_evaluate(now, self.evaluated.get(owner)):
            return {
                "message": "Waiting for a new confirmed 15-minute close in the 09:45–15:15 IST entry window."
            }
        ok, result, _ = get_history(
            "NIFTY",
            "NSE_INDEX",
            "15m",
            clock.date().isoformat(),
            clock.date().isoformat(),
            auth_token=auth,
            broker="kotak",
        )
        if not ok:
            return {
                "error": "NIFTY candle refresh failed. Check the broker connection and history service."
            }
        bars = list(cached) + closed_bars(result.get("data", []), now)
        if not bars or bars[-1].time + timedelta(minutes=15) != close:
            return {
                "message": "The broker has not supplied the final closed candle yet; waiting without a catch-up order."
            }
        setup = evaluate_setup(bars, preset)
        if not setup:
            self.evaluated[owner] = close
            return {
                "message": "No confirmed setup on the latest close. Awaiting the next bar; no trade forced."
            }
        ok, funds, _ = get_funds(auth_token=auth, broker="kotak")
        data = funds.get("data", {}) if ok else {}
        limit = data.get("availabletradinglimit")
        if limit is None:
            return {
                "error": "Kotak did not report a verified trading limit. Entry affordability is unavailable."
            }
        ok, dates, _ = get_expiry_dates("NIFTY", "NFO", "options", api_key=key)
        if not ok:
            return {"error": "Live option expiry metadata is unavailable."}
        expiries = []
        for value in dates.get("data", []):
            try:
                expiry = datetime.strptime(value, "%d-%b-%y").date()
                if expiry >= clock.date():
                    expiries.append(expiry)
            except (ValueError, TypeError):
                continue
        if not expiries:
            return {"error": "No unexpired NIFTY contract is available."}
        expiry = min(expiries)
        ok, chain, _ = get_option_chain(
            "NIFTY", "NSE_INDEX", expiry.strftime("%d%b%y").upper(), 20, key
        )
        if not ok:
            return {"error": "Live option-chain refresh failed."}
        setup = anchor_setup(setup, chain.get("underlying_ltp") or 0)
        if setup is None:
            return {
                "error": "The fresh index reference no longer permits the original structural risk bracket."
            }

        candidates = []
        for row in chain.get("chain", []):
            leg = row.get(setup.direction.lower())
            if (
                leg
                and leg.get("symbol")
                and abs(D(str(leg.get("ask") or leg.get("ltp") or 0)) - 50) <= 5
            ):
                candidates.append((row, leg))
        contracts = []
        quotes = {}
        recent = {}
        for row, leg in candidates[:8]:
            c = Contract(
                leg["symbol"],
                "NFO",
                expiry,
                D(str(row["strike"])),
                setup.direction,
                int(leg.get("lotsize") or 0),
                D(str(leg.get("tick_size") or 0)),
            )
            observed = datetime.now(IST)
            ok, depth, _ = get_depth(c.symbol, c.exchange, auth_token=auth, broker="kotak")
            levels = depth.get("data", {}) if ok else {}
            bids = levels.get("bids") or []
            asks = levels.get("asks") or []
            if not bids or not asks:
                continue
            # This is the time of an uncached broker depth read, not an invented exchange timestamp.
            q = Quote(
                c.symbol,
                D(str(bids[0].get("price") or 0)),
                D(str(asks[0].get("price") or 0)),
                int(bids[0].get("quantity") or 0),
                int(asks[0].get("quantity") or 0),
                observed,
                None,
                verified_depth_snapshot=True,
            )
            if preset.controlled:
                ok, history, _ = get_history(
                    c.symbol,
                    "NFO",
                    "1m",
                    clock.date().isoformat(),
                    clock.date().isoformat(),
                    auth_token=auth,
                    broker="kotak",
                )
                recent[c.symbol] = (
                    closed_bars(history.get("data", []), now, minutes=1) if ok else []
                )
            contracts.append(c)
            quotes[c.symbol] = q
        current = datetime.now(IST)
        selected = select_contract(
            contracts,
            quotes,
            preset,
            D(str(limit)),
            current,
            direction=setup.direction,
            index_reference=setup.index_reference,
            recent_bars=recent,
        )
        self.evaluated[owner] = close
        if not selected.ok:
            return {"error": selected.error}
        return {
            "setup": setup,
            "selection": selected,
            "available_limit": str(limit),
            "observed_at": current.isoformat(),
        }
