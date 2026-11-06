"""Real signed loopback HTTP workers + public Flask routes + durable SQLite.
All broker behavior is fake; no production credentials or orders are used.
"""
from contextlib import contextmanager,ExitStack
from dataclasses import asdict
import json
import threading
from concurrent.futures import ThreadPoolExecutor

from flask import Flask
from werkzeug.serving import make_server
from sqlalchemy import create_engine

from services.combined_terminal.contracts import WorkerResult,scoped_id
from services.combined_terminal.worker import Worker
from services.combined_terminal.registry import Registry,WorkerConfig
from services.combined_terminal.transport import Transport,ReplayGuard
from services.combined_terminal.ledger import Ledger
from services.combined_terminal.runtime import Runtime
from blueprints.broker_worker import create_worker_blueprint
from blueprints.combined_terminal import create_combined_terminal_blueprint
from test_ledger import NOW,connections,snapshot,buy
from test_routing import ticket


class Controller:
    def __init__(self,path):
        self.path=path
        self.data=json.loads(path.read_text()) if path.exists() else {'trades':{},'calls':[],'fills':[]}
        self.timeout=False
        self.g=self
    def save(self):self.path.write_text(json.dumps(self.data))
    def state(self):return self.data
    def quote(self,*args):return {'ltp':100,'ask':100,'bid':99.95,'time':NOW}
    def metadata(self,*args):return {'lot':65,'tick':.05,'freeze':1800}
    def preview(self,p):return {'ticket':'trade-'+str(len(self.data['calls'])),'expires':NOW+5,'plan':{'risk':650}}
    def enter(self,key):
        self.data['calls'].append('enter')
        trade={'id':key,'symbol':'NIFTY27OCT2623000CE','exchange':'NFO','product':'MIS','remaining':65,'entry_quantity':65,
               'status':'open','current_sl':90,'target':120,'quote':self.quote(),
               'ops':[{'role':'entry','state':'accepted','orderid':'same-broker-id'}]}
        self.data['trades'][key]=trade
        self.data['fills'].append(buy('same-broker-id'))
        self.save()
        if self.timeout:raise TimeoutError('lost response')
        return trade
    def exit(self,key,qty,request_id):
        self.data['calls'].append('exit');trade=self.data['trades'][key]
        trade.update(remaining=0,status='closed');self.save();return trade


class FakeWorker(Worker):
    def snapshot(self,ref):return snapshot(ref,fills=self.controller.data['fills'])


@contextmanager
def serving(worker,path,secret):
    app=Flask('fake-worker')
    app.register_blueprint(create_worker_blueprint(secret,ReplayGuard(path),lambda:worker,clock=lambda:NOW))
    server=make_server('127.0.0.1',0,app,threaded=True)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:yield 'http://127.0.0.1:'+str(server.server_port)
    finally:server.shutdown();thread.join(timeout=2)


@contextmanager
def system(tmp_path):
    with ExitStack() as stack:
        workers=[];configs=[];controllers=[]
        for index,ref in enumerate(connections()):
            c=Controller(tmp_path/f'controller{index}.json');controllers.append(c)
            worker=FakeWorker(ref,c,tmp_path/f'worker{index}.db',identity=lambda r=ref:r,clock=lambda:NOW);workers.append(worker)
            secret=bytes([65+index])*32
            url=stack.enter_context(serving(worker,tmp_path/f'nonce{index}.db',secret))
            configs.append(WorkerConfig(ref,url,secret))
        registry=Registry(configs);ledger=Ledger(create_engine('sqlite:///'+str(tmp_path/'ledger.db')),connections())
        transport=Transport(registry,clock=lambda:NOW)
        runtime=Runtime(registry,ledger,transport,clock=lambda:NOW);runtime.reconcile_once()
        app=Flask('combined-integration');app.secret_key='test-only-session-key'
        app.register_blueprint(create_combined_terminal_blueprint(lambda:runtime))
        def client():
            c=app.test_client()
            with c.session_transaction() as session:session['user']='alice'
            return c
        yield runtime,controllers,workers,client
        transport.client.close()


def post(client,path,data):
    result=client.post('/combined-terminal/api/'+path,json=data)
    assert result.status_code==200,result.json
    return result.json['data']


