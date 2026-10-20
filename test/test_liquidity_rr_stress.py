from scripts.research.video_reversal.rr import levels


def test_minimum_two_r_uses_actual_entry_risk_and_rejects_less_room():
    p = {"first_r": 2, "runner_r": 5, "first_fraction": 0.8, "min_room_r": 2}
    c = {"side": "long", "stop": 90, "target": 120}
    plan = levels(c, 100, p, 0.05)
    assert plan["target"] == 120 and plan["runner_target"] == 150
    assert plan["first_fraction"] == 0.8
    assert levels(dict(c, target=119.95), 100, p, 0.05) is None
    assert levels(c, 101, p, 0.05) is None  # Risk/reward must use actual observed entry.


def test_short_and_full_ten_r_targets_do_not_move_stop():
    c = {"side": "short", "stop": 210, "target": 180}
    p = {"first_r": 10, "runner_r": None, "first_fraction": 1, "min_room_r": 2}
    plan = levels(c, 200, p, 0.05)
    assert plan["target"] == 100 and plan["first_fraction"] == 1
    assert c["stop"] == 210
    assert levels({"side": "short", "stop": 110, "target": 80}, 100, p, 0.05) is None


def test_partial_runner_cash_weights_and_original_stop(monkeypatch):
    from scripts.research.video_reversal import kotak

    b = {"time": 120, "open": 100, "high": 200, "low": 90, "close": 100}
    c = {
        "id": "rr",
        "side": "long",
        "known": 120,
        "expires": 180,
        "trigger": 99.95,
        "stop": 90,
        "target": 160,
    }
    policy = {"first_r": 2, "runner_r": 5, "first_fraction": 0.8, "min_room_r": 2}
    monkeypatch.setattr(kotak, "path", lambda b, order: iter([(120, 100), (121, 120), (122, 150)]))
    trades, _ = kotak.simulate_session([b], {120: [c]}, "low-first", rr_policy=policy)
    assert trades[0]["stop"] == 90
    assert abs(trades[0]["r_multiple"] - 2.6) < 1e-9
    assert trades[0]["reason"] == "runner_target"
    monkeypatch.setattr(kotak, "path", lambda b, order: iter([(120, 100), (121, 120), (122, 90)]))
    trades, _ = kotak.simulate_session([b], {120: [c]}, "low-first", rr_policy=policy)
    assert abs(trades[0]["r_multiple"] - 1.4) < 1e-9
    ten = dict(policy, runner_r=10)
    monkeypatch.setattr(kotak, "path", lambda b, order: iter([(120, 100), (121, 120), (122, 200)]))
    trades, _ = kotak.simulate_session([b], {120: [c]}, "low-first", rr_policy=ten)
    assert abs(trades[0]["r_multiple"] - 3.6) < 1e-9


def test_projected_maximum_target_rounds_within_selected_five_or_ten_r_cap():
    for side, entry, stop, swing in [("long", 100.01, 90, 130), ("short", 199.99, 210, 170)]:
        sign = 1 if side == "long" else -1
        for maximum in [5, 10]:
            p = {"first_r": maximum, "runner_r": None, "first_fraction": 1, "min_room_r": 2}
            plan = levels({"side": side, "stop": stop, "target": swing}, entry, p, 0.05)
            actual = sign * (plan["target"] - entry) / abs(entry - stop)
            assert 2 <= actual <= maximum + 1e-9
