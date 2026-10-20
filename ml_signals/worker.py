"""ML worker process: live snapshots and scheduled retraining."""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from utils.logging import get_logger

logger = get_logger(__name__)


def _now_ist() -> datetime:
    import pytz

    return datetime.now(pytz.timezone("Asia/Kolkata"))


def _symbols_from_settings() -> list[str]:
    from database.ml_settings_db import get_settings
    from ml_signals.data import normalize_symbol

    settings = get_settings()
    raw = settings.get("symbols") or []
    out: list[str] = []
    for value in raw:
        try:
            symbol = normalize_symbol(str(value))
        except Exception:
            continue
        if symbol not in out:
            out.append(symbol)
    return out or ["BTCUSD", "ETHUSD", "SOLUSD"]


def _run_train_child(symbol: str) -> dict[str, Any]:
    from database.ml_settings_db import get_settings
    from ml_signals import predict, train

    settings = get_settings()
    config = train.TrainConfig(
        hold_minutes=min(28, max(1, int(settings.get("max_hold_minutes", 28)))),
        sentiment_enabled=True,
    )
    metrics = predict.run_training(config, symbol=symbol)
    # The newest model drives signals straight away. Live trading is gated on
    # its promotion separately, so activating an unpromoted one is safe.
    train.activate_model(str(metrics["version"]), symbol=symbol)
    return {
        "symbol": symbol,
        "version": metrics["version"],
        "promoted": bool(metrics.get("promoted", False)),
        "promotion_reason": metrics.get("promotion_reason"),
    }


def _run_retrain_for_symbol(symbol: str, timeout_s: int = 3600) -> dict[str, Any]:
    """Train one symbol in a child process, so its CPU and memory end with it.

    Output goes to the worker's own log file rather than a pipe: a pipe that
    nobody drains fills up and blocks the child.
    """
    from services.ml_worker_manager import LOG_FILE

    cmd = [sys.executable, "-m", "ml_signals.worker", "train-symbol", "--symbol", symbol]
    started = time.time()
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as log:
        process = subprocess.Popen(
            cmd,
            cwd=str(Path(__file__).resolve().parents[1]),
            env=os.environ.copy(),
            stdout=log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
        )
        try:
            returncode = process.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            returncode = -9
    from ml_signals.worker_store import read_train_result

    result = read_train_result(symbol) or {}
    payload: dict[str, Any] = {
        "symbol": symbol,
        "ok": returncode == 0,
        "elapsed_s": round(time.time() - started, 1),
        **result,
    }
    if returncode != 0 and "error" not in payload:
        payload["error"] = (
            "Training stopped after an hour without finishing."
            if returncode == -9
            else "Training stopped with an error. Details are in log/ml_worker.log."
        )
    return payload


def _train_symbol_command(symbol: str) -> int:
    from ml_signals.worker_store import write_train_result

    try:
        value = _run_train_child(symbol)
        write_train_result(symbol, {"state": "complete", **value, "updated_at": time.time()})
        return 0
    except Exception as exc:
        logger.exception("Training child failed for %s", symbol)
        write_train_result(
            symbol,
            {"state": "failed", "symbol": symbol, "error": str(exc), "updated_at": time.time()},
        )
        return 1


