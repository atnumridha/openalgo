import unittest

from services.delta_chart.entry_guard import validate_entry_candles
from services.delta_chart.service import Rejected


class EntryGuardTests(unittest.TestCase):
    def setUp(self):
        self.now = 18000
        self.bars = [
            {"time": 13200 + i * 300, "open": 78060, "high": 78080, "low": 78040, "close": 78060}
            for i in range(16)
        ]
        self.data = {
            "side": "buy",
            "price": 78070,
            "auto_protection": {"source_time": 17700, "interval_seconds": 300},
        }

    def check(self, **changes):
        validate_entry_candles(dict(self.data, **changes), self.bars, self.now)

    def test_aligned_normal_long_and_short_pass(self):
        self.check()
        self.check(side="sell", price=78050)

    def test_user_chase_78142_above_78060_with_atr40_is_blocked(self):
        with self.assertRaisesRegex(Rejected, "pullback"):
            self.check(price=78142)

    def test_short_chase_is_mirrored(self):
        with self.assertRaisesRegex(Rejected, "pullback"):
            self.check(side="sell", price=77978)

    def test_half_atr_boundary_is_allowed(self):
        self.check(price=78080)
        self.check(side="sell", price=78040)

    def test_forming_candle_does_not_confirm_or_rewrite_closed_source(self):
        self.bars.append(
            {"time": 18000, "open": 78060, "high": 79000, "low": 78060, "close": 79000}
        )
        self.check()
        with self.assertRaises(Rejected):
            self.check(auto_protection={"source_time": 18000, "interval_seconds": 300})

    def test_stale_source_and_missing_latest_closed_candle_rejected(self):
        with self.assertRaises(Rejected):
            validate_entry_candles(self.data, self.bars, self.now + 900)
        self.bars.pop()
        with self.assertRaises(Rejected):
            self.check()

    def test_gap_duplicate_and_invalid_ohlc_rejected(self):
        for patch in (
            {"time": 16001},
            {"time": 15900},
            {"low": 78090},
            {"close": float("nan")},
            {"high": -1},
        ):
            with self.subTest(patch=patch):
                bars = [dict(row) for row in self.bars]
                bars[10].update(patch)
                with self.assertRaises(Rejected):
                    validate_entry_candles(self.data, bars, self.now)

    def test_source_wrong_side_and_insufficient_evidence_rejected(self):
        for changes in (
            {"side": "invalid"},
            {"price": float("inf")},
            {"auto_protection": {"source_time": 17400, "interval_seconds": 300}},
        ):
            with self.assertRaises(Rejected):
                self.check(**changes)
        with self.assertRaises(Rejected):
            validate_entry_candles(self.data, self.bars[-14:], self.now)

    def test_sharp_closed_range_or_body_blocks_even_price_at_close(self):
        for patch in (
            {"high": 78120, "low": 78000},
            {"open": 77990, "high": 78060, "low": 77990, "close": 78060},
        ):
            bars = [dict(row) for row in self.bars]
            bars[-1].update(patch)
            with self.assertRaisesRegex(Rejected, "Sharp move"):
                validate_entry_candles(self.data, bars, self.now)

    def test_unbroken_confirmed_pivot_blocks_unconfirmed_quote_crossing(self):
        for side, field, level, price in (
            ("buy", "high", 78075, 78076),
            ("sell", "low", 78045, 78044),
        ):
            bars = [dict(row) for row in self.bars]
            # Unique 2-left/2-right pivot, comfortably inside the normal ATR allowance.
            bars[5][field] = level
            for i in (3, 4, 6, 7):
                bars[i][field] = 78070 if side == "buy" else 78050
            with self.assertRaisesRegex(Rejected, "confirmed candle"):
                validate_entry_candles(dict(self.data, side=side, price=price), bars, self.now)

    def test_forming_quote_cannot_break_pivot_but_closed_break_can(self):
        bars = [dict(row) for row in self.bars]
        for i in (3, 4, 6, 7):
            bars[i]["high"] = 78070
        bars[5]["high"] = 78075
        bars.append({"time": 18000, "open": 78060, "high": 78100, "low": 78060, "close": 78090})
        with self.assertRaises(Rejected):
            validate_entry_candles(dict(self.data, price=78076), bars, self.now)
        bars[8].update(close=78076)
        validate_entry_candles(dict(self.data, price=78076), bars, self.now)

    def test_deep_stale_pullback_is_rejected_in_both_directions(self):
        with self.assertRaises(Rejected):
            self.check(price=78019)
        with self.assertRaises(Rejected):
            self.check(side="sell", price=78101)

    def test_one_atr_pullback_boundary_is_allowed(self):
        self.check(price=78020)
        self.check(side="sell", price=78100)

    def test_manual_entry_can_override_sharp_move_and_pullback_filters(self):
        for side, price in (("buy", 78142), ("sell", 77978), ("buy", 78019), ("sell", 78101)):
            with self.subTest(side=side, price=price):
                self.check(side=side, price=price, entry_mode="manual")
                with self.assertRaisesRegex(Rejected, "pullback"):
                    self.check(side=side, price=price)

    def test_manual_override_accepts_large_closed_candle_without_affecting_auto(self):
        for patch in (
            {"high": 78120, "low": 78000},
            {"open": 77990, "high": 78060, "low": 77990, "close": 78060},
        ):
            bars = [dict(row) for row in self.bars]
            bars[-1].update(patch)
            validate_entry_candles(dict(self.data, entry_mode="manual"), bars, self.now)
            with self.assertRaisesRegex(Rejected, "Sharp move"):
                validate_entry_candles(self.data, bars, self.now)

    def test_manual_override_retains_fresh_and_valid_closed_evidence(self):
        data = dict(self.data, entry_mode="manual")
        with self.assertRaises(Rejected):
            validate_entry_candles(data, self.bars[-10:], self.now)
        with self.assertRaises(Rejected):
            validate_entry_candles(data, self.bars, self.now + 900)
        with self.assertRaises(Rejected):
            validate_entry_candles(dict(data, price=float("nan")), self.bars, self.now)
        malformed = [dict(row) for row in self.bars]
        malformed[-1]["low"] = 79000
        with self.assertRaises(Rejected):
            validate_entry_candles(data, malformed, self.now)

    def test_manual_override_keeps_unconfirmed_breakout_validation(self):
        bars = [dict(row) for row in self.bars]
        bars[5]["high"] = 78075
        for i in (3, 4, 6, 7):
            bars[i]["high"] = 78070
        with self.assertRaisesRegex(Rejected, "confirmed candle"):
            validate_entry_candles(
                dict(self.data, entry_mode="manual", price=78076), bars, self.now
            )
