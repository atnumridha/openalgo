import unittest

from services.delta_chart.ema import ema_backfill


class EmaTests(unittest.TestCase):
    def test_sma_seed_then_exponential_weight(self):
        result = ema_backfill([{"time": i * 60, "close": 100 + i} for i in range(16)])
        self.assertEqual(result["9"]["points"][0], {"time": 480, "value": 104})
        self.assertEqual(result["9"]["points"][1]["value"], 105)
        self.assertEqual(result["15"]["points"][0]["value"], 107)

    def test_short_history_returns_seed_for_latest_candle(self):
        state = ema_backfill([{"time": 60, "close": 100}])["9"]
        self.assertEqual(state, {"points": [], "count": 1, "sum": 100, "value": None})

    def test_invalid_unordered_or_excessive_history_rejected(self):
        for bars in (
            [{"time": 1, "close": float("nan")}],
            [{"time": 1, "close": 0}],
            [{"time": 2, "close": 1}, {"time": 1, "close": 1}],
            [{}],
            [None],
            [{}] * 10001,
        ):
            with self.assertRaises(ValueError):
                ema_backfill(bars)

    def test_backend_owns_crosses_direction_and_bounded_cache(self):
        from services.delta_chart.ema import _calculate
        bars = [{"time":i*60,"close":100 + (i if i<30 else 60-i)} for i in range(70)]
        first = ema_backfill(bars)
        self.assertEqual(first["algorithm"], "sma-seeded-ema-9-15-v1")
        self.assertEqual(first["direction"], "down")
        self.assertTrue(any(c["side"] == "down" for c in first["crosses"]))
        before = _calculate.cache_info().hits
        again = ema_backfill(bars)
        self.assertEqual(_calculate.cache_info().hits, before + 1)
        self.assertEqual(first, again)
        first["9"]["points"][0]["value"] = -1
        self.assertGreater(ema_backfill(bars)["9"]["points"][0]["value"], 0)
        self.assertEqual(_calculate.cache_info().maxsize, 8)

    def test_ema21_sma_seed_recursion_and_independent_cached_copy(self):
        bars = [{"time": i * 60, "close": 100 + i} for i in range(21)]
        self.assertEqual(ema_backfill(bars[:20])["21"]["points"], [])
        result = ema_backfill(bars + [{"time": 1260, "close": 132}])
        self.assertEqual(result["21"]["points"], [
            {"time": 1200, "value": 110}, {"time": 1260, "value": 112}])
        result["21"]["points"][0]["value"] = -1
        result["21"]["count"] = -1
        again = ema_backfill(bars + [{"time": 1260, "close": 132}])
        self.assertEqual(again["21"]["points"][0]["value"], 110)
        self.assertEqual(again["21"]["count"], 22)

    def test_ema21_preserves_exact_existing_9_15_values_and_cross(self):
        bars = [{"time": i * 60, "close": 100 + (i if i < 30 else 60-i)} for i in range(70)]
        result = ema_backfill(bars)
        self.assertIn("21", result)
        self.assertEqual(result["9"]["value"], 94.99867077200422)
        self.assertEqual(result["15"]["value"], 97.92336236334354)
        self.assertEqual(result["crosses"], [{"time": 2400.0, "value": 123.2289742372532, "side": "down"}])
