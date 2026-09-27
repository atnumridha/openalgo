from datetime import datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from services.strategy_module import scalping


def daily_rows(now, count=310):
    dates = pd.bdate_range(end=now.date() - timedelta(days=1), periods=count, tz=scalping.IST)
    return [
        {"timestamp": d.isoformat(), "open": 100, "high": 102, "low": 99, "close": 101}
        for d in dates
    ]


def test_daily_history_excludes_current_and_future_closes_and_requires_previous_session(
    monkeypatch,
):
    from database import market_calendar_db

    monkeypatch.setattr(
        market_calendar_db,
        "get_effective_session_window",
        lambda d, _: {"start_ms": 1} if d.weekday() < 5 else None,
    )
    now = datetime(2026, 9, 28, 10, 0, tzinfo=scalping.IST)
    rows = daily_rows(now)
    forming = rows[-1] | {"timestamp": now.isoformat(), "close": 90000}
    f = scalping.closed_daily_frame(rows + [forming], now)
    assert len(f) == 310 and f.index.max().date().isoformat() == "2026-09-25"
    with pytest.raises(scalping.WaitingForSignal, match="previous trading session"):
        scalping.closed_daily_frame(rows[:-1], now)
    with pytest.raises(scalping.WaitingForSignal, match="272"):
        scalping.closed_daily_frame(rows[-271:], now)


def test_daily_history_duplicate_and_invalid_rows_are_not_filled(monkeypatch):
    from database import market_calendar_db

    monkeypatch.setattr(
        market_calendar_db, "get_effective_session_window", lambda *_: {"start_ms": 1}
    )
    now = datetime(2026, 9, 25, 10, tzinfo=scalping.IST)
    rows = daily_rows(now)
    with pytest.raises(ValueError):
        scalping.closed_daily_frame(rows + [rows[-1]], now)
    rows[20]["close"] = float("nan")
    with pytest.raises(ValueError):
        scalping.closed_daily_frame(rows, now)


def test_regime_adapter_matches_frozen_research_signal_function():
    from services.research.groww_algorithmic import features, signals

    index = pd.date_range("2025-06-20 09:20", periods=350, freq="5min", tz=scalping.IST)
    close = 100 + np.random.default_rng(1).normal(size=len(index)).cumsum()
    five = pd.DataFrame(
        {"open": close, "high": close + 1, "low": close - 1, "close": close}, index=index
    )
    dates = pd.bdate_range(end="2025-06-19", periods=400, tz=scalping.IST)
    daily = pd.DataFrame({"close": np.linspace(80, 100, len(dates))}, index=dates)
    want = signals(features(five, daily), "timing_50_200")
    got = scalping.signals_for_profile("regime50200", five=five, daily=daily)
    pd.testing.assert_series_equal(got.direction, want.direction)
    pd.testing.assert_series_equal(got.stop_price, want.stop_price)


def test_box_waits_for_closed_opening_range_and_uses_premium_exits():
    index = pd.date_range("2026-09-25 09:16", periods=30, freq="min", tz=scalping.IST)
    minute = pd.DataFrame({"open": 100.0, "high": 111.0, "low": 89.0, "close": 100.0}, index=index)
    minute.loc[index[15], ["open", "high", "low", "close"]] = [109, 115, 108, 114]
    f = scalping.signals_for_profile("box15", minute=minute)
    assert f.direction.iloc[:15].eq("").all() and f.direction.iloc[15] == "CE"
    signal = f.iloc[15].to_dict() | {"timestamp": index[15].isoformat()}
    context = scalping.trade_context("box15", signal, None)
    assert context["exit_basis"] == "option_premium"
    assert scalping.exit_reason(context, index[16].to_pydatetime(), 100000) is None
    assert (
        scalping.exit_reason(context, index[15].to_pydatetime() + timedelta(minutes=15), None)
        == "scheduler"
    )


@pytest.mark.parametrize(
    "profile,minimum_days,target",
    [
        ("box15", 0, 20),
        ("regime50200", 0, None),
        ("ema915", 1, None),
        ("macd200", 1, None),
        ("ema5", 1, None),
    ],
)
def test_protection_preserves_profile_expiry_and_target(profile, minimum_days, target, monkeypatch):
    monkeypatch.setattr(scalping, "quote_price", lambda *_: 150)
    monkeypatch.setattr(scalping, "require_option_liquidity", lambda *_: None, raising=False)
    leg = {
        "expiry": (datetime.now(scalping.IST) + timedelta(days=minimum_days)).strftime("%d-%b-%y"),
        "quantity": 75,
        "lot_size": 75,
        "symbol": "NIFTYCE",
        "exchange": "NFO",
    }
    context = {"profile": profile, "signal_at": datetime.now(scalping.IST).isoformat()}
    out = scalping.protect_leg(leg, context, None)
    assert out["target_pts"] == target
    assert context["premium_target_points"] == target
    if profile == "box15":
        assert out["sl_pts"] == 10 and out["risk_unit"] == "points"
    else:
        assert out["sl_pts"] * 75 <= 800


