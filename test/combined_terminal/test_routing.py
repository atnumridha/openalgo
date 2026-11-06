from dataclasses import replace
from types import SimpleNamespace
import pytest

from services.combined_terminal.contracts import WorkerResult,scoped_id
from test_ledger import NOW,ledger,populate,connections


class Transport:
    def __init__(self):self.calls=[];self.timeout=False
    def call(self,c):
        self.calls.append(c)
        if c.action=='quote':data={'ltp':100,'ask':100,'bid':99.95,'time':NOW}
        elif c.action=='metadata':data={'lot':65,'tick':.05,'freeze':1800,'expiry':'2026-10-27'}
        elif c.action=='preview':data={'ticket':'native-'+c.operation_id,'expires':NOW+5,'plan':{'risk':650}}
        elif c.action=='enter':
            if self.timeout:raise TimeoutError('lost acknowledgement')
            data={'id':c.payload['ticket'],'ops':[{'role':'entry','orderid':'order1','state':'accepted'}]}
        elif c.action in ('exit','stop'):data={'id':c.payload['trade_id'],'status':'closing'}
        else:raise ValueError(c.action)
        return WorkerResult(c.operation_id,c.connection,'accepted',data,NOW)


def make(tmp_path):
    from services.combined_terminal.coordinator import TerminalCoordinator
    from services.combined_terminal.registry import Registry,WorkerConfig
    store=ledger(tmp_path);populate(store)
    registry=Registry([WorkerConfig(r,'http://127.0.0.1:'+str(5002+i),b'x'*32) for i,r in enumerate(connections())])
    transport=Transport()
    return TerminalCoordinator(registry,store,transport,clock=lambda:NOW),store,transport


def ticket():
    return {'context_id':'tab1','symbol':'NIFTY27OCT2623000CE','exchange':'NFO','product':'MIS',
            'quantity':65,'entry':100,'sl':90,'target':120,'manual_entry':True}


def test_selector_change_invalidates_old_preview(tmp_path):
    c,_,t=make(tmp_path)
    preview=c.preview('alice','kotak',ticket())
    c.select('alice','tab1','flat')
    with pytest.raises(ValueError):c.enter('alice',preview['preview_id'],'one')
    assert not any(x.action=='enter' for x in t.calls)


def test_entry_bound_to_broker_and_payload_and_expiry(tmp_path):
    c,_,t=make(tmp_path)
    p=c.preview('alice','flat',ticket())
    result=c.enter('alice',p['preview_id'],'one',connection_id='flat')
    assert result.connection.broker=='flattrade'
    entry=[x for x in t.calls if x.action=='enter']
    assert len(entry)==1 and entry[0].connection.id=='flat'
    assert c.enter('alice',p['preview_id'],'one',connection_id='flat')==result
    assert len([x for x in t.calls if x.action=='enter'])==1
    with pytest.raises(ValueError):c.enter('alice',p['preview_id'],'different',connection_id='kotak')


def test_unknown_submission_never_dispatched_again(tmp_path):
    c,_,t=make(tmp_path);t.timeout=True
    p=c.preview('alice','kotak',ticket())
    assert c.enter('alice',p['preview_id'],'one').state=='unknown'
    assert c.enter('alice',p['preview_id'],'one').state=='unknown'
    assert len([x for x in t.calls if x.action=='enter'])==1


def test_exit_uses_saved_owner_not_selected_connection(tmp_path):
    c,store,t=make(tmp_path)
    c.select('alice','tab1','flat')
    trade_id=scoped_id(connections()[0],'trade','legacy-trade')
    result=c.mutate_trade('alice',trade_id,'exit',{'connection_id':'flat','quantity':65,'request_id':'exit1'})
    assert result.connection.id=='kotak'
    assert t.calls[-1].connection.id=='kotak'
    assert t.calls[-1].payload=={'trade_id':'legacy-trade','quantity':65}
    # New entries fail on missing books, but the same account's exit stays available.
    with store.write() as db:
        from database.combined_terminal_db import Observation
        db.execute(Observation.__table__.delete())
    with pytest.raises(ValueError):c.preview('alice','flat',ticket())
    assert c.mutate_trade('alice',trade_id,'exit',{'request_id':'exit2'}).connection.id=='kotak'


