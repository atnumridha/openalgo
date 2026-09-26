"""Idempotent, sandbox-only Strategy Module starter configurations."""

from __future__ import annotations

from dataclasses import dataclass

from database import strategy_module_db as store


@dataclass(frozen=True, slots=True)
class InstallResult:
    """The rows installed now and rows already owned by the caller."""

    created: tuple[dict, ...]
    existing: tuple[dict, ...]
    webhook_tokens: dict[str, str]
    workflows_created: tuple[dict, ...] = ()
    workflows_existing: tuple[dict, ...] = ()


def _option_definition(
    name: str,
    option_type: str,
    *,
    underlying: str = "NIFTY",
    underlying_exchange: str = "NSE_INDEX",
    universe_tab: str = "weekly_monthly",
    expiry: str = "weekly",
    entry_time: str = "09:20",
    exit_time: str = "15:20",
    sl_pts: float = 20,
    target_pts: float = 35,
    risk_unit: str = "points",
) -> dict:
    return {
        "name": name,
        "strategy_kind": "batch",
        "universe_tab": universe_tab,
        "underlying": underlying,
        "underlying_exchange": underlying_exchange,
        "strategy_type": "intraday",
        "product": "MIS",
        "pricetype": "MARKET",
        "entry_time": entry_time,
        "exit_time": exit_time,
        "legs": [
            {
                "segment": "options",
                "position": "B",
                "lots": 1,
                "option_type": option_type,
                "strike_mode": "atm",
                "atm_offset": "ATM",
                "expiry": expiry,
                "sl_pts": sl_pts,
                "target_pts": target_pts,
                "risk_unit": risk_unit,
            }
        ],
        "overall_sl_mtm": 1000,
        "overall_target_mtm": 1800,
        "daily_loss_limit_inr": 1000,
        "scheduler": None,
    }


def _cash_definition(name: str, symbol: str, *, stop: int, target: int) -> dict:
    return {
        "name": name,
        "strategy_kind": "signal",
        "direction": "long_only",
        "universe_tab": "stocks_fno",
        "underlying": symbol,
        "underlying_exchange": "NSE",
        "strategy_type": "intraday",
        "product": "MIS",
        "pricetype": "MARKET",
        "entry_time": "09:20",
        "exit_time": "15:20",
        "legs": [
            {
                "symbol": symbol,
                "exchange": "NSE",
                "side": "long",
                "segment": "cash",
                "qty_mode": "units",
                "qty": 1,
                "sl_pts": stop,
                "target_pts": target,
            }
        ],
        "overall_sl_mtm": 1000,
        "overall_target_mtm": 1800,
        "daily_loss_limit_inr": 1000,
        "scheduler": None,
    }


def starter_definitions() -> tuple[dict, ...]:
    """Return fresh ordinary Strategy Module payloads for the starter templates.

    Options are weekly ATM batch legs so a future run resolves the contract at
    run time. Cash signal templates deliberately name liquid NSE symbols.
    None of these payloads controls status or live mode; those remain store
    owned defaults and are therefore stopped and sandbox-only on creation.
    """
    return (
        _option_definition("NIFTY 5/15-Minute Trend Signal Receiver", "CE"),
        _option_definition("NIFTY Breakout and Retest Signal Receiver", "CE"),
        _option_definition("NIFTY Long-Option Momentum Signal Receiver", "CE"),
        _option_definition(
            "SENSEX 5/15-Minute Trend Signal Receiver",
            "CE",
            underlying="SENSEX",
            underlying_exchange="BSE_INDEX",
            exit_time="15:15",
        ),
        _option_definition(
            "SENSEX Breakout and Retest Signal Receiver",
            "CE",
            underlying="SENSEX",
            underlying_exchange="BSE_INDEX",
            exit_time="15:15",
        ),
        *(
            _option_definition(
                f"{underlying} Momentum and Breakout Signal Receiver",
                "CE",
                underlying=underlying,
                underlying_exchange="MCX",
                universe_tab="mcx",
                expiry="current",
                entry_time="09:30",
                exit_time="22:45",
                sl_pts=20,
                target_pts=35,
                risk_unit="percent",
            )
            for underlying in ("GOLDM", "CRUDEOILM", "SILVERM", "NATGASMINI")
        ),
        _cash_definition("NIFTY 50 Cash Momentum Signal Receiver", "RELIANCE", stop=12, target=20),
        _cash_definition(
            "Cash Support Mean-Reversion Signal Receiver", "HDFCBANK", stop=10, target=16
        ),
        _cash_definition("Opening-Range Breakout Signal Receiver", "ICICIBANK", stop=8, target=14),
    )


def install(user_id: str) -> InstallResult:
    """Create missing templates, without starting, scheduling, or enabling them.

    Validation happens through the public configuration validator before each
    write. The store's per-user unique name constraint remains the final
    duplicate guard, including for two concurrent installer requests.
    """
    # Kept local to avoid a blueprint -> starter pack -> blueprint import cycle
    # while still making the public validator the single configuration gate.
    from blueprints.strategy_module import validate_strategy_config

    existing_by_name = {row["name"]: row for row in store.list_strategies(user_id)}
    created: list[dict] = []
    existing: list[dict] = []
    webhook_tokens: dict[str, str] = {}

    for definition in starter_definitions():
        name = definition["name"]
        already_there = existing_by_name.get(name)
        if already_there is not None:
            existing.append(already_there)
            continue

        config, error = validate_strategy_config(definition)
        if error is not None or config is None:
            raise RuntimeError(f"Starter definition {name!r} is invalid: {error}")

        row, error = store.create_strategy(user_id, config)
        if row is None:
            # A simultaneous installer may have won the unique-name race. Read
            # the durable row rather than minting a replacement token.
            matching = next(
                (item for item in store.list_strategies(user_id) if item["name"] == name), None
            )
            if matching is None:
                raise RuntimeError(f"Could not install starter definition {name!r}: {error}")
            existing.append(matching)
            continue

        token = row.pop("webhook_token")
        webhook_tokens[name] = token
        created.append(row)
        store.record_event(row["id"], user_id, "strategy_created", f"Strategy '{name}' created")

    from services.strategy_module import starter_workflows

    starter_names = {spec[0] for spec in starter_workflows.WORKFLOW_SPECS}
    strategy_rows = {
        row["name"]: row for row in store.list_strategies(user_id)
        if row["name"] in starter_names
    }
    strategy_ids = {name: int(row["id"]) for name, row in strategy_rows.items()}
    connection_ids = {
        name: row.get("broker_connection_id") for name, row in strategy_rows.items()
    }
    workflows = starter_workflows.install(
        strategy_ids, user_id, broker_connection_ids=connection_ids
    )
    return InstallResult(
        tuple(created),
        tuple(existing),
        webhook_tokens,
        workflows.created,
        workflows.existing,
    )
