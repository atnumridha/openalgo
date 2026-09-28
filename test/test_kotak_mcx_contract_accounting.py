"""MCX monetary units must not change broker quantity or understate cash risk."""

from datetime import datetime
from decimal import Decimal
from importlib import import_module
from types import SimpleNamespace

import pandas as pd
import pytest
from sqlalchemy import text
from test_strategy_module_sandbox_reset import seeded_reset_db as seeded_reset_db

from database.engine_factory import create_db_engine


def _master_csv(tmp_path, gold_lot=100):
    rows = []
    for index, (name, lot) in enumerate(
        [
            ("GOLDM", gold_lot),
            ("CRUDEOILM", 10),
            ("SILVERM", 5),
            ("NATGASMINI", 250),
            ("GOLD", 1000),
        ]
    ):
        rows.append(
            {
                "pSymbol": str(index + 1),
                "pSymbolName": name,
                "pOptionType": "CE",
                "lExpiryDate": 1793232000,
                "dStrikePrice": 15000000.0,
                "lLotSize": lot,
                "dTickSize": 50,
                "pTrdSymbol": f"{name}29OCT26150000CE",
                "pExchSeg": "mcx_fo",
            }
        )
    pd.DataFrame(rows).to_csv(tmp_path / "MCX_FO.csv", index=False)


def test_importer_persists_monetary_units_without_rescaling_quantity(tmp_path):
    from broker.kotak.database import master_contract_db as master

    _master_csv(tmp_path)
    frame = master.process_kotak_mcx_csv(str(tmp_path))
    assert frame["lotsize"].tolist() == [100, 10, 5, 250, 1000]
    assert "contract_value" in frame.columns
    assert frame["contract_value"].iloc[:4].tolist() == [0.1, 1.0, 1.0, 1.0]
    assert pd.isna(frame["contract_value"].iloc[4])

    engine = create_db_engine(f"sqlite:///{tmp_path / 'import.db'}")
    old_bind = master.db_session.bind
    master.db_session.remove()
    master.db_session.configure(bind=engine)
    try:
        master.Base.metadata.create_all(engine)
        master.copy_from_dataframe(frame)
        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT lotsize, contract_value FROM symtoken WHERE name='GOLDM'")
            ).one() == (100, 0.1)
    finally:
        master.db_session.remove()
        master.db_session.configure(bind=old_bind)
        engine.dispose()


def test_importer_refuses_a_changed_known_contract_lot(tmp_path):
    from broker.kotak.database import master_contract_db as master

    _master_csv(tmp_path, gold_lot=10)
    with pytest.raises(ValueError, match="lot|units"):
        master.process_kotak_mcx_csv(str(tmp_path))