def test_two_brokers_real_http_owner_exit_outage_and_restart(tmp_path):
    with system(tmp_path) as (runtime,controllers,workers,client):
        c=client();previews=[]
        for index,ref in enumerate(connections()):
            p=post(c,'preview',{'connection_id':ref.id,'ticket':{**ticket(),'context_id':'tab'+str(index)}});previews.append(p)
            post(c,'entry',{'connection_id':ref.id,'preview_id':p['preview_id'],'operation_id':'entry'+str(index)})
            runtime.reconcile_once()
        assert [x.data['calls'] for x in controllers]==[['enter'],['enter']]
        assert runtime.snapshot('alice','live')['day']['entries']==2
        # Selection of Flattrade must not redirect the Kotak exit.
        post(c,'selection',{'context_id':'tab0','connection_id':'flat'})
        post(c,'trade-action',{'trade_id':scoped_id(connections()[0],'trade','trade-0'),'action':'exit','payload':{'request_id':'close-one','connection_id':'flat'}})
        assert [x.data['calls'] for x in controllers]==[['enter','exit'],['enter']]
        # Replay both HTTP and central intents: neither creates another broker entry.
        post(c,'entry',{'connection_id':'kotak','preview_id':previews[0]['preview_id'],'operation_id':'entry0'})
        command=next(iter(workers[0].controller.data['trades']))
        assert command=='trade-0'
        runtime.reconcile_once()
        restored=Runtime(runtime.registry,Ledger(create_engine('sqlite:///'+str(tmp_path/'ledger.db')),connections()),runtime.transport,clock=lambda:NOW)
        assert restored.snapshot('alice','live')['day']['entries']==2
        assert controllers[0].data['calls'].count('enter')==1
        original=runtime.transport.call
        def outage(cmd):
            if cmd.connection.id=='flat':raise TimeoutError()
            return original(cmd)
        runtime.transport.call=outage;runtime.reconcile_once()
        assert runtime.snapshot('alice','live')['summary']['estimated_total_net'] is None
        assert len(runtime.snapshot('alice','live')['positions'])==1
        runtime.transport.call=original;runtime.reconcile_once()
        assert runtime.snapshot('alice','live')['summary']['complete']


def test_real_http_last_slot_contention_and_external_fills(tmp_path):
    with system(tmp_path) as (runtime,controllers,workers,client):
        controllers[0].data['fills']=[buy('external1'),buy('external2')]
        controllers[0].save();runtime.reconcile_once()
        previews=[post(client(),'preview',{'connection_id':r.id,'ticket':{**ticket(),'context_id':'tab'+r.id}}) for r in connections()]
        def enter(index):
            return client().post('/combined-terminal/api/entry',json={'connection_id':connections()[index].id,'preview_id':previews[index]['preview_id'],'operation_id':'race'+str(index)}).status_code
        with ThreadPoolExecutor(2) as pool:results=list(pool.map(enter,[0,1]))
        assert sorted(results)==[200,409]
        assert sum(x.data['calls'].count('enter') for x in controllers)==1


def test_real_http_unknown_submission_reconciles_without_duplicate(tmp_path):
    with system(tmp_path) as (runtime,controllers,workers,client):
        controllers[0].timeout=True
        p=post(client(),'preview',{'connection_id':'kotak','ticket':ticket()})
        receipt=post(client(),'entry',{'connection_id':'kotak','preview_id':p['preview_id'],'operation_id':'unknown1'})
        assert receipt['state']=='unknown'
        assert not runtime.snapshot('alice','live')['day']['entry_allowed']
        runtime.reconcile_once()
        assert runtime.ledger.intent('alice','unknown1').state in ('accepted','filled')
        post(client(),'entry',{'connection_id':'kotak','preview_id':p['preview_id'],'operation_id':'unknown1'})
        assert controllers[0].data['calls']==['enter']
        assert controllers[1].data['calls']==[]


def test_expired_entry_reports_no_submission_and_creates_no_intent(tmp_path):
    with system(tmp_path) as (runtime,controllers,workers,client):
        c=client();p=post(c,'preview',{'connection_id':'kotak','ticket':ticket()})
        runtime.coordinator.clock=lambda:NOW+6
        response=c.post('/combined-terminal/api/entry',json={'connection_id':'kotak','preview_id':p['preview_id'],'operation_id':'expired1'})
        assert response.status_code==409 and response.json['submission']=='not_submitted'
        assert all(x.data['calls']==[] for x in controllers)
