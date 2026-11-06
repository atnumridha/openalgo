import pytest
from services.combined_terminal.contracts import ConnectionRef, WorkerCommand


def ref(account='a'):
    return ConnectionRef('kotak-main', 'alice', 'kotak', account, 'live')


class Controller:
    def __init__(self):
        self.entries = 0
        self.fail = False
        self.scope = 'alice:a:live'
    def enter(self, ticket):
        self.entries += 1
        if self.fail:
            raise TimeoutError('token=private-value')
        return {'id': ticket, 'status': 'entry_pending', 'ops': [{'state':'accepted','orderid':'one'}]}
    def state(self):
        return {'trades': {}, 'settings': {}}


def test_worker_rejects_mismatched_account_before_dispatch(tmp_path):
    from services.combined_terminal.worker import Worker
    c = Controller()
    worker = Worker(ref(), c, tmp_path/'worker.db', identity=lambda:ref())
    with pytest.raises(PermissionError):
        worker.execute(WorkerCommand('op1', ref('other'), 'enter', {'ticket':'ticket'}, 100))
    assert c.entries == 0


def test_worker_rejects_changed_login_before_dispatch(tmp_path):
    from services.combined_terminal.worker import Worker
    c = Controller()
    worker = Worker(ref(), c, tmp_path/'worker.db', identity=lambda:ref('changed'))
    with pytest.raises(PermissionError):
        worker.execute(WorkerCommand('op1', ref(), 'enter', {'ticket':'ticket'}, 100))
    assert c.entries == 0


def test_worker_dispatches_intent_once_across_restart(tmp_path):
    from services.combined_terminal.worker import Worker
    c = Controller()
    command = WorkerCommand('op1', ref(), 'enter', {'ticket':'ticket'}, 100)
    first = Worker(ref(), c, tmp_path/'worker.db', identity=lambda:ref()).execute(command)
    again = Worker(ref(), c, tmp_path/'worker.db', identity=lambda:ref()).execute(command)
    assert first.data['id'] == again.data['id'] == 'ticket'
    assert c.entries == 1
    with pytest.raises(ValueError):
        Worker(ref(), c, tmp_path/'worker.db', identity=lambda:ref()).execute(
            WorkerCommand('op1', ref(), 'enter', {'ticket':'different'},100))


def test_unknown_outcome_retained_without_retry_or_secret(tmp_path):
    from services.combined_terminal.worker import Worker
    c = Controller(); c.fail = True
    cmd = WorkerCommand('op1', ref(), 'enter', {'ticket':'ticket'},100)
    result = Worker(ref(), c, tmp_path/'worker.db', identity=lambda:ref()).execute(cmd)
    assert result.state == 'unknown'
    assert 'private-value' not in str(result.to_dict())
    assert Worker(ref(), c, tmp_path/'worker.db', identity=lambda:ref()).execute(cmd).state == 'unknown'
    assert c.entries == 1


def test_unsigned_worker_request_cannot_reach_controller(tmp_path):
    from flask import Flask
    from blueprints.broker_worker import create_worker_blueprint
    from services.combined_terminal.transport import ReplayGuard, sign, PATH
    import json
    from dataclasses import asdict
    calls=[]
    class FakeWorker:
        def execute(self,command):
            from services.combined_terminal.contracts import WorkerResult
            calls.append(command)
            return WorkerResult(command.operation_id,ref(),'accepted',{},100)
    app=Flask(__name__)
    app.register_blueprint(create_worker_blueprint(b'x'*32,ReplayGuard(tmp_path/'nonce.db'),lambda:FakeWorker(),clock=lambda:100))
    body=json.dumps({'operation_id':'op1','connection':asdict(ref()),'action':'status','payload':{},'created_at':100}).encode()
    with app.test_client() as client:
        assert client.post(PATH,data=body,content_type='application/json').status_code==403
        assert calls==[]
        headers=sign(b'x'*32,body,PATH,now=100,nonce='one')
        assert client.post(PATH,data=body,headers=headers,content_type='application/json').status_code==200
        assert len(calls)==1
        assert client.post(PATH,data=body,headers=headers,content_type='application/json').status_code==403
        assert len(calls)==1


def test_validation_failure_without_prepared_trade_is_definitive_rejection(tmp_path):
    from services.combined_terminal.worker import Worker
    c=Controller()
    def expired(ticket):raise ValueError('Preview expired')
    c.enter=expired
    result=Worker(ref(),c,tmp_path/'worker.db',identity=lambda:ref()).execute(
        WorkerCommand('expired',ref(),'enter',{'ticket':'old'},100))
    assert result.state=='rejected'


def test_read_only_receipt_recovers_validation_rejection_without_resubmission(tmp_path):
    from services.combined_terminal.worker import Worker
    c=Controller()
    def expired(ticket):raise ValueError('expired')
    c.enter=expired
    worker=Worker(ref(),c,tmp_path/'worker.db',identity=lambda:ref())
    worker.execute(WorkerCommand('entry1',ref(),'enter',{'ticket':'p'},100))
    result=worker.execute(WorkerCommand('read1',ref(),'receipt',{'operation_id':'entry1'},100))
    assert result.data['receipt']['state']=='rejected'
    assert result.data['receipt']['operation_id']=='entry1'
    assert c.entries==0


def test_external_position_price_uses_same_fresh_quotes_as_account_pnl(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from services.combined_terminal.worker import Worker
    from services.kotak_assistant.monitor import BrokerMonitor
    from test_ledger import NOW,buy
    c=Controller();position={'symbol':'NIFTY','exchange':'NFO','product':'MIS','quantity':65,'average_price':100,'ltp':90}
    books={'book_time':NOW,'orders':[],'fills':[buy('one')],'positions':[position],'discipline':{'count_verified':True}}
    monkeypatch.setattr(BrokerMonitor,'snapshot',lambda self:books)
    c.store=None;c.g=SimpleNamespace(mode='live',scope='alice:a:live',cached=lambda *a:{'cash':30000},quote=lambda *a:{'ltp':102,'bid':101.95,'ask':102,'time':NOW})
    worker=Worker(ref(),c,tmp_path/'worker.db',identity=lambda:ref(),clock=lambda:NOW)
    snap=worker.snapshot(ref())
    assert snap.quotes_fresh and snap.positions[0]['ltp']==102
    assert snap.positions[0]['quote']['time']==NOW
    assert snap.positions[0]['gross_open']==round((101.95-100)*65,2)


def test_snapshot_accepts_books_observed_during_the_read(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from services.combined_terminal.worker import Worker
    from services.kotak_assistant.monitor import BrokerMonitor
    current=[1793630000.0]
    def observed(self):
        current[0]+=0.1
        return {'book_time':current[0],'orders':[],'fills':[],'positions':[],'discipline':{'count_verified':True}}
    monkeypatch.setattr(BrokerMonitor,'snapshot',observed)
    c=Controller();c.store=None;c.g=SimpleNamespace(mode='live',scope='fixture',cached=lambda *a:{'cash':8000})
    w=Worker(ref(),c,tmp_path/'worker.db',identity=lambda:ref(),clock=lambda:current[0])
    snapshot=w.snapshot(ref())
    assert snapshot.books_complete
    assert snapshot.funds=={'availablecash':8000}
    assert snapshot.error is None
