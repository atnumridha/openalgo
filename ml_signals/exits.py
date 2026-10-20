"""When to close an open ML trade early, as one pure decision.

The stop, the target and the break-even trail are ``services/risk/``'s job and
fire on every tick. This decides the exits only the model can see:

* **Model flip.** The last closed bar's signal now points the other way.
* **Holding is worth less than leaving.** The expected value of staying in,
  for the side held, has fallen below what closing costs. Both must hold for
  ``confirmations`` closed bars in a row, so one noisy bar cannot close a trade.
* **Hold cap.** The trade has been open as long as the operator allows.
* **Scalper window.** A flat or losing trade is closed before the Scalper Offer
  window shuts, because once it does the close costs a fee and the model does
  not expect the trade to earn that back.

No I/O: the trade, the latest closed-bar decision and the clock arrive as
arguments, and the answer is a reason or None.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

#: Minutes before the Scalper Offer window closes that the window exit acts.
WINDOW_MARGIN_MINUTES = 1.0


@dataclass(frozen=True)
class ExitDecision:
    close: bool
    reason: str | None = None
    detail: str | None = None
    #: Closed-bar confirmations counted so far, for the next call.
    streak: int = 0
    last_bar: int | None = None


def decide_exit(
    *,
    side: str,
    opened_at: float,
    now: float,
    signal: dict[str, Any] | None,
    pnl_pct: float,
    exit_fee_pct_now: float,
    exit_fee_pct_after_window: float,
    window_remaining_minutes: float | None,
    max_hold_minutes: float,
    confirmations: int,
    streak: int = 0,
    last_bar: int | None = None,
) -> ExitDecision:
    """Whether to close an open trade now, and why.

    Args:
        side: "LONG" or "SHORT", the side held.
        signal: the latest closed-bar decision for the trade's symbol and
            interval (``action``, ``ev_long_pct``, ``ev_short_pct``, ``time``).
        pnl_pct: the trade's price move so far, in percent of entry, signed so
            positive is a gain for the side held.
        exit_fee_pct_now: closing fee now, percent of notional (0 inside the
            Scalper Offer window).
        exit_fee_pct_after_window: closing fee once the window has passed.
        window_remaining_minutes: minutes left in the window, None if the
            trade has none.
        streak, last_bar: carried from the previous call, so each closed bar
            counts once towards ``confirmations``.
    """
    held_minutes = max(0.0, (now - opened_at) / 60)
    if held_minutes >= max_hold_minutes:
        return ExitDecision(
            True,
            "hold_cap",
            f"Open for {held_minutes:.0f} minutes, the most this setting allows.",
            streak,
            last_bar,
        )

    if (
        window_remaining_minutes is not None
        and 0 < window_remaining_minutes <= WINDOW_MARGIN_MINUTES
        and exit_fee_pct_after_window > 0
        and pnl_pct <= 0
        and _hold_value(side, signal) < exit_fee_pct_after_window
    ):
        return ExitDecision(
            True,
            "scalper_window",
            (
                "Closing while it is still free: the Scalper Offer window ends in under a "
                f"minute and the model does not expect this trade to earn back the "
                f"{exit_fee_pct_after_window:.3f}% fee charged after it."
            ),
            streak,
            last_bar,
        )

    if not signal or signal.get("time") is None:
        return ExitDecision(False, streak=streak, last_bar=last_bar)
    bar = int(signal["time"])
    if bar == last_bar:
        return ExitDecision(False, streak=streak, last_bar=last_bar)

    action = str(signal.get("action") or "WAIT")
    opposite = (side == "LONG" and action == "SHORT") or (side == "SHORT" and action == "LONG")
    hold_value = _hold_value(side, signal)
    weak = hold_value < exit_fee_pct_now
    if opposite or weak:
        streak += 1
    else:
        streak = 0
    if streak >= confirmations:
        if opposite:
            return ExitDecision(
                True,
                "model_flip",
                f"The model has pointed {action} for {streak} closed bars in a row.",
                streak,
                bar,
            )
        return ExitDecision(
            True,
            "low_expected_value",
            (
                f"Holding is expected to make {hold_value:.3f}%, less than the "
                f"{exit_fee_pct_now:.3f}% it costs to close, for {streak} closed bars in a row."
            ),
            streak,
            bar,
        )
    return ExitDecision(False, streak=streak, last_bar=bar)


def _hold_value(side: str, signal: dict[str, Any] | None) -> float:
    """Expected net percent of the side held, from the latest decision."""
    if not signal:
        return 0.0
    key = "ev_long_pct" if side == "LONG" else "ev_short_pct"
    value = signal.get(key)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
