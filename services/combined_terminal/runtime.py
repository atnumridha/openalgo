"""Bounded independent account polling; browser reads never dispatch orders."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import os
import threading
import time
import uuid
from sqlalchemy import select,update

from database.combined_terminal_db import Intent,Preview,Preference
from .contracts import AccountSnapshot,WorkerCommand,WorkerResult
from .ledger import row,encode,RELEASED
from .coordinator import TerminalCoordinator
from .aggregate import aggregate


class Runtime:
    enabled=True
    def __init__(self,registry,ledger,transport,clock=time.time):
        self.registry,self.ledger,self.transport,self.clock=registry,ledger,transport,clock
        self.coordinator=TerminalCoordinator(registry,ledger,transport,clock)
        self._poll_gate=threading.Lock()
        self._stop=threading.Event()
        self._thread=None
        self._threads=[]
        self._start_lock=threading.Lock()

    def _read(self,ref,now):
        prior=next((s for s in self.ledger.snapshots(ref.owner,ref.mode) if s.connection==ref),None)
        try:
            command=WorkerCommand(uuid.uuid4().hex,ref,'snapshot',{},now)
            result=self.transport.call(command)
            if result.connection!=ref or result.operation_id!=command.operation_id or result.state!='accepted':
                raise ValueError('Worker identity or snapshot unavailable')
            snap=AccountSnapshot.from_dict(result.data['snapshot'])
            if snap.connection!=ref or snap.captured_at>self.clock()+1:raise ValueError('Account snapshot identity mismatch')
            managed=result.data.get('managed_trades',[])
            if not isinstance(managed,list):raise ValueError('Invalid owned trades')
            snap=replace(snap,managed_trades=managed)
            self.ledger.observe(snap,self.clock())
            self._receipts(ref,managed)
        except Exception:
            # Retain last-known ownership/SL/quantity, but never label it fresh.
            stale=replace(prior,books_complete=False,quotes_fresh=False,
                          realized_net=None,estimated_open_net=None,error='Broker connection unavailable; last known positions retained') if prior else AccountSnapshot(
                              ref,now,False,False,error='Broker connection unavailable')
            self.ledger.observe(stale,self.clock())

    def _receipts(self,ref,trades):
        with self.ledger.engine.connect() as db:
            pending=db.execute(select(Intent).where(Intent.connection_id==ref.id,Intent.filled==False)).mappings().all()
            pending=[dict(r) for r in pending if r['state'] not in RELEASED]
            previews={r['preview_id']:row(db,Preview,Preview.id==r['preview_id']) for r in pending}
        for intent in pending:
            preview=previews[intent['preview_id']]
            if not preview:continue
            trade=next((t for t in trades if t.get('id')==preview['worker_ticket']),None)
            if not trade:
                # Ask the durable worker receipt, never repeat the mutation.
                command=WorkerCommand(uuid.uuid4().hex,ref,'receipt',{'operation_id':intent['id']},self.clock())
                read=self.transport.call(command)
                if read.connection!=ref or read.operation_id!=command.operation_id or read.state!='accepted':continue
                receipt=read.data.get('receipt')
                if not receipt:continue  # Absence cannot prove rejection.
                result=WorkerResult.from_dict(receipt)
                if result.connection!=ref or result.operation_id!=intent['id']:raise ValueError('Receipt identity mismatch')
                self.ledger.record_result(intent['id'],result)
                continue
            entry=next((o for o in trade.get('ops',[]) if o.get('role')=='entry'),{})
            state=entry.get('state','unknown')
            if entry.get('broker_status') in ('rejected','cancelled','canceled') and not trade.get('entry_quantity',0):state='rejected'
            if state not in ('accepted','rejected','unknown'):state='unknown'
            self.ledger.record_result(intent['id'],WorkerResult(intent['id'],ref,state,trade,self.clock()))

    def reconcile_once(self,now=None):
        if not self._poll_gate.acquire(blocking=False):return
        try:
            now=self.clock() if now is None else now
            refs=[w.connection for w in self.registry._workers.values()]
            with ThreadPoolExecutor(max_workers=2,thread_name_prefix='combined-read') as pool:
                futures=[pool.submit(self._read,ref,now) for ref in refs]
                for f in futures:
                    try:f.result()
                    except Exception:pass  # Individual account failure cannot stop its neighbor.
        finally:self._poll_gate.release()

    def _settings(self,user,mode):
        with self.ledger.engine.connect() as db:
            stored=row(db,Preference,Preference.id==encode([user,mode]))
        return {'reminder_seconds':120,**(json.loads(stored['body']) if stored else {})}

    def configure(self,user,mode,settings):
        if not self.registry.connections(user) or mode not in ('live','analyze'):raise PermissionError('Account unavailable')
        if set(settings)!={'reminder_seconds'}:raise ValueError('Unsupported terminal preference')
        seconds=settings['reminder_seconds']
        if type(seconds) is not int or not 30<=seconds<=3600:raise ValueError('Reminder interval must be 30–3600 seconds')
        with self.ledger.write() as db:
            key=encode([user,mode]);value=encode({'reminder_seconds':seconds})
            if row(db,Preference,Preference.id==key):db.execute(update(Preference).where(Preference.id==key).values(body=value))
            else:db.execute(Preference.__table__.insert().values(id=key,body=value))
        return self._settings(user,mode)

    def snapshot(self,user,mode):
        if mode not in ('live','analyze'):raise ValueError('Invalid mode')
        now=self.clock()
        refs=[c for c in self.registry.connections(user) if c.mode==mode]
        saved={s.connection.id:s for s in self.ledger.snapshots(user,mode)}
        snapshots=[saved.get(c.id,AccountSnapshot(c,now,False,False,error='Waiting for account connection')) for c in refs]
        state=aggregate(snapshots,self.ledger.day(user,mode,now),now)
        return {**state,'settings':self._settings(user,mode),'mode':mode,'setup_required':not bool(refs)}

    def _poll_account(self, ref):
        # Each account has its own single-flight loop. A slow/disconnected broker
        # cannot hold its neighbor's refresh. One second is the target start cadence.
        while not self._stop.is_set():
            started=self.clock()
            try:self._read(ref,started)
            except Exception:pass
            self._stop.wait(max(0,1-(self.clock()-started)))

    def start(self):
        with self._start_lock:
            if any(t.is_alive() for t in self._threads):return
            self._stop.clear()
            self._threads=[threading.Thread(target=self._poll_account,args=(w.connection,),
                          daemon=True,name='combined-read-'+w.connection.broker)
                           for w in self.registry._workers.values()]
            for thread in self._threads:thread.start()

    def stop(self):
        self._stop.set()
        for thread in self._threads:thread.join(timeout=6)


class SetupRuntime:
    enabled=True
    coordinator=None
    def snapshot(self,user,mode):
        if mode not in ('live','analyze'):raise ValueError('Invalid mode')
        from .ledger import day_at
        now=time.time()
        return {'connections':[],'positions':[],'history':[],'fills':[],'mode':mode,'updated_at':now,
                'setup_required':True,'settings':{'reminder_seconds':120},
                'summary':{'complete':False,'realized_net':None,'estimated_open_net':None,'estimated_total_net':None,
                           'reason':'Private broker configuration required'},
                'day':{'date':day_at(now),'entries':0,'reserved_entries':0,'remaining_entries':0,'max_entries':3,
                       'loss_limit':1000,'profit_target':2000,'net':None,'entry_allowed':False,'count_verified':False,
                       'loss_reached':False,'profit_reached':False,'updated_at':now,'blocked_reason':'Broker setup required'}}
    def start(self):pass
    def configure(self,*args,**kwargs):raise ValueError('Broker setup required')


class DisabledRuntime:
    enabled=False


_instance=None
_instance_lock=threading.Lock()


def get_runtime():
    global _instance
    if os.getenv('COMBINED_TERMINAL_ENABLED','').lower()!='true':return DisabledRuntime()
    with _instance_lock:
        if _instance is None:
            # Private registry/service wiring is configured by the isolated launcher.
            from .configuration import configured_runtime
            try:_instance=configured_runtime()
            except (ValueError,KeyError,TypeError,OSError):_instance=SetupRuntime()
            _instance.start()
        return _instance