def test_wrong_owner_and_unknown_trade_identity_refused(tmp_path):
    c,_,t=make(tmp_path)
    with pytest.raises(PermissionError):c.preview('bob','kotak',ticket())
    with pytest.raises(PermissionError):c.mutate_trade('bob',scoped_id(connections()[0],'trade','one'),'exit',{'request_id':'x'})
    with pytest.raises(ValueError):c.mutate_trade('alice','garbage','exit',{'request_id':'x'})
    assert t.calls==[]


def test_stale_quote_and_invalid_contract_block_preview(tmp_path):
    c,_,t=make(tmp_path)
    original=t.call
    def old(command):
        r=original(command)
        return replace(r,data={**r.data,'time':NOW-6}) if command.action=='quote' else r
    t.call=old
    with pytest.raises(ValueError):c.preview('alice','kotak',ticket())
    assert not any(x.action=='preview' for x in t.calls)


def test_public_routes_require_user_and_csrf_and_get_is_readonly(tmp_path):
    from flask import Flask
    from flask_wtf.csrf import CSRFProtect,generate_csrf
    from blueprints.combined_terminal import create_combined_terminal_blueprint
    c,_,t=make(tmp_path)
    service=SimpleNamespace(enabled=True,coordinator=c,snapshot=lambda user,mode:{'connections':[]})
    app=Flask(__name__);app.secret_key='testing-key';CSRFProtect(app)
    app.register_blueprint(create_combined_terminal_blueprint(lambda:service))
    @app.get('/test-csrf')
    def csrf():return generate_csrf()
    with app.test_client() as client:
        assert client.get('/combined-terminal/api/snapshot').status_code==401
        with client.session_transaction() as session:session['user']='alice'
        assert client.get('/combined-terminal/api/snapshot').status_code==200
        assert t.calls==[]
        assert client.post('/combined-terminal/api/preview',json={'connection_id':'kotak','ticket':ticket()}).status_code==400
        token=client.get('/test-csrf').text
        response=client.post('/combined-terminal/api/preview',json={'connection_id':'kotak','ticket':ticket()},headers={'X-CSRFToken':token})
        assert response.status_code==200


def test_legacy_entry_cannot_bypass_combined_limits(monkeypatch):
    from flask import Flask
    from blueprints import kotak_assistant as module
    monkeypatch.setenv('COMBINED_TERMINAL_ENABLED','true')
    calls=[]
    controller=SimpleNamespace(enter=lambda ticket:calls.append(ticket) or {})
    monkeypatch.setattr(module,'action_data',lambda *a:(controller,{'ticket':'old'}))
    monkeypatch.setattr(module.runtime,'start',lambda:None)
    app=Flask(__name__);app.secret_key='test'
    app.register_blueprint(module.kotak_assistant_bp)
    with app.test_client() as client:
        with client.session_transaction() as s:s.update(user='alice',broker='kotak')
        assert client.post('/kotak-assistant/api/entry',json={}).status_code==409
    assert calls==[]


def test_selected_worker_cannot_preview_more_than_shared_planned_loss_cap(tmp_path):
    c,_,t=make(tmp_path)
    original=t.call
    def excessive(command):
        result=original(command)
        if command.action=='preview':result.data['plan']['risk']=1000.01
        return result
    t.call=excessive
    with pytest.raises(ValueError,match='1,000|1000'):c.preview('alice','kotak',ticket())
    assert not any(x.action=='enter' for x in t.calls)


def test_review_poll_buy_uses_current_complete_observation(tmp_path):
    from test_ledger import snapshot
    c,store,t=make(tmp_path)
    p=c.preview('alice','kotak',ticket())
    for ref in connections():store.observe(snapshot(ref,at=NOW+.1),NOW+.1)
    c.clock=lambda:NOW+.2
    assert c.enter('alice',p['preview_id'],'after-poll').state=='accepted'