def test_option_liquidity_uses_last_completed_five_minute_quote(monkeypatch):
    from services import indicator_service

    now = datetime(2026, 9, 25, 10, 5, 10, tzinfo=scalping.IST)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now

    monkeypatch.setattr(scalping, "datetime", Clock)
    at = pd.Timestamp(now).floor("5min")
    records = [
        {
            "timestamp": (at - pd.Timedelta(minutes=5)).isoformat(),
            "open": 100,
            "high": 102,
            "low": 99,
            "close": 101,
            "volume": 749,
        }
    ]
    monkeypatch.setattr(
        indicator_service,
        "fetch_history_cached",
        lambda *a, **k: {"status": "success", "data": records},
    )
    leg = {"symbol": "NIFTYCE", "exchange": "NFO", "lot_size": 75}
    context = {"signal_at": at.isoformat()}
    with pytest.raises(scalping.WaitingForSignal, match="liquidity"):
        scalping.require_option_liquidity(leg, context, SimpleNamespace())
    records[0]["volume"] = 750
    scalping.require_option_liquidity(leg, context, SimpleNamespace())
    records[0]["timestamp"] = (at - pd.Timedelta(minutes=10)).isoformat()
    with pytest.raises(scalping.WaitingForSignal, match="completed option candle"):
        scalping.require_option_liquidity(leg, context, SimpleNamespace())


def test_yesterdays_profiles_remain_valid_but_are_not_reinstalled_by_shortlist(monkeypatch):
    from blueprints.strategy_module import validate_strategy_config
    from services.strategy_module.scalping_pack import definitions

    for profile in ("macd200", "ema5"):
        row = next(r for r in definitions() if r["scalp_profile"] == "ema915") | {
            "scalp_profile": profile
        }
        assert validate_strategy_config(row)[1] is None
        assert profile in scalping.PROFILES
    assert not {"macd200", "ema5"} & {r["scalp_profile"] for r in definitions()}
    five = pd.DataFrame(index=range(604))
    minute = pd.DataFrame(index=range(60))
    marker = object()
    monkeypatch.setattr(scalping, "macd_features", lambda f: f, raising=False)
    monkeypatch.setattr(
        scalping, "macd_signals", lambda f: marker if f is five else None, raising=False
    )
    monkeypatch.setattr(
        scalping,
        "ema_reversal_signals",
        lambda f, m: marker if f is five and m is minute else None,
        raising=False,
    )
    assert scalping.signals_for_profile("macd200", five=five) is marker
    assert scalping.signals_for_profile("ema5", five=five, minute=minute) is marker


@pytest.mark.parametrize(
    "profile,requests",
    [
        ("box15", [("NIFTY", "1m")]),
        ("regime50200", [("NIFTY", "5m"), ("NIFTY", "D")]),
        ("ema915", [("NIFTY", "5m"), ("BANKNIFTY", "5m")]),
        ("macd200", [("NIFTY", "5m")]),
        ("ema5", [("NIFTY", "5m"), ("NIFTY", "1m")]),
    ],
)
def test_latest_signal_requests_only_each_profiles_required_candles(monkeypatch, profile, requests):
    from services import indicator_service

    now = datetime(2026, 9, 25, 10, 5, 10, tzinfo=scalping.IST)
    at = pd.Timestamp(now).floor("5min")
    calls = []
    frame = pd.DataFrame({"direction": ["CE"], "low": [90], "high": [110]}, index=[at])

    def fetch(client, symbol, exchange, interval, *args, **kwargs):
        calls.append((symbol, interval))
        return {"status": "success", "data": []}

    monkeypatch.setattr(indicator_service, "fetch_history_cached", fetch)
    monkeypatch.setattr(
        indicator_service,
        "current_completed_bar_start",
        lambda interval, *args: at - pd.Timedelta(minutes=1 if interval == "1m" else 5),
    )
    monkeypatch.setattr(scalping, "closed_frame", lambda *args: frame)
    monkeypatch.setattr(scalping, "closed_daily_frame", lambda *args: frame)
    monkeypatch.setattr(scalping, "signals_for_profile", lambda *args, **kwargs: frame)
    assert scalping.latest_signal(profile, None, now)["direction"] == "CE"
    assert calls == requests


def test_shortlist_install_preserves_yesterdays_saved_rows_and_flows(monkeypatch):
    from uuid import uuid4

    from blueprints.strategy_module import validate_strategy_config
    from database import flow_db
    from database import strategy_module_db as store
    from services.strategy_module import scalping_pack as pack

    owner, connection = "shortlist-test-" + uuid4().hex, str(uuid4())
    store.init_db()
    flow_db.init_db()
    monkeypatch.setattr(pack, "_connection_for_owner", lambda *_: connection)
    template = next(r for r in pack.definitions() if r["scalp_profile"] == "ema915")
    retained = {}
    try:
        for profile in ("ema915", "macd200", "ema5"):
            config, error = validate_strategy_config(
                template
                | {
                    "name": scalping.PROFILES[profile],
                    "scalp_profile": profile,
                    "broker_connection_id": connection,
                }
            )
            assert error is None
            row, error = store.create_strategy(owner, config)
            assert error is None
            row.pop("webhook_token", None)
            graph = pack.workflow_definition(row, row["id"], owner, connection)
            flow = flow_db.create_workflow(**graph)
            retained[row["id"]] = (row, flow.id, flow.nodes)
        result = pack.install(owner)
        assert len(result["created"]) == 2 and len(result["existing"]) == 1
        assert len(store.list_strategies(owner)) == 5
        again = pack.install(owner)
        assert again["created"] == [] and len(again["existing"]) == 3
        for sid, (before, fid, nodes) in retained.items():
            assert store.strategy_to_dict(store.get_strategy(sid, owner)) == before
            flow = flow_db.get_workflow(fid)
            assert flow.nodes == nodes and not flow.is_active
    finally:
        for row in store.list_strategies(owner):
            for flow in flow_db.get_workflows_for_strategy(row["id"]):
                flow_db.delete_workflow(flow.id)
            store.delete_strategy(row["id"], owner)
        store.db_session.remove()
        flow_db.db_session.remove()
