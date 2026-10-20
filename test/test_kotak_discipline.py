from services.kotak_assistant.discipline import advance


def test_legacy_high_water_does_not_double_count_returning_ids():
    first = advance({}, "2026-10-16", [], 1, minimum_entries=2, known_ids=["NFO:1"])
    second = advance(first, "2026-10-16", [], 2, known_ids=["NFO:1", "NFO:2"])
    assert second["entries"] == 2
    assert not first["count_verified"] and not second["count_verified"]


def test_new_external_id_cannot_resolve_unattributed_legacy_count():
    first = advance({}, "2026-10-16", [], 1, minimum_entries=2, known_ids=["NFO:A"])
    second = advance(first, "2026-10-16", [], 2, known_ids=["NFO:B"])
    assert second["entries"] == 2 and not second["count_verified"]
    reset = advance(second, "2026-10-17", [], 3)
    assert reset["entries"] == 0 and reset["count_verified"]


def test_broker_numeric_strings_match_normalized_saved_fills():
    from services.kotak_assistant.discipline import merge_fills

    saved = {
        "orderid": "1",
        "tradeid": "1",
        "symbol": "NIFTY19OCT2623150CE",
        "exchange": "NFO",
        "product": "MIS",
        "action": "BUY",
        "quantity": 65,
        "average_price": 100.0,
        "timestamp": "16-Oct-2026 10:00:00",
    }
    raw = {**saved, "quantity": "65", "average_price": "100.00"}
    assert len(merge_fills([saved], [raw])) == 1