def _symbol(value, **overrides):
    fields = {
        "symbol": "GOLDM29OCT26150000CE",
        "name": "GOLDM",
        "lotsize": 100,
        "exchange": "MCX",
        "brexchange": "mcx_fo",
        "contract_value": value,
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


@pytest.mark.parametrize(
    "name,lot,multiplier,expected",
    [
        ("GOLDM", 100, 0.1, "1000"),
        ("CRUDEOILM", 10, 1.0, "1000"),
        ("SILVERM", 5, 1.0, "500"),
        ("NATGASMINI", 250, 1.0, "25000"),
    ],
)
def test_sandbox_option_premium_uses_quote_units(monkeypatch, name, lot, multiplier, expected):
    from sandbox import fund_manager

    info = _symbol(multiplier, name=name, lotsize=lot, symbol=f"{name}29OCT26150000CE")
    monkeypatch.setattr(fund_manager, "get_symbol_info", lambda *_: info)
    monkeypatch.setattr(fund_manager, "get_config", lambda _key, default: default)
    margin, _ = fund_manager.FundManager("test").calculate_margin_required(
        info.symbol, "MCX", "NRML", lot, 100, "BUY"
    )
    assert margin == Decimal(expected)


@pytest.mark.parametrize("value", [None, 0, -1, 1.0, True, "invalid", float("nan"), float("inf")])
def test_sandbox_refuses_missing_invalid_or_conflicting_kotak_units(monkeypatch, value):
    from sandbox import fund_manager

    monkeypatch.setattr(fund_manager, "get_symbol_info", lambda *_: _symbol(value))
    monkeypatch.setattr(fund_manager, "get_config", lambda _key, default: default)
    margin, _ = fund_manager.FundManager("test").calculate_margin_required(
        "GOLDM29OCT26150000CE", "MCX", "NRML", 100, 100, "BUY"
    )
    assert margin is None


def test_sandbox_keeps_another_brokers_explicit_unit_basis(monkeypatch):
    from sandbox import fund_manager

    info = _symbol(10, brexchange="MCX", lotsize=1)
    monkeypatch.setattr(fund_manager, "get_symbol_info", lambda *_: info)
    monkeypatch.setattr(fund_manager, "get_config", lambda _key, default: default)
    margin, _ = fund_manager.FundManager("test").calculate_margin_required(
        info.symbol, "MCX", "NRML", 1, 100, "BUY"
    )
    assert margin == Decimal("1000")


def _roundtrip_trades():
    return [
        SimpleNamespace(
            id=index,
            symbol="GOLDM29OCT26150000CE",
            exchange="MCX",
            product="NRML",
            action=action,
            quantity=100,
            price=Decimal(price),
            trade_timestamp=datetime(2026, 9, 28, 10, index),
        )
        for index, (action, price) in enumerate([("BUY", "100"), ("SELL", "80")])
    ]


@pytest.mark.parametrize("value", [None, "invalid", True, float("nan")])
def test_reset_replay_refuses_missing_mcx_metadata(monkeypatch, value):
    from database import token_db
    from services.strategy_module import sandbox_reset

    monkeypatch.setattr(token_db, "get_symbol_info", lambda *_: _symbol(value))
    with pytest.raises(ValueError, match="contract|Contract|units"):
        sandbox_reset._replay_position_realised_pnl(_roundtrip_trades())


def test_reset_replay_matches_the_rupees_credited_to_sandbox(monkeypatch):
    from database import token_db
    from services.strategy_module import sandbox_reset

    monkeypatch.setattr(token_db, "get_symbol_info", lambda *_: _symbol(0.1))
    replay = sandbox_reset._replay_position_realised_pnl(_roundtrip_trades())
    assert replay == {("GOLDM29OCT26150000CE", "MCX", "NRML"): Decimal("-200.00")}


def test_goldm_reset_reconciles_wallet_and_blocks_changed_unit_evidence(
    monkeypatch,
    seeded_reset_db,
):
    from database import sandbox_db, token_db
    from database import strategy_module_db as store
    from services.strategy_module import sandbox_reset

    symbol = "GOLDM29OCT26150000CE"
    for row in store.db_session.query(store.SmStrategyOrder).all():
        row.symbol, row.exchange, row.qty, row.filled_qty = symbol, "MCX", 100, 100
    run = store.db_session.get(store.SmStrategyRun, seeded_reset_db.owned_sandbox_run_id)
    run.pnl_realized = Decimal("-200.00")
    for row in sandbox_db.db_session.query(sandbox_db.SandboxOrders).all():
        row.symbol, row.exchange, row.quantity, row.filled_quantity = symbol, "MCX", 100, 100
    for row in sandbox_db.db_session.query(sandbox_db.SandboxTrades).all():
        row.symbol, row.exchange, row.quantity = symbol, "MCX", 100
    funds = sandbox_db.SandboxFunds.query.filter_by(user_id="owner").one()
    funds.available_balance = Decimal("99800.00")
    funds.realized_pnl = funds.today_realized_pnl = funds.total_pnl = Decimal("-200.00")
    sandbox_db.db_session.add(
        sandbox_db.SandboxPositions(
            user_id="owner",
            symbol=symbol,
            exchange="MCX",
            product="NRML",
            quantity=0,
            average_price=Decimal("100.00"),
            today_realized_pnl=Decimal("-200.00"),
            accumulated_realized_pnl=Decimal("-200.00"),
        )
    )
    store.db_session.commit()
    sandbox_db.db_session.commit()

    monkeypatch.setattr(token_db, "get_symbol_info", lambda *_: _symbol(0.1))
    view = sandbox_reset.preview("owner", now=seeded_reset_db.now)
    assert view.blockers == ()
    assert view.realised_pnl == Decimal("-200.00")
    assert view.funds_after == Decimal("100000.00")

    monkeypatch.setattr(token_db, "get_symbol_info", lambda *_: _symbol("invalid"))
    blocked = sandbox_reset.preview("owner", now=seeded_reset_db.now)
    assert any("contract units" in reason for reason in blocked.blockers)
    assert blocked.version != view.version
    with pytest.raises(sandbox_reset.ResetBlocked):
        sandbox_reset.execute("owner", view.version, now=seeded_reset_db.now)
    assert funds.available_balance == Decimal("99800.00")


def _migration_db(tmp_path, bad_lot=False):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE symtoken (id INTEGER PRIMARY KEY, name TEXT, "
                "exchange TEXT, brexchange TEXT, lotsize INTEGER, contract_value REAL)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO symtoken (name, exchange, brexchange, lotsize, contract_value) "
                "VALUES (:name,:exchange,:brexchange,:lotsize,:contract_value)"
            ),
            [
                {
                    "name": name,
                    "exchange": exchange,
                    "brexchange": broker,
                    "lotsize": lot,
                    "contract_value": value,
                }
                for name, exchange, broker, lot, value in [
                    ("GOLDM", "MCX", "mcx_fo", 100, None),
                    ("GOLDM", "MCX", "mcx_fo", 100, 1.0),
                    ("CRUDEOILM", "MCX", "mcx_fo", 10, None),
                    ("SILVERM", "MCX", "mcx_fo", 10 if bad_lot else 5, None),
                    ("NATGASMINI", "MCX", "mcx_fo", 250, None),
                    ("GOLDM", "MCX", "MCX", 1, 10.0),
                    ("GOLD", "MCX", "mcx_fo", 1000, None),
                    ("GOLDM", "NFO", "nse_fo", 100, None),
                ]
            ],
        )
    return engine


