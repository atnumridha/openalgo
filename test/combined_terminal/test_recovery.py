from dataclasses import replace
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from sqlalchemy import create_engine
import pytest

from services.combined_terminal.contracts import WorkerResult
from test_ledger import NOW,connections,snapshot,ledger,populate,intent


class Feed:
    def __init__(self):self.fail=set();self.calls=[]
    def call(self,command):
        self.calls.append(command)
        if command.connection.id in self.fail:raise TimeoutError('upstream credential must not leak')
        snap=snapshot(command.connection)
        trade={'id':'native','symbol':'NIFTY','exchange':'NFO','product':'MIS','remaining':65,
               'status':'open','current_sl':95,'quote':{'ltp':101,'time':NOW}}
        return WorkerResult(command.operation_id,command.connection,'accepted',
                            {'snapshot':snap.to_dict(),'managed_trades':[trade]},NOW)


def make(tmp_path):
    from services.combined_terminal.registry import Registry,WorkerConfig
    from services.combined_terminal.runtime import Runtime
    store=ledger(tmp_path)
    registry=Registry([WorkerConfig(c,'http://127.0.0.1:'+str(5002+i),b'x'*32) for i,c in enumerate(connections())])
    feed=Feed()
    return Runtime(registry,store,feed,clock=lambda:NOW),feed,store


def test_restart_restores_owned_positions_when_worker_is_unavailable(tmp_path):
    from services.combined_terminal.runtime import Runtime
    from services.combined_terminal.ledger import Ledger
    runtime,feed,store=make(tmp_path)
    runtime.reconcile_once(NOW)
    assert len(runtime.snapshot('alice','live')['positions'])==2
    feed.fail={'flat'}
    restored=Runtime(runtime.registry,Ledger(create_engine('sqlite:///'+str(tmp_path/'ledger.db')),connections()),feed,clock=lambda:NOW+1)
    restored.reconcile_once(NOW+1)
    state=restored.snapshot('alice','live')
    assert len(state['positions'])==2
    assert state['summary']['estimated_total_net'] is None
    assert state['positions'][1]['current_sl']==95
    assert not any(c.action in ('enter','exit','stop') for c in feed.calls)


def test_overlapping_polls_do_not_duplicate_reads(tmp_path):
    runtime,feed,store=make(tmp_path)
    gate,release=threading.Event(),threading.Event()
    original=feed.call
    def slow(command):
        gate.set();release.wait(2)
        return original(command)
    feed.call=slow
    with ThreadPoolExecutor(2) as pool:
        first=pool.submit(runtime.reconcile_once,NOW)
        assert gate.wait(1)
        second=pool.submit(runtime.reconcile_once,NOW)
        second.result(timeout=1)
        release.set();first.result(timeout=2)
    assert len(feed.calls)==2


def test_foreign_inner_snapshot_identity_is_never_accepted(tmp_path):
    runtime,feed,store=make(tmp_path)
    original=feed.call
    def wrong(command):
        result=original(command)
        result.data['snapshot']['connection']['account']='other'
        return result
    feed.call=wrong
    runtime.reconcile_once(NOW)
    state=runtime.snapshot('alice','live')
    assert not state['day']['entry_allowed']
    assert all(c['entry_ready'] is False for c in state['connections'])


def test_reminder_preference_persists_with_range_checks(tmp_path):
    from services.combined_terminal.runtime import Runtime
    runtime,feed,store=make(tmp_path)
    assert runtime.snapshot('alice','live')['settings']['reminder_seconds']==120
    runtime.configure('alice','live',{'reminder_seconds':180})
    again=Runtime(runtime.registry,store,feed,clock=lambda:NOW)
    assert again.snapshot('alice','live')['settings']['reminder_seconds']==180
    with pytest.raises(ValueError):again.configure('alice','live',{'reminder_seconds':0})


def test_unknown_receipt_reconciles_by_saved_worker_ticket_without_resubmit(tmp_path):
    from test_routing import make,ticket
    from services.combined_terminal.runtime import Runtime
    from database.combined_terminal_db import Preview
    from sqlalchemy import select
    c,store,entry_transport=make(tmp_path)
    entry_transport.timeout=True
    p=c.preview('alice','kotak',ticket())
    assert c.enter('alice',p['preview_id'],'one').state=='unknown'
    with store.engine.connect() as db:
        native=db.execute(select(Preview.worker_ticket).where(Preview.id==p['preview_id'])).scalar_one()
    feed=Feed();original=feed.call
    def recovered(command):
        result=original(command)
        result.data['managed_trades']=[{'id':native,'entry_quantity':0,
            'ops':[{'role':'entry','state':'accepted','orderid':'o2'}]}] if command.connection.id=='kotak' else []
        return result
    feed.call=recovered
    runtime=Runtime(c.registry,store,feed,clock=lambda:NOW)
    runtime.reconcile_once(NOW)
    assert store.intent('alice','one').state=='accepted'
    assert len([x for x in entry_transport.calls if x.action=='enter'])==1
    assert all(x.action=='snapshot' for x in feed.calls)


def test_worker_snapshot_captured_during_network_read_is_not_future_data():
    from services.combined_terminal.runtime import Runtime
    from services.combined_terminal.contracts import AccountSnapshot,ConnectionRef,WorkerResult
    now=[100.0];observed=[]
    ref=ConnectionRef('flat','alice','flattrade','account','live')
    class Ledger:
        def snapshots(self,*args):return []
        def observe(self,snapshot,*args):observed.append(snapshot)
    class Transport:
        def call(self,command):
            now[0]=102.0
            snapshot=AccountSnapshot(ref,102.0,True,True,funds={'availablecash':8000},realized_net=0,estimated_open_net=0)
            return WorkerResult(command.operation_id,ref,'accepted',{'snapshot':snapshot.to_dict(),'managed_trades':[]},102.0)
    runtime=Runtime(None,Ledger(),Transport(),clock=lambda:now[0])
    runtime._receipts=lambda *args:None
    runtime._read(ref,100.0)
    assert observed[-1].books_complete
    assert observed[-1].error is None
