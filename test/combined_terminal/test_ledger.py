from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from zoneinfo import ZoneInfo
from dataclasses import replace
import pytest
from sqlalchemy import create_engine

NOW=datetime(2026,10,20,10,0,tzinfo=ZoneInfo('Asia/Kolkata')).timestamp()


def connections():
    from services.combined_terminal.contracts import ConnectionRef
    return [ConnectionRef('kotak','alice','kotak','a'*24,'live'),
            ConnectionRef('flat','alice','flattrade','b'*24,'live')]


def snapshot(ref, *, pnl=0, fills=None, orders=None, at=NOW, complete=True):
    from services.combined_terminal.contracts import AccountSnapshot
    return AccountSnapshot(ref,at,complete,True,orders or [],fills or [],[],{'availablecash':30000},pnl,0)


def buy(oid, tid=None, epoch=NOW):
    return {'orderid':oid,'tradeid':tid or oid,'symbol':'NIFTY','exchange':'NFO','product':'MIS',
            'action':'BUY','quantity':65,'average_price':100,'timestamp':epoch}


def ledger(tmp_path):
    from services.combined_terminal.ledger import Ledger
    return Ledger(create_engine('sqlite:///'+str(tmp_path/'ledger.db')),connections())


def populate(store, fills=None, pnl=0, at=NOW):
    refs=connections()
    return {r.id:store.observe(snapshot(r,fills=fills if i==0 else None,pnl=pnl if i==0 else 0,at=at),at)
            for i,r in enumerate(refs)}


def intent(op, ref=None):
    from services.combined_terminal.contracts import EntryIntent
    return EntryIntent(op,ref or connections()[0],'preview-'+op,'hash-'+op,'reserved')


def test_two_tabs_cannot_reserve_same_last_entry(tmp_path):
    store=ledger(tmp_path)
    ids=populate(store,[buy('1'),buy('2')])
    def reserve(op):
        try:return store.reserve('alice',intent(op),ids,NOW).operation_id
        except ValueError:return None
    with ThreadPoolExecutor(2) as pool:
        results=list(pool.map(reserve,['one','two']))
    assert sum(x is not None for x in results)==1
    assert store.day('alice','live',NOW)['remaining_entries']==0


def test_retry_returns_same_intent_and_rejects_changed_payload(tmp_path):
    store=ledger(tmp_path); ids=populate(store)
    first=store.reserve('alice',intent('one'),ids,NOW)
    assert store.reserve('alice',intent('one'),ids,NOW)==first
    with pytest.raises(ValueError):store.reserve('alice',replace(intent('one'),payload_hash='changed'),ids,NOW)
    with pytest.raises(PermissionError):store.intent('bob','one')


def test_unknown_reservation_survives_restart(tmp_path):
    from services.combined_terminal.ledger import Ledger
    from services.combined_terminal.contracts import WorkerResult
    store=ledger(tmp_path); ids=populate(store,[buy('1'),buy('2')]); ref=connections()[0]
    store.reserve('alice',intent('one'),ids,NOW)
    store.record_result('one',WorkerResult('one',ref,'unknown',{},NOW))
    restored=Ledger(create_engine('sqlite:///'+str(tmp_path/'ledger.db')),connections())
    with pytest.raises(ValueError):restored.reserve('alice',intent('other'),ids,NOW)
    assert restored.intent('alice','one').state=='unknown'


def test_partial_fill_counts_once_and_cancel_does_not_release_entry(tmp_path):
    from services.combined_terminal.contracts import WorkerResult
    store=ledger(tmp_path); ids=populate(store); ref=connections()[0]
    store.reserve('alice',intent('one'),ids,NOW)
    store.record_result('one',WorkerResult('one',ref,'accepted',{'id':'trade','ops':[{'role':'entry','orderid':'o1'}]},NOW))
    order={'orderid':'o1','exchange':'NFO','action':'BUY','quantity':130,'filled_quantity':65,'order_status':'cancelled'}
    store.observe(snapshot(ref,fills=[buy('o1','f1')],orders=[order]),NOW)
    assert store.day('alice','live',NOW)['entries']==1
    order.update(filled_quantity=130)
    store.observe(snapshot(ref,fills=[buy('o1','f1'),buy('o1','f2')],orders=[order],at=NOW+1),NOW+1)
    assert store.day('alice','live',NOW+1)['entries']==1


def test_definitive_zero_fill_rejection_releases_capacity(tmp_path):
    from services.combined_terminal.contracts import WorkerResult
    store=ledger(tmp_path); ids=populate(store,[buy('1'),buy('2')]); ref=connections()[0]
    store.reserve('alice',intent('one'),ids,NOW)
    store.record_result('one',WorkerResult('one',ref,'rejected',{},NOW))
    assert store.reserve('alice',intent('two'),ids,NOW).state=='reserved'