class MlWorker:
    """One loop, once a second: publish signals, manage open trades, retrain on schedule.

    Retraining runs in a child process on its own thread, so the snapshots
    and the smart exit keep their one-second cadence while a model trains.
    """

    def __init__(self) -> None:
        from ml_signals import data

        self._stop = threading.Event()
        self._settings_refresh_at = 0.0
        self._settings: dict[str, Any] = {}
        self._symbols: list[str] = ["BTCUSD", "ETHUSD", "SOLUSD"]
        self._next_train_for: dict[str, float] = {}
        self._intervals = ("1m", "3m", "5m", "15m")
        self._last_status: dict[str, Any] = {"worker": "ml-signals", "state": "starting"}
        self._clock = time.time
        self._sources_for = data.sources_for
        self._train_queue: list[str] = []
        self._training: threading.Thread | None = None
        self._training_symbol: str | None = None
        self._exit_state: dict[str, dict[str, Any]] = {}
        self._next_manage_at = 0.0
        self._next_reconcile_at = 0.0

    def stop(self) -> None:
        self._stop.set()

    def _refresh_settings(self) -> None:
        from database.ml_settings_db import get_settings
        from ml_signals.data import normalize_symbol
        from ml_signals.train import current_version

        now = self._clock()
        if now < self._settings_refresh_at:
            return
        settings = get_settings()
        self._settings = settings
        self._settings_refresh_at = now + 10

        symbols = []
        for value in settings.get("symbols") or []:
            try:
                symbol = normalize_symbol(str(value))
            except Exception:
                continue
            if symbol not in symbols:
                symbols.append(symbol)
        added = [s for s in symbols if s not in self._symbols]
        if symbols:
            self._symbols = symbols
        # A symbol with no model yet is trained straight away rather than at
        # the next nightly slot: there is nothing to suggest until it is.
        for symbol in self._symbols:
            if current_version(symbol) is None or symbol in added:
                self._queue_training(symbol)

        hour = int(settings.get("retrain_hour_ist", 3))
        minute = int(settings.get("retrain_minute_ist", 30))
        enabled = bool(settings.get("retrain_enabled", True))
        self._schedule_next_retrain(hour, minute, enabled)

    def _schedule_next_retrain(self, hour: int, minute: int, enabled: bool) -> None:
        from datetime import timedelta

        if not enabled:
            self._next_train_for = {}
            return
        now_ist = _now_ist()
        base = now_ist.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if base <= now_ist:
            base = base + timedelta(days=1)
        when = base.timestamp()
        for symbol in self._symbols:
            self._next_train_for.setdefault(symbol, when)
        for symbol in [s for s in self._next_train_for if s not in self._symbols]:
            del self._next_train_for[symbol]

    def _status(self, **values: Any) -> None:
        from ml_signals.worker_store import write_status

        self._last_status.update(values)
        self._last_status["updated_at"] = self._clock()
        self._last_status["training"] = self._training_symbol
        self._last_status["training_queue"] = list(self._train_queue)
        write_status(dict(self._last_status))

    def _refresh_data(self, symbol: str) -> dict[str, Any]:
        from ml_signals import data

        refreshed, failed = 0, []
        for name in tuple(self._sources_for(symbol)):
            if self._stop.is_set():
                break
            try:
                data.download_source(name, days=365, symbol=symbol)
                refreshed += 1
            except Exception as exc:
                logger.warning("History refresh for %s %s failed: %s", symbol, name, exc)
                failed.append(name)
        return {"symbol": symbol, "sources": refreshed, "failed": failed}

    # -- live snapshots -----------------------------------------------------

    def _build_live_snapshot(self, symbol: str, interval: str) -> dict[str, Any]:
        from ml_signals import live

        view = live.get_engine(symbol).snapshot(interval)
        if view is None:
            return {
                "state": "starting",
                "symbol": symbol,
                "interval": interval,
                "feed": "No data yet.",
                "server_time": self._clock(),
                "sources": {},
            }
        if interval == '1m':
            try:
                from ml_signals.fee_algo_runtime import observe
                frames = live.recent_frames(symbol)
                from ml_signals.data import PRICE_SOURCE
                frame = frames.get(PRICE_SOURCE)
                if frame is not None and not frame.empty:
                    view['fee_algo'] = observe(symbol, frame, self._clock())
            except Exception as exc:
                view['fee_algo'] = {'action': 'HOLD', 'reason': f'Fee-aware model unavailable: {type(exc).__name__}'}
        return view

    def _publish_live(self) -> None:
        from ml_signals.worker_store import write_live_snapshot

        for symbol in self._symbols:
            for interval in self._intervals:
                write_live_snapshot(symbol, interval, self._build_live_snapshot(symbol, interval))

    # -- retraining ---------------------------------------------------------

    def _queue_training(self, symbol: str) -> None:
        if symbol != self._training_symbol and symbol not in self._train_queue:
            self._train_queue.append(symbol)

    def _run_due_retrains(self) -> None:
        from ml_signals.worker_store import take_requests

        now = self._clock()
        for symbol in take_requests():
            try:
                from ml_signals.data import normalize_symbol

                self._queue_training(normalize_symbol(symbol))
            except ValueError:
                continue
        for symbol, at in list(self._next_train_for.items()):
            if at <= now:
                self._queue_training(symbol)
                self._next_train_for[symbol] = at + 24 * 3600
        if self._training is not None and self._training.is_alive():
            return
        self._training = None
        self._training_symbol = None
        if not self._train_queue or self._stop.is_set():
            return
        symbol = self._train_queue.pop(0)
        self._training_symbol = symbol
        self._training = threading.Thread(
            target=self._retrain, args=(symbol,), name=f"ml-train-{symbol}", daemon=True
        )
        self._training.start()

    def _retrain(self, symbol: str) -> None:
        from database.ml_settings_db import set_internal

        self._status(message=f"Saving history and retraining {symbol}")
        try:
            history = self._refresh_data(symbol)
            if self._stop.is_set():
                return
            result = _run_retrain_for_symbol(symbol)
            if result.get("ok"):
                text = (
                    f"{symbol} {result.get('version')}: "
                    + ("Live allowed. " if result.get("promoted") else "Sandbox only. ")
                    + str(result.get("promotion_reason") or "")
                )
            else:
                text = f"{symbol}: {result.get('error') or 'training failed'}"
            set_internal(last_retrain_status=text)
            self._status(last_train={"history": history, "train": result})
        except Exception as exc:
            logger.exception("Retraining failed for %s", symbol)
            set_internal(last_retrain_status=f"{symbol}: training failed. See log/ml_worker.log.")
            self._status(last_train={"symbol": symbol, "error": str(exc)})

    # -- open trades --------------------------------------------------------

    def _manage_trades(self) -> None:
        """Smart exits and broker reconciliation, through Flask's own endpoint.

        The worker holds no strategy state: open legs live in the web
        process. It asks Flask for them, decides here with the pure rules in
        ml_signals.exits, and sends each exit back through the strategy's
        local webhook so it is audited like any other signal.
        """
        now = self._clock()
        if now < self._next_manage_at:
            return
        self._next_manage_at = now + MANAGE_SECONDS
        from ml_signals import local_api

        trades = local_api.open_trades()
        if trades is None:
            return
        if any(t.get("mode") == "live" for t in trades) and now >= self._next_reconcile_at:
            self._next_reconcile_at = now + RECONCILE_SECONDS
            for settled in local_api.reconcile():
                logger.info("Delta no longer holds %s; its ML leg was marked closed", settled)
        open_keys = {t["key"] for t in trades}
        for key in [k for k in self._exit_state if k not in open_keys]:
            del self._exit_state[key]
        self._prune_trade_meta(open_keys)
        if not bool(self._settings.get("smart_exit_enabled", True)):
            return
        for trade in trades:
            self._smart_exit(trade, now)

    def _prune_trade_meta(self, open_keys: set[str]) -> None:
        """Forget closed trades, keeping a recent one a moment in case its entry is still filling."""
        from ml_signals.worker_store import read_trades, update_trades

        now = self._clock()
        stale = [
            key
            for key, meta in read_trades().items()
            if key not in open_keys and now - float(meta.get("opened_at") or 0) > 120
        ]
        if stale:
            update_trades(lambda trades: {k: v for k, v in trades.items() if k not in stale})

    def _smart_exit(self, trade: dict[str, Any], now: float) -> None:
        from ml_signals import local_api
        from ml_signals.exits import decide_exit
        from ml_signals.worker_store import read_live_snapshot

        if trade.get("entry_status") != "complete" or trade.get("exit_kind"):
            return
        interval = trade.get("interval") or "5m"
        snapshot = read_live_snapshot(trade["symbol"], interval) or {}
        notional = float(trade.get("contracts") or 0) * float(trade.get("contract_value") or 0)
        notional *= float(trade.get("last_price") or 0)
        fee_now = float(trade.get("exit_fee_now") or 0) / notional * 100 if notional else 0.0
        fee_after = (
            float(trade.get("exit_fee_after_window") or 0) / notional * 100 if notional else 0.0
        )
        memory = self._exit_state.setdefault(trade["key"], {"streak": 0, "last_bar": None})
        decision = decide_exit(
            side=trade["side"],
            opened_at=float(trade.get("opened_at") or now),
            now=now,
            signal=snapshot.get("closed"),
            pnl_pct=float(trade.get("pnl_pct") or 0),
            exit_fee_pct_now=fee_now,
            exit_fee_pct_after_window=fee_after,
            window_remaining_minutes=trade.get("window_remaining_minutes"),
            max_hold_minutes=float(self._settings.get("max_hold_minutes", 28)),
            confirmations=int(self._settings.get("smart_exit_confirmations", 2)),
            streak=memory["streak"],
            last_bar=memory["last_bar"],
        )
        memory.update(streak=decision.streak, last_bar=decision.last_bar)
        if not decision.close or memory.get("sent"):
            return
        memory["sent"] = True
        logger.info("Smart exit for %s: %s", trade["key"], decision.detail)
        if not local_api.send_exit(trade, decision.reason or "smart_exit", decision.detail or ""):
            memory["sent"] = False

    # -- loop ---------------------------------------------------------------

    def run(self) -> None:
        from ml_signals.worker_store import write_status

        write_status({"worker": "ml-signals", "state": "starting", "updated_at": self._clock()})
        self._status(state="live", message="Worker started")
        parent = os.getppid()
        while not self._stop.is_set():
            # The web process starts this one in its own session, so a crash or
            # a kill of the web process would otherwise leave it running: a
            # second worker after the next start, both writing snapshots and
            # both sending exits. Re-parented means the web process is gone.
            if os.getppid() != parent:
                logger.info("The web process that started the ML worker has gone; stopping")
                break
            started = self._clock()
            try:
                self._refresh_settings()
                self._publish_live()
                self._manage_trades()
                self._run_due_retrains()
                self._status(state="live", symbols=self._symbols, message="Live snapshots updated")
            except Exception as exc:
                logger.exception("ML worker tick failed")
                self._status(state="failed", error=str(exc))
            elapsed = self._clock() - started
            self._stop.wait(max(0.05, 1.0 - elapsed))


#: How often open trades are checked against the model.
MANAGE_SECONDS = 2.0
#: How often Live trades are checked against what Delta actually holds. Each
#: check is one private API call, so it is kept well inside Delta's limits.
RECONCILE_SECONDS = 10.0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="OpenAlgo ML worker")
    parser.add_argument("command", nargs="?", default="run", choices=("run", "train-symbol"))
    parser.add_argument("--symbol", default="BTCUSD")
    args = parser.parse_args(argv)

    if args.command == "train-symbol":
        return _train_symbol_command(args.symbol)

    worker = MlWorker()

    def _signal_stop(signum, _frame):
        logger.info("ML worker received signal %s", signum)
        worker.stop()

    signal.signal(signal.SIGTERM, _signal_stop)
    signal.signal(signal.SIGINT, _signal_stop)

    try:
        worker.run()
    finally:
        from ml_signals import live, local_api

        live._stop_engines()
        local_api.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
