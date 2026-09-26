"""Once-per-session, order-free sandbox protection comparison reports."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from database import profit_comparison_db as comparisons
from database import strategy_module_db as store
from services.strategy_module import session

IST = ZoneInfo("Asia/Kolkata")
PROFILES = ("baseline", "early", "room")


def _session_payload(snapshots: list[dict]) -> dict:
    metrics = {}
    for name in PROFILES:
        profiles = [snapshot["profiles"][name] for snapshot in snapshots]
        complete = all(
            profile["status"] == "closed" and profile["simulated_realized_pnl"] is not None
            for profile in profiles
        )
        metrics[name] = {
            "complete_entries": sum(
                profile["status"] == "closed" and profile["simulated_realized_pnl"] is not None
                for profile in profiles
            ),
            "realized_estimate": sum(
                float(profile["simulated_realized_pnl"]) for profile in profiles
            ) if complete else None,
            "entry_peak_sum": sum(float(profile["peak_profit"]) for profile in profiles),
            "max_entry_drawdown": max(float(profile["max_drawdown"]) for profile in profiles),
            "giveback_sum": sum(
                float(profile["peak_profit"]) - float(profile["simulated_realized_pnl"])
                for profile in profiles
            ) if complete else None,
            "missed_fill_entries": sum(bool(profile["missed_fill"]) for profile in profiles),
            "trigger_only_entries": sum(profile["status"] == "trigger_only" for profile in profiles),
        }
    early_exits = 0
    for snapshot in snapshots:
        baseline = snapshot["profiles"]["baseline"].get("trigger_at")
        early = snapshot["profiles"]["early"].get("trigger_at")
        if baseline and early and early < baseline:
            early_exits += 1
    return {
        "entry_count": len(snapshots),
        "all_profiles_complete": all(
            metrics[name]["complete_entries"] == len(snapshots) for name in PROFILES
        ),
        "early_protection_triggered_before_baseline": early_exits,
        "fees": "unavailable",
        "rule_selected": None,
        "profiles": metrics,
    }


def report_completed_sessions(now: datetime | None = None) -> int:
    """Catch up recent completed sessions; unique DB rows prevent duplicates."""
    now = (now or datetime.now(UTC)).astimezone(UTC)
    comparisons.finalize_due(now)
    current_day = session.session_day(now.astimezone(IST))
    sent = 0
    for days_ago in (1, 2):
        day = current_day - timedelta(days=days_ago)
        start = datetime.combine(day, session.session_reset_time(), IST).astimezone(UTC)
        end = start + timedelta(days=1)
        if end > now:
            continue
        snapshots = comparisons.list_created_between(start, end)
        by_strategy: dict[int, list[dict]] = {}
        owners: dict[int, str] = {}
        for snapshot in snapshots:
            run = store.get_run(snapshot["run_id"])
            if run is None or run.mode != "sandbox":
                continue
            strategy = store.get_strategy_unscoped(run.strategy_id)
            if strategy is None:
                continue
            by_strategy.setdefault(run.strategy_id, []).append(snapshot)
            owners[run.strategy_id] = strategy.user_id
        for strategy_id, group in by_strategy.items():
            payload = _session_payload(group)
            payload["session_day"] = day.isoformat()
            if payload["all_profiles_complete"]:
                totals = payload["profiles"]
                message = (
                    f"Sandbox comparison {day}: {len(group)} entries. "
                    f"Existing ₹{totals['baseline']['realized_estimate']:.2f}; "
                    f"earlier ₹{totals['early']['realized_estimate']:.2f}; "
                    f"trend room ₹{totals['room']['realized_estimate']:.2f}. "
                    "Simulated, fees unavailable; no rule selected."
                )
            else:
                message = (
                    f"Sandbox comparison {day}: {len(group)} entries, but some fills or "
                    "quotes were unavailable. See Compare tab; no rule selected."
                )
            sent += int(store.record_comparison_session_summary(
                strategy_id, owners[strategy_id], day, message, payload
            ))
    return sent
