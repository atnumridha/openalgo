import unittest

from services.delta_chart.fill_timing import first_entry_fill_time


class FillTimingTests(unittest.TestCase):
    def test_uses_earliest_exact_order_fill_not_order_placement(self):
        plan = {"entry_order_id": "entry", "pid": "27"}
        payload = {"side": "buy", "size": 2}
        fills = [
            {
                "id": "f1",
                "order_id": "entry",
                "product_id": 27,
                "fill_type": "normal",
                "side": "buy",
                "size": 1,
                "created_at": 100,
            },
            {
                "id": "f2",
                "order_id": "entry",
                "product_id": 27,
                "fill_type": "normal",
                "side": "buy",
                "size": 1,
                "created_at": 110,
            },
        ]
        self.assertEqual(first_entry_fill_time(plan, payload, fills, True, 200), 100)
        self.assertIsNone(first_entry_fill_time(plan, payload, fills, False, 200))
        self.assertEqual(first_entry_fill_time(plan, payload, fills[:1], True, 200), 100)
        self.assertIsNone(first_entry_fill_time(plan, payload, [fills[0], fills[0]], True, 200))
        self.assertIsNone(first_entry_fill_time(plan, payload, fills, True, 50))
