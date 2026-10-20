"""Pure index-reference R targets for offline stress scenarios, before costs."""

import math


def levels(candidate, entry, policy, tick):
    sign = 1 if candidate["side"] == "long" else -1
    risk = sign * (entry - candidate["stop"])
    room = sign * (candidate["target"] - entry)
    if risk <= 0 or room + 1e-9 < policy["min_room_r"] * risk:
        return None

    def target(multiple):
        raw = entry + sign * multiple * risk
        # Preserve the 2R minimum; higher projected targets are maximum caps.
        round_up = (sign > 0) == (multiple == policy["min_room_r"])
        return (math.ceil(raw / tick - 1e-9) if round_up else math.floor(raw / tick + 1e-9)) * tick

    first = target(policy["first_r"])
    runner = target(policy["runner_r"]) if policy["runner_r"] is not None else None
    if first <= 0 or (runner is not None and runner <= 0):
        return None
    return {
        "target": first,
        "runner_target": runner,
        "first_fraction": policy["first_fraction"],
        "initial_risk_points": risk,
        "structural_room_r": room / risk,
        "higher_target_projected": policy["first_r"] > room / risk
        or (policy["runner_r"] is not None and policy["runner_r"] > room / risk),
    }