def test_colliding_ids_count_separately_and_changed_fill_blocks(tmp_path):
    store=ledger(tmp_path)
    for ref in connections():store.observe(snapshot(ref,fills=[buy('1')]),NOW)
    assert store.day('alice','live',NOW)['entries']==2
    altered=buy('1');altered['quantity']=130
    with pytest.raises(ValueError):store.observe(snapshot(connections()[0],fills=[altered],at=NOW+1),NOW+1)
    with pytest.raises(ValueError):store.reserve('alice',intent('one'),store.snapshot_ids('alice','live'),NOW+1)


def test_loss_latch_persists_after_recovery_but_profit_allows_capacity(tmp_path):
    store=ledger(tmp_path)
    ids=populate(store,pnl=2000)
    assert store.reserve('alice',intent('one'),ids,NOW).state=='reserved'
    populate(store,pnl=-1000,at=NOW+1)
    populate(store,pnl=100,at=NOW+2)
    with pytest.raises(ValueError):store.reserve('alice',intent('two'),store.snapshot_ids('alice','live'),NOW+2)
    assert store.day('alice','live',NOW+2)['loss_reached']


def test_old_day_loss_does_not_reset_unresolved_order(tmp_path):
    from services.combined_terminal.contracts import WorkerResult
    store=ledger(tmp_path);ids=populate(store)
    store.reserve('alice',intent('one'),ids,NOW)
    store.record_result('one',WorkerResult('one',connections()[0],'unknown',{},NOW))
    tomorrow=NOW+86400;ids=populate(store,at=tomorrow)
    with pytest.raises(ValueError,match='unresolved'):store.reserve('alice',intent('two'),ids,tomorrow)
    assert store.day('alice','live',tomorrow)['entries']==0


def test_missing_or_stale_snapshot_blocks_reservation(tmp_path):
    store=ledger(tmp_path)
    ids=populate(store)
    with pytest.raises(ValueError):store.reserve('alice',intent('one'),{'kotak':ids['kotak']},NOW)
    with pytest.raises(ValueError):store.reserve('alice',intent('one'),ids,NOW+11)


def test_prior_day_fills_and_paper_are_not_counted_as_live(tmp_path):
    store=ledger(tmp_path)
    populate(store,[buy('old',epoch=NOW-86400)])
    assert store.day('alice','live',NOW)['entries']==0
    assert store.day('alice','analyze',NOW)['entries']==0


def test_filled_order_missing_trade_rows_blocks_new_entry(tmp_path):
    store=ledger(tmp_path)
    populate(store)
    order={'orderid':'missing','exchange':'NFO','action':'BUY','quantity':65,
           'filled_quantity':65,'order_status':'complete','timestamp':NOW}
    store.observe(snapshot(connections()[0],orders=[order]),NOW)
    with pytest.raises(ValueError):store.reserve('alice',intent('one'),store.snapshot_ids('alice','live'),NOW)


def test_migration_preserves_legacy_records_and_is_idempotent(tmp_path):
    from sqlalchemy import text,inspect
    from upgrade.migrate_combined_terminal import migrate
    engine=create_engine('sqlite:///'+str(tmp_path/'old.db'))
    with engine.begin() as db:
        db.execute(text('CREATE TABLE legacy (id INTEGER PRIMARY KEY, value TEXT)'))
        db.execute(text("INSERT INTO legacy VALUES (1,'retained')"))
    assert 'combined_terminal_intent' in migrate(engine,status=True)
    assert len(inspect(engine).get_table_names())==1
    migrate(engine);migrate(engine)
    assert 'combined_terminal_preview' in inspect(engine).get_table_names()
    with engine.connect() as db:assert db.execute(text('SELECT value FROM legacy')).scalar_one()=='retained'


def test_master_migration_runner_can_unpack_registry():
    from upgrade.migrate_all import MIGRATIONS
    consumed=[]
    for script,description in MIGRATIONS:
        consumed.append(script)
    assert 'migrate_combined_terminal.py' in consumed


def test_quote_freshness_expires_before_book_freshness(tmp_path):
    store=ledger(tmp_path);ids=populate(store)
    with pytest.raises(ValueError):store.reserve('alice',intent('late'),ids,NOW+6)


def test_unknown_entry_blocks_replacement_on_other_broker_even_below_cap(tmp_path):
    from services.combined_terminal.contracts import WorkerResult
    store=ledger(tmp_path);ids=populate(store)
    store.reserve('alice',intent('one'),ids,NOW)
    store.record_result('one',WorkerResult('one',connections()[0],'unknown',{},NOW))
    with pytest.raises(ValueError,match='unresolved|unknown'):
        store.reserve('alice',intent('replacement',connections()[1]),ids,NOW)
