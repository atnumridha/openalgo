from scripts.research.video_reversal.capital import affordable_lots
from scripts.research.video_reversal.expiry_rupees import replay


def test_maximum_lots_include_entry_charges_and_cannot_overspend():
    def entry_fee(value):
        return value * 0.001

    lots = affordable_lots(30000, 150, 65, entry_fee)
    assert lots == 3
    assert lots * 65 * 150 + entry_fee(lots * 65 * 150) <= 30000
    assert (lots + 1) * 65 * 150 + entry_fee((lots + 1) * 65 * 150) > 30000
    assert affordable_lots(9750, 150, 65, entry_fee) == 0


def test_delayed_trail_waits_for_two_r_then_protects_one_r():
    p = {"entry": 100, "stop": 95, "target": 150, "risk_rupees": 5}
    rows = [
        {
            "timestamp": 60 + i * 60,
            "open": v,
            "high": v + 1,
            "low": v - 0.1,
            "close": v,
            "volume": 10,
        }
        for i, v in enumerate([106, 111, 110])
    ]
    t = replay(
        rows,
        60,
        240,
        p,
        1,
        lambda b, s: 0,
        0.05,
        trailing={"activation_r": 2, "gap_r": 1.5, "minimum_lock_r": 1},
    )
    assert t["stop_updates"][0]["effective_from"] == 180
    assert t["stop_updates"][0]["protected_net"] >= 5
    assert len(t["stop_updates"]) == 1


def test_other_expiry_events_never_trade_after_expiry_or_outside_requested_period():
    from scripts.research.video_reversal.capital import event_in_window

    study = {"expiry": "2026-10-13", "requested_period": ["2026-09-19", "2026-10-18"]}
    assert event_in_window({"session": "2026-10-13"}, study)
    assert not event_in_window({"session": "2026-10-14"}, study)
    assert not event_in_window({"session": "2026-09-18"}, study)


def test_risk_cap_reduces_lots_and_preserves_atr_stop():
    from scripts.research.video_reversal.capital import risk_limited_plan

    lots, plan = risk_limited_plan(30000, 100, 3, 65, 0.05, 2, lambda buy, sell: 10, 1000)
    assert lots == 3
    assert plan["risk_rupees"] <= 1000
    assert plan["stop"] == 95.6
    assert 4 * ((plan["entry"] - plan["stop"] + 0.1) * 65) + 10 > 1000


def test_risk_cap_skips_when_one_lot_cannot_fit():
    from scripts.research.video_reversal.capital import risk_limited_plan

    lots, plan = risk_limited_plan(30000, 100, 12, 65, 0.05, 2, lambda buy, sell: 10, 1000)
    assert lots == 0 and plan is None


def test_missing_expired_premiums_are_not_reported_as_zero_profit(tmp_path, monkeypatch):
    import json

    from scripts.research.video_reversal.capital import main

    (tmp_path / "events.json").write_text("[]")
    (tmp_path / "contracts-current.json").write_text("[]")
    (tmp_path / "study.json").write_text(
        json.dumps(
            {
                "expiry": "2026-09-22",
                "requested_period": ["2026-09-19", "2026-09-22"],
                "modes": ["fixed", "delayed"],
                "coverage_note": "No premium archive.",
            }
        )
    )
    monkeypatch.setattr("sys.argv", ["capital", str(tmp_path), "--max-loss", "1000"])
    main()
    r = json.loads((tmp_path / "capital-30000-maxlots-risk1000/results.json").read_text())
    assert all(c["entries"] == 0 and c["net"] is None for c in r["cases"])
