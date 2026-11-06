import json
from dataclasses import asdict
from pathlib import Path
import pytest
from test_protocol import refs


def private(path, value):
    path.write_text(value); path.chmod(0o600); return path


def test_private_registry_rejects_public_files_and_remote_workers(tmp_path):
    from services.combined_terminal.configuration import load_registry
    secret=private(tmp_path/'key','x'*32)
    path=private(tmp_path/'registry.json',json.dumps({'ledger_path':str(tmp_path/'ledger.db'),'workers':[{'connection':asdict(refs()[0]),'url':'http://127.0.0.1:5001','secret_file':str(secret)}]}))
    registry,db=load_registry(path)
    assert registry.connection('alice','kotak-main')==refs()[0]
    assert db==tmp_path/'ledger.db'
    path.chmod(0o644)
    with pytest.raises(ValueError,match='private'):load_registry(path)


def service(tmp_path, role, port):
    root=tmp_path/role;root.mkdir()
    env={'BROKER_API_KEY':'client:::api','BROKER_API_SECRET':'never-display-me','APP_KEY':'x'*64,'API_KEY_PEPPER':'y'*64,
         'FLASK_PORT':str(port),'WEBSOCKET_PORT':str(port+1000),'ZMQ_PORT':str(port+2000)}
    for key in ('DATABASE_URL','LATENCY_DATABASE_URL','LOGS_DATABASE_URL','HEALTH_DATABASE_URL','SANDBOX_DATABASE_URL'):
        env[key]='sqlite:///'+str(root/(key+'.db'))
    env['HISTORIFY_DATABASE_URL']=str(root/'history.duckdb')
    private(root/'.env','\n'.join(k+'='+v for k,v in env.items()))
    return {'role':role,'root':str(root),'env_file':str(root/'.env'),'external':role=='kotak','http_port':port,'ws_port':port+1000,'zmq_port':port+2000}


def test_launcher_refuses_duplicate_ports_shared_database_and_invalid_role(tmp_path):
    from scripts.combined_terminal.supervise import validate_services
    a,b=service(tmp_path,'kotak',5001),service(tmp_path,'flattrade',5002)
    assert len(validate_services([a,b]))==2
    with pytest.raises(ValueError,match='port'):validate_services([a,{**b,'http_port':5001}])
    env=Path(b['env_file']);env.write_text(env.read_text().replace(str(Path(b['root'])/'DATABASE_URL.db'),str(Path(a['root'])/'DATABASE_URL.db')))
    with pytest.raises(ValueError,match='database'):validate_services([a,b])
    with pytest.raises(ValueError,match='role'):validate_services([{**a,'role':'delta'}])


def test_missing_credentials_never_echo_values(tmp_path):
    from scripts.combined_terminal.supervise import validate_services
    item=service(tmp_path,'flattrade',5002)
    p=Path(item['env_file']);p.write_text(p.read_text().replace('BROKER_API_KEY=client:::api','BROKER_API_KEY='))
    with pytest.raises(ValueError) as err:validate_services([item])
    assert 'never-display-me' not in str(err.value)


def test_stopped_child_restarts_without_touching_external_kotak():
    from scripts.combined_terminal.supervise import Supervisor
    calls=[]
    class Child:
        def poll(self):return 1
    def spawn(item):calls.append(item['role']);return Child()
    supervisor=Supervisor([{'role':'kotak','external':True},{'role':'flattrade','external':False}],spawn)
    supervisor.tick();supervisor.tick()
    assert calls==['flattrade','flattrade']


def test_worker_host_validates_identity_before_dispatch_and_protection(tmp_path):
    from services.combined_terminal.host import WorkerHost
    from services.combined_terminal.worker import Worker
    from services.combined_terminal.contracts import WorkerCommand
    from test_worker import Controller
    c=Controller();c.reconcile=lambda:pytest.fail('wrong account protection')
    worker=Worker(refs()[0],c,tmp_path/'worker.db',identity=lambda:refs()[1])
    host=WorkerHost([worker])
    with pytest.raises(PermissionError):host.execute(WorkerCommand('op1',refs()[0],'enter',{'ticket':'p'},100))
    host.reconcile_once()
    assert c.entries==0


def test_worker_protection_runs_without_central_or_browser(tmp_path):
    from services.combined_terminal.host import WorkerHost
    from services.combined_terminal.worker import Worker
    from test_worker import Controller
    c=Controller();calls=[]
    c.state=lambda:{'trades':{'existing':{'status':'open'}}}
    c.reconcile=lambda:calls.append('protected')
    host=WorkerHost([Worker(refs()[0],c,tmp_path/'worker.db',identity=lambda:refs()[0])])
    host.reconcile_once(); assert calls==['protected']


def test_missing_registry_returns_setup_required_without_enabling_orders(monkeypatch):
    from services.combined_terminal import runtime
    monkeypatch.setenv('COMBINED_TERMINAL_ENABLED','true')
    monkeypatch.delenv('COMBINED_TERMINAL_CONFIG',raising=False)
    monkeypatch.setattr(runtime,'_instance',None)
    state=runtime.get_runtime().snapshot('alice','live')
    assert state['setup_required'] and not state['day']['entry_allowed']
    assert state['summary']['estimated_total_net'] is None


def test_flattrade_oauth_requires_matching_client_before_token_exchange(monkeypatch):
    from services.combined_terminal.flattrade_gateway import callback_client
    monkeypatch.setenv('BROKER_API_KEY','CLIENT:::api')
    assert callback_client('CLIENT')=='CLIENT'
    with pytest.raises(ValueError):callback_client('OTHER')
    with pytest.raises(ValueError):callback_client(None)


def test_worker_checks_recent_terminal_trades_for_delayed_fills(tmp_path):
    from services.combined_terminal.host import WorkerHost
    from services.combined_terminal.worker import Worker
    from test_worker import Controller
    c=Controller();calls=[]
    c.state=lambda:{'trades':{'existing':{'status':'closed','created':100}}}
    c.reconcile=lambda:calls.append('late-fill-check')
    host=WorkerHost([Worker(refs()[0],c,tmp_path/'worker.db',identity=lambda:refs()[0])],clock=lambda:101)
    host.reconcile_once();host.reconcile_once()
    assert calls==['late-fill-check']
