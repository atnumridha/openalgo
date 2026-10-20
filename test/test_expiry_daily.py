from scripts.research.video_reversal.daily import daily_rows


def test_daily_accounting_preserves_unknown_exit_and_blocks_later_days():
    case = {
        "trades": [
            {
                "session": "2026-10-05",
                "lots": 1,
                "gross": 110,
                "fees": 10,
                "net": 100,
                "cash_after": 30100,
            },
            {
                "session": "2026-10-06",
                "lots": 1,
                "gross": None,
                "fees": None,
                "net": None,
                "cash_after": None,
            },
        ]
    }
    rows = daily_rows(
        case,
        ["2026-10-05", "2026-10-06", "2026-10-07"],
        30000,
        lambda d, c: ("No eligible setup", 0),
    )
    assert rows[0]["net"] == 100 and rows[0]["closing_capital"] == 30100
    assert rows[1]["net"] is None and rows[1]["status"] == "Unresolved exit"
    assert rows[2]["net"] is None and rows[2]["status"] == "Not evaluated after unresolved trade"


def test_missing_premiums_are_not_zero_daily_profit():
    rows = daily_rows(
        {"trades": []}, ["2026-09-21"], 30000, lambda d, c: ("Missing option premiums", None)
    )
    assert rows[0]["net"] is None
    assert rows[0]["closing_capital"] == 30000
