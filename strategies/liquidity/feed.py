"""Bounded public-data reader. Native HTF bars; completed pivots only."""

import time

from cachetools import TTLCache

from strategies.confluence.data import DeltaPublic


def references(rows, seconds, frame, now, captured_at=None, entry_bars=()):
    cutoff = min(now, captured_at if captured_at is not None else now)
    observed = sorted([b for b in rows if b["time"] <= cutoff], key=lambda b: b["time"])
    bars = [b for b in observed if b["time"] + seconds <= cutoff]
    result = []
    for side, field in [("Low", "low"), ("High", "high")]:
        for i in range(len(bars) - 3, 1, -1):
            w = bars[i - 2 : i + 3]
            p = bars[i]
            if any(y["time"] != x["time"] + seconds for x, y in zip(w, w[1:], strict=False)):
                continue
            if not all(
                p[field] < x[field] if side == "Low" else p[field] > x[field]
                for x in w
                if x is not p
            ):
                continue
            price = p[field]
            known = bars[i + 2]["time"] + seconds
            touches = [
                x["time"]
                for x in observed
                if x["time"] >= known
                and (x[field] <= price if side == "Low" else x[field] >= price)
            ]
            retired = min(touches) if touches else None
            # Refine only with complete coverage of the coarse interval.
            small = [b for b in entry_bars if b["time"] >= known]
            crossed = [
                b["time"]
                for b in small
                if (b[field] <= price if side == "Low" else b[field] >= price)
            ]
            if retired is not None and small and small[0]["time"] <= retired:
                precise = [t for t in crossed if t >= retired]
                if precise:
                    retired = min(precise)
            elif retired is None and crossed:
                retired = min(crossed)
            # A recent first touch may start a candidate, but cannot be a target.
            if retired is not None and entry_bars and retired < entry_bars[0]["time"]:
                continue
            result.append(
                {
                    "id": f"{frame}:{side}:{p['time']}",
                    "side": side,
                    "price": price,
                    "known": known,
                    "frame": frame,
                    "retired_at": retired,
                }
            )
            break
    return result


class Feed(DeltaPublic):
    def __init__(self, transport=None):
        super().__init__(transport)
        self.htf = TTLCache(maxsize=3, ttl=60)

    def context(self, now):
        minute = int(now // 60) * 60
        if minute not in self.candles:
            self.candles[minute] = self.history(minute - 120 * 60, minute)
        refs = []
        for resolution, seconds, label in [
            ("1h", 3600, "1H"),
            ("4h", 14400, "4H"),
            ("1d", 86400, "1D"),
        ]:
            cached = self.htf.get(resolution)
            if cached is None or int(cached["captured_at"] // seconds) != int(now // seconds):
                captured = time.time()
                rows = self.get(
                    "/v2/history/candles",
                    {
                        "symbol": "BTCUSD",
                        "resolution": resolution,
                        "start": minute - seconds * 100,
                        "end": minute,
                    },
                )
                cached = {"rows": rows, "captured_at": captured}
                self.htf[resolution] = cached
            refs.extend(
                references(
                    cached["rows"], seconds, label, now, cached["captured_at"], self.candles[minute]
                )
            )
        return {"bars": self.candles[minute], "references": refs, "product": self.product("BTCUSD")}