def test_migration_backfills_only_verified_kotak_rows_and_is_idempotent(tmp_path):
    migration = import_module("upgrade.migrate_kotak_mcx_contract_values")
    engine = _migration_db(tmp_path)
    try:
        assert migration.status(engine) is False
        assert migration.apply(engine) is True
        assert migration.status(engine) is True
        assert migration.apply(engine) is True
        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT contract_value FROM symtoken ORDER BY id")
            ).scalars().all() == [0.1, 0.1, 1.0, 1.0, 1.0, 10.0, None, None]
    finally:
        engine.dispose()


def test_migration_does_not_partially_apply_when_a_known_lot_has_changed(tmp_path):
    migration = import_module("upgrade.migrate_kotak_mcx_contract_values")
    engine = _migration_db(tmp_path, bad_lot=True)
    try:
        with pytest.raises(ValueError, match="lot|units"):
            migration.apply(engine)
        with engine.connect() as connection:
            assert (
                connection.execute(
                    text("SELECT contract_value FROM symtoken WHERE id=1")
                ).scalar_one()
                is None
            )
    finally:
        engine.dispose()


def test_migration_status_does_not_write_and_conflicting_units_abort_batch(tmp_path):
    migration = import_module("upgrade.migrate_kotak_mcx_contract_values")
    engine = _migration_db(tmp_path)
    try:
        assert migration.status(engine) is False
        with engine.begin() as connection:
            assert (
                connection.execute(
                    text("SELECT contract_value FROM symtoken WHERE id=1")
                ).scalar_one()
                is None
            )
            connection.execute(text("UPDATE symtoken SET contract_value=2 WHERE id=5"))
        with pytest.raises(ValueError, match="Conflicting"):
            migration.apply(engine)
        with engine.connect() as connection:
            assert (
                connection.execute(
                    text("SELECT contract_value FROM symtoken WHERE id=1")
                ).scalar_one()
                is None
            )
    finally:
        engine.dispose()


def test_migration_resolves_relative_database_against_project_root(monkeypatch):
    migration = import_module("upgrade.migrate_kotak_mcx_contract_values")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///db/test-only.db")
    assert migration.get_database_url() == f"sqlite:///{migration.PROJECT_ROOT}/db/test-only.db"


def test_migration_entrypoint_disposes_engine_on_failure(monkeypatch, tmp_path):
    migration = import_module("upgrade.migrate_kotak_mcx_contract_values")
    engine = _migration_db(tmp_path, bad_lot=True)
    disposed = []
    original_dispose = engine.dispose

    def dispose():
        disposed.append(True)
        original_dispose()

    monkeypatch.setattr(engine, "dispose", dispose)
    monkeypatch.setattr(migration, "create_db_engine", lambda *_: engine)
    monkeypatch.setattr(migration, "get_database_url", lambda: "sqlite:///unused.db")
    monkeypatch.setattr("sys.argv", ["migrate_kotak_mcx_contract_values.py"])
    assert migration.main() == 1
    assert disposed == [True]


def test_migration_runner_propagates_unit_validation_failure(monkeypatch):
    from upgrade import migrate_all

    monkeypatch.setattr(
        migrate_all.subprocess, "run", lambda *_args, **_kwargs: SimpleNamespace(returncode=1)
    )
    assert (
        migrate_all.run_migration("migrate_kotak_mcx_contract_values.py", "Kotak MCX units")
        is False
    )
