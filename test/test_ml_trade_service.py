"""One-click ML trades: suggestion to order, the Live gate, smart exits and reconciliation.

Orders are recorded instead of sent, through the same patch points the signal
tests use, so every check here runs the real strategy module and risk core.
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import restx_api  # noqa: F401
from database import strategy_module_db as store
from database.ml_settings_db import init_db as init_ml_settings
from database.ml_settings_db import set_internal, update_settings
from services import ml_trade_service as svc
from services.crypto_fees import ContractFees
from services.strategy_module import engine, signals, state
from services.strategy_module.order_dispatch import DispatchResult

USER = "ml_trade_test_user"
SYMBOLS = (("BTCUSDFUT", "BTCUSD", 0.001), ("ETHUSDFUT", "ETHUSD", 0.01))


@pytest.fixture(scope="module", autouse=True)
def seed_master_contract():
    from database.symbol import SymToken, db_session, init_db

    init_db()
    inserted = []
    for symbol, brsymbol, cv in SYMBOLS:
        if SymToken.query.filter_by(symbol=symbol, exchange="CRYPTO").first() is not None:
            continue
        db_session.add(
            SymToken(
                symbol=symbol,
                brsymbol=brsymbol,
                name=brsymbol,
                exchange="CRYPTO",
                brexchange="DELTAIN",
                token=brsymbol,
                expiry="",
                strike=-1.0,
                lotsize=1,
                instrumenttype="PERPFUT",
                tick_size=0.5,
                contract_value=cv,
            )
        )
        inserted.append(symbol)
    db_session.commit()
    yield
    for symbol in inserted:
        SymToken.query.filter_by(symbol=symbol, exchange="CRYPTO").delete()
    db_session.commit()
    db_session.remove()


@pytest.fixture(autouse=True)
def clean(tmp_path, monkeypatch):
    from ml_signals import worker_store

    monkeypatch.setattr(worker_store, "WORKER_DIR", tmp_path / "worker")
    monkeypatch.setattr(worker_store, "LIVE_DIR", tmp_path / "worker" / "live")
    monkeypatch.setattr(worker_store, "STATUS_FILE", tmp_path / "worker" / "status.json")
    store.db_session.remove()
    store.init_db()
    init_ml_settings()
    update_settings(
        {"symbols": ["BTCUSD", "ETHUSD"], "risk_pct": 1.0, "max_leverage": 10, "sandbox_balance_usd": 1000.0}
    )
    set_internal(sandbox_strategy_id=None, live_strategy_id=None, webhook_tokens={})
    monkeypatch.setattr(
        "services.crypto_fee_service.contract_fees",
        lambda symbol, exchange="CRYPTO": (
            ContractFees(symbol=symbol.removesuffix("FUT")),
            dict((s, cv) for s, _, cv in SYMBOLS).get(symbol, 1.0),
        ),
    )

    def purge():
        for row in store.list_strategies(USER):
            if row["current_run_id"]:
                state.clear_run_state(row["current_run_id"])
            store.set_strategy_status(row["id"], "stopped", None)
            store.delete_strategy(row["id"], USER)
        store.clear_strategy_module_cache()

    purge()
    yield
    purge()
    set_internal(sandbox_strategy_id=None, live_strategy_id=None, webhook_tokens={})


@pytest.fixture
def placed():
    seen = []

    def record(**kwargs):
        seen.append({**kwargs["order"], "_mode": kwargs.get("mode")})
        return DispatchResult(ok=True, broker_order_id=f"SB-{len(seen)}", response={})

    with (
        patch.object(signals.order_dispatch, "dispatch_order", side_effect=record),
        patch.object(signals, "_api_key_for", return_value="test-key"),
        patch.object(engine.order_dispatch, "dispatch_order", side_effect=record),
        patch.object(engine, "_api_key_for", return_value="test-key"),
        patch.object(engine, "_subscribe_run"),
        patch.object(engine, "_unsubscribe_run"),
    ):
        yield seen


def _snapshot(symbol="BTCUSD", interval="5m", action="LONG", promoted=False, price=60_000.0):
    from ml_signals.worker_store import write_live_snapshot

    now = time.time()
    signal = {
        "time": int(now) // 300 * 300 - 300,
        "action": action,
        "p_long": 0.6,
        "p_short": 0.1,
        "p_wait": 0.3,
        "ev_long_pct": 0.2,
        "ev_short_pct": -0.1,
        "ev_pct": 0.2,
        "min_edge_pct": 0.05,
        "stop_pct": 0.15,
        "target_pct": 0.4,
        "hold_minutes": 28,
    }
    write_live_snapshot(
        symbol,
        interval,
        {
            "state": "live",
            "symbol": symbol,
            "interval": interval,
            "server_time": now,
            "price": price,
            "model_version": "unit",
            "model_promoted": promoted,
            "promotion_reason": "Lost 1.20% of notional after fees over 40 trades.",
            "closed": signal,
            "forming": dict(signal, time=signal["time"] + 300),
        },
    )


def test_a_suggestion_carries_levels_size_and_fees():
    _snapshot()
    value = svc.suggestion("BTCUSD", "5m", mode="sandbox", user_id=USER)
    assert value["tradable"], value["message"]
    assert value["entry_price"] == 60_000.0
    assert value["stop_price"] == pytest.approx(60_000 * (1 - 0.0015))
    assert value["target_price"] == pytest.approx(60_000 * (1 + 0.004))
    sizing = value["sizing"]
    assert sizing["contracts"] >= 1
    assert sizing["risk_amount"] <= 10.0 + 1e-9
    assert sizing["exit_fee_in_window"] == 0.0
    assert value["expires_at"] > time.time()


def test_a_stale_snapshot_is_not_traded():
    from ml_signals.worker_store import read_live_snapshot, write_live_snapshot

    _snapshot()
    old = read_live_snapshot("BTCUSD", "5m")
    old["server_time"] = time.time() - 60
    write_live_snapshot("BTCUSD", "5m", old)
    value = svc.suggestion("BTCUSD", "5m", mode="sandbox", user_id=USER)
    assert not value["tradable"]
    assert "seconds old" in value["message"]


def test_a_sandbox_trade_opens_with_its_own_size_and_percent_levels(placed):
    _snapshot()
    result = svc.place_trade(
        user_id=USER, symbol="BTCUSD", interval="5m", mode="sandbox", expected_action="LONG"
    )
    assert result["ok"], result["message"]
    order = placed[0]
    assert order["symbol"] == "BTCUSDFUT"
    assert order["action"] == "BUY"
    assert order["product"] == "NRML"
    assert order["_mode"] == "sandbox"
    assert "bracket_stop_loss_price" not in order
    assert int(order["quantity"]) == result["suggestion"]["sizing"]["contracts"]

    strategy = store.get_strategy(result["strategy_id"], USER)
    assert strategy.name == svc.SANDBOX_NAME and not strategy.live_enabled
    engine.apply_fill(result["run_id"], result["leg_id"], 60_000.0, is_entry=True)
    leg = state.get_run_state(result["run_id"])["legs"][str(result["leg_id"])]
    assert leg["risk_unit"] == "percent"
    assert leg["sl_pts"] == pytest.approx(0.15)
    # The break-even trail arms at the round-trip fee plus the buffer.
    assert 0.1 < leg["trail_x"] < 0.4


def test_a_second_entry_on_an_open_symbol_is_refused(placed):
    _snapshot()
    first = svc.place_trade(
        user_id=USER, symbol="BTCUSD", interval="5m", mode="sandbox", expected_action="LONG"
    )
    engine.apply_fill(first["run_id"], first["leg_id"], 60_000.0, is_entry=True)
    second = svc.place_trade(
        user_id=USER, symbol="BTCUSD", interval="5m", mode="sandbox", expected_action="LONG"
    )
    assert not second["ok"]
    assert "already open" in second["message"]
    assert len(placed) == 1


def test_a_changed_signal_sends_nothing(placed):
    _snapshot(action="SHORT")
    result = svc.place_trade(
        user_id=USER, symbol="BTCUSD", interval="5m", mode="sandbox", expected_action="LONG"
    )
    assert not result["ok"] and "changed to SHORT" in result["message"]
    assert placed == []


def test_live_is_locked_until_the_model_is_promoted(placed):
    _snapshot(promoted=False)
    with patch.object(svc, "balance_for", return_value=(1000.0, None, "delta")):
        result = svc.place_trade(
            user_id=USER, symbol="BTCUSD", interval="5m", mode="live", expected_action="LONG"
        )
    assert not result["ok"]
    assert "Live is locked" in result["message"]
    assert "Lost 1.20%" in result["message"]
    assert placed == []


def test_a_promoted_live_trade_carries_a_stop_held_on_delta(placed):
    _snapshot(promoted=True)
    with patch.object(svc, "balance_for", return_value=(1000.0, None, "delta")):
        result = svc.place_trade(
            user_id=USER, symbol="BTCUSD", interval="5m", mode="live", expected_action="LONG"
        )
    assert result["ok"], result["message"]
    order = placed[0]
    assert order["_mode"] == "live"
    # Beyond the managed 0.15% stop, so the managed one fires first.
    assert float(order["bracket_stop_loss_price"]) == pytest.approx(60_000 * (1 - 0.00225), abs=0.01)
    strategy = store.get_strategy(result["strategy_id"], USER)
    assert strategy.name == svc.LIVE_NAME and strategy.live_enabled


def test_open_trades_report_net_after_fees_and_the_btc_voucher(placed):
    update_settings({"fee_diwali_offer": True})
    _snapshot()
    result = svc.place_trade(
        user_id=USER, symbol="BTCUSD", interval="5m", mode="sandbox", expected_action="LONG"
    )
    engine.apply_fill(result["run_id"], result["leg_id"], 60_000.0, is_entry=True)
    engine.process_tick("BTCUSDFUT", "CRYPTO", 60_060.0)
    trades = svc.open_trades(USER)
    assert len(trades) == 1
    trade = trades[0]
    contracts = trade["contracts"]
    gross = (60_060 - 60_000) * contracts * 0.001
    assert trade["gross_pnl"] == pytest.approx(gross)
    entry_fee = contracts * 0.001 * 60_000 * 0.0005 * 1.18
    assert trade["net_pnl"] == pytest.approx(gross - entry_fee)
    assert trade["exit_fee_now"] == 0.0
    assert trade["voucher_now"] == pytest.approx(entry_fee / 1.18)
    update_settings({"fee_diwali_offer": False})


def test_a_leg_delta_already_closed_is_settled_without_an_order(placed):
    _snapshot(promoted=True)
    with patch.object(svc, "balance_for", return_value=(1000.0, None, "delta")):
        result = svc.place_trade(
            user_id=USER, symbol="BTCUSD", interval="5m", mode="live", expected_action="LONG"
        )
    engine.apply_fill(result["run_id"], result["leg_id"], 60_000.0, is_entry=True)
    placed.clear()

    with patch.object(svc, "delta_open_sizes", return_value={"BTCUSD": 0.0}):
        settled = svc.reconcile_live(USER)

    assert [s["symbol"] for s in settled] == ["BTCUSD"]
    assert placed == []
    leg = state.get_run_state(result["run_id"])["legs"][str(result["leg_id"])]
    assert leg["status"] == "closed"


def test_a_leg_delta_still_holds_is_left_alone(placed):
    _snapshot(promoted=True)
    with patch.object(svc, "balance_for", return_value=(1000.0, None, "delta")):
        result = svc.place_trade(
            user_id=USER, symbol="BTCUSD", interval="5m", mode="live", expected_action="LONG"
        )
    engine.apply_fill(result["run_id"], result["leg_id"], 60_000.0, is_entry=True)
    with patch.object(svc, "delta_open_sizes", return_value={"BTCUSD": 5.0}):
        assert svc.reconcile_live(USER) == []
    with patch.object(svc, "delta_open_sizes", return_value=None):
        assert svc.reconcile_live(USER) == []


def test_a_smart_exit_goes_through_the_strategy_webhook(placed):
    from services.strategy_module.webhook import handle_webhook

    _snapshot()
    result = svc.place_trade(
        user_id=USER, symbol="BTCUSD", interval="5m", mode="sandbox", expected_action="LONG"
    )
    engine.apply_fill(result["run_id"], result["leg_id"], 60_000.0, is_entry=True)
    token = svc.webhook_token(USER, result["strategy_id"])
    assert token
    # Kept encrypted, and reused rather than rotated on the next call.
    assert svc.webhook_token(USER, result["strategy_id"]) == token
    outcome = handle_webhook(
        token, {"action": "long_exit", "leg_id": result["leg_id"]}, ip="127.0.0.1"
    )
    assert outcome.ok, outcome.message
    assert placed[-1]["action"] == "SELL"
    assert placed[-1]["reduce_only"] is True


def test_worker_endpoints_refuse_without_the_secret(monkeypatch):
    from blueprints import ml_signals as bp

    request = SimpleNamespace(remote_addr="127.0.0.1", headers={"X-ML-Worker-Secret": "wrong"})
    monkeypatch.setattr(bp, "request", request)
    assert bp._worker_allowed() is False
    from services.ml_worker_manager import WORKER_SECRET

    request.headers = {"X-ML-Worker-Secret": WORKER_SECRET}
    assert bp._worker_allowed() is True
    request.remote_addr = "10.0.0.5"
    assert bp._worker_allowed() is False


def test_an_unknown_contract_size_is_never_guessed(monkeypatch):
    _snapshot()
    monkeypatch.setattr("database.token_db_enhanced.get_symbol_info", lambda symbol, exchange: None)
    value = svc.suggestion("BTCUSD", "5m", mode="sandbox", user_id=USER)
    assert not value["tradable"]
    assert value["sizing"] is None
    assert "contract size" in value["message"]


def test_the_database_fallback_carries_the_contract_value():
    # The cache was the only path that read it, so a cache miss sized a BTC
    # trade as if each contract were one whole bitcoin.
    from database.token_db_enhanced import get_symbol_info_dbquery

    info = get_symbol_info_dbquery("BTCUSDFUT", "CRYPTO")
    assert info is not None
    assert info.contract_value == pytest.approx(0.001)
