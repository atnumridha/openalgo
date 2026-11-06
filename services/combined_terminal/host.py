"""Broker-local worker host and browser-independent protection supervisor."""
import atexit
import os
import threading
import time
from dataclasses import replace

from .configuration import document,private_bytes,absolute_db
from .contracts import ConnectionRef
from .worker import Worker


class WorkerHost:
    def __init__(self,workers,clock=time.time):
        self.workers={w.connection.id:w for w in workers}
        if len(self.workers)!=len(workers):raise ValueError('Duplicate worker identity')
        self.clock=clock;self._terminal_checks={}
        self._stop=threading.Event();self._thread=None;self._gate=threading.Lock()

    def execute(self,command):
        worker=self.workers.get(command.connection.id)
        if worker is None:raise PermissionError('Worker connection unavailable')
        return worker.execute(command)

    def reconcile_once(self):
        if not self._gate.acquire(blocking=False):return
        try:
            for worker in self.workers.values():
                try:
                    if worker.identity()!=worker.connection:continue
                    now=self.clock();trades=list(worker.controller.state().get('trades',{}).values())
                    active=any(t.get('status') not in ('closed','rejected') for t in trades)
                    recent=any(0<=now-t.get('created',now)<=86400 for t in trades)
                    due=now-self._terminal_checks.get(worker.connection.id,float('-inf'))>=5
                    if active or (recent and due):
                        worker.controller.reconcile()
                        self._terminal_checks[worker.connection.id]=now
                except Exception:
                    # Fail closed on changed login; retain durable protection state.
                    pass
                finally:
                    from services.kotak_assistant.runtime import cleanup_sessions
                    cleanup_sessions()
        finally:self._gate.release()

    def start(self):
        if self._thread and self._thread.is_alive():return
        def loop():
            while not self._stop.is_set():
                self.reconcile_once();self._stop.wait(1)
        self._thread=threading.Thread(target=loop,daemon=True,name='broker-owned-protection')
        self._thread.start();atexit.register(self._stop.set)


def configured_host():
    cfg=document(os.environ.get('COMBINED_WORKER_CONFIG',''))
    refs=[ConnectionRef(**r) for r in cfg['connections']]
    if not refs or len({(r.broker,r.account,r.owner) for r in refs})!=1:raise ValueError('Worker must serve one fixed broker account')
    operation_path=absolute_db(cfg['operation_path']);nonce_path=absolute_db(cfg['nonce_path'])
    if operation_path==nonce_path:raise ValueError('Worker databases must be distinct')
    for p in (operation_path,nonce_path):p.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    workers=[]
    for ref in refs:
        if ref.broker=='kotak':
            from services.kotak_assistant.runtime import controller
            c=controller(ref.owner,ref.mode)
        else:
            from services.kotak_assistant.store import Store
            from services.kotak_assistant.execution import Coordinator
            from .flattrade_gateway import FlattradeGateway
            c=Coordinator(Store(),FlattradeGateway(ref.owner,ref.mode))
        if c.g.account!=ref.account:raise ValueError('Configured broker account does not match worker environment')
        def identity(c=c,ref=ref):
            c.g.credentials()
            if c.g.account!=ref.account:raise PermissionError('Broker login identity changed')
            return ref
        workers.append(Worker(ref,c,operation_path,identity=identity))
    return WorkerHost(workers),private_bytes(cfg['secret_file']).strip(),nonce_path


def install_worker(app,csrf):
    if os.getenv('COMBINED_WORKER_ENABLED','').lower()!='true':return
    from blueprints.broker_worker import create_worker_blueprint
    from .transport import ReplayGuard
    host,secret,path=configured_host()
    if len(secret)<32:raise ValueError('Worker signing key unavailable')
    blueprint=create_worker_blueprint(secret,ReplayGuard(path),lambda:host)
    app.register_blueprint(blueprint);csrf.exempt(blueprint)
    app.extensions['combined_worker']=host
    host.start()
