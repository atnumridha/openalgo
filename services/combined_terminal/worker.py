"""Broker-local execution facade with durable dispatch-before-I/O idempotency."""
import hashlib
import json
import sqlite3
import time
from datetime import datetime

from .contracts import AccountSnapshot, WorkerResult, MUTATIONS


def fingerprint(command):
    return hashlib.sha256(json.dumps({'connection':command.to_dict()['connection'],
        'action':command.action,'payload':command.payload},sort_keys=True,allow_nan=False).encode()).hexdigest()


def safe_data(value):
    # Broker raw responses never belong in public terminal data.
    blocked={'auth','token','feed_token','apikey','api_key','secret','api_secret','raw','headers',
             'broker_error','broker_response','broker_api_key','broker_api_secret'}
    if isinstance(value,dict):
        return {k:safe_data(v) for k,v in value.items() if k.lower() not in blocked}
    if isinstance(value,list):return [safe_data(v) for v in value]
    return value


class Worker:
    def __init__(self, connection, controller, path, *, identity, clock=time.time):
        self.connection,self.controller,self.path,self.identity,self.clock=connection,controller,str(path),identity,clock
        with sqlite3.connect(self.path) as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('CREATE TABLE IF NOT EXISTS combined_worker_operation (id TEXT PRIMARY KEY, hash TEXT NOT NULL, result TEXT)')

    def execute(self,command):
        if command.connection!=self.connection or self.identity()!=self.connection:
            raise PermissionError('Worker account identity mismatch')
        durable=command.action in MUTATIONS or command.action=='preview'
        if durable:
            with sqlite3.connect(self.path,timeout=5) as db:
                db.execute('BEGIN IMMEDIATE')
                row=db.execute('SELECT hash,result FROM combined_worker_operation WHERE id=?',(command.operation_id,)).fetchone()
                if row:
                    if row[0]!=fingerprint(command):raise ValueError('Operation payload changed')
                    if row[1]:return WorkerResult.from_dict(json.loads(row[1]))
                    return WorkerResult(command.operation_id,self.connection,'unknown',{},self.clock(),'Dispatch pending; reconcile original intent')
                db.execute('INSERT INTO combined_worker_operation VALUES (?,?,NULL)',(command.operation_id,fingerprint(command)))
        try:
            data=self._dispatch(command)
            state='accepted'
            if command.action=='enter':
                ops=data.get('ops',[])
                entry=next((o for o in ops if o.get('role')=='entry'),ops[0] if ops else {})
                state=entry.get('state','unknown')
                if state not in ('accepted','rejected','unknown'):state='unknown'
            result=WorkerResult(command.operation_id,self.connection,state,safe_data(data),self.clock())
        except Exception as error:
            state='unknown' if command.action in MUTATIONS else 'rejected'
            if command.action=='enter' and isinstance(error,ValueError):
                try:
                    if command.payload.get('ticket') not in self.controller.state().get('trades',{}):
                        state='rejected'  # Coordinator persists a trade before any broker I/O.
                except Exception:pass
            result=WorkerResult(command.operation_id,self.connection,state,
                {},self.clock(),'Operation outcome unknown; reconcile original intent' if command.action in MUTATIONS else 'Broker data or preview unavailable')
        if durable:
            with sqlite3.connect(self.path) as db:
                db.execute('UPDATE combined_worker_operation SET result=? WHERE id=?',
                    (json.dumps(result.to_dict(),allow_nan=False),command.operation_id))
        return result

    def _dispatch(self,command):
        c,p=self.controller,command.payload
        if command.action in ('market','chart'):
            from .market import MarketData
            market=MarketData(c)
            return market.snapshot(p) if command.action=='market' else market.chart(p)
        if command.action=='receipt':
            from .contracts import identifier
            operation_id=p['operation_id'];identifier(operation_id)
            with sqlite3.connect(self.path) as db:
                stored=db.execute('SELECT result FROM combined_worker_operation WHERE id=?',(operation_id,)).fetchone()
            if not stored or not stored[0]:return {'receipt':None}
            receipt=WorkerResult.from_dict(json.loads(stored[0]))
            if receipt.connection!=self.connection:raise PermissionError('Receipt account mismatch')
            return {'receipt':receipt.to_dict()}
        if command.action=='status':return {'ready':True,'broker':self.connection.broker}
        if command.action=='snapshot':
            return {'snapshot':self.snapshot(self.connection).to_dict(),
                    'managed_trades':safe_data(list(c.state().get('trades',{}).values())),
                    'settings':c.state().get('settings',{})}
        if command.action=='metadata':return c.g.metadata(p['symbol'],p['exchange'])
        if command.action=='quote':return c.g.quote(p['symbol'],p['exchange'])
        if command.action=='history':return {'candles':c.g.history_range(p['symbol'],p['exchange'],p['interval'],p['start'],p['end'])}
        if command.action=='ladder':return c.g.ladder(p['underlying'],p['expiry'],p.get('count',8))
        if command.action=='preview':return c.preview(p)
        if command.action=='enter':return c.enter(p['ticket'])
        if command.action=='exit':return c.exit(p['trade_id'],p.get('quantity'),command.operation_id)
        if command.action=='stop':return c.tighten(p['trade_id'],p['sl'])
        if command.action=='reconcile':return c.reconcile()
        # Raw cancel is intentionally unavailable: the owning controller coordinates
        # cancel/replace and position reduction without leaving exposure unprotected.
        raise ValueError('Unsupported worker operation')

    def snapshot(self,connection):
        if connection!=self.connection or self.identity()!=self.connection:
            raise PermissionError('Worker account identity mismatch')
        from services.kotak_assistant.analysis import journal,IST
        from services.kotak_assistant.discipline import liquidation
        from services.kotak_assistant.monitor import BrokerMonitor
        c=self.controller
        now=self.clock()
        try:
            if connection.mode=='live':
                seen=BrokerMonitor(c.store,c.g,clock=self.clock).snapshot()
                if seen.get('error') or not seen.get('book_time'):raise ValueError('Incomplete account observation')
                books={**seen,'time':seen['book_time']}
            else:books=c.books()
            # A fresh broker read can finish after the request started.
            now=self.clock()
            if not 0<=now-books['time']<=10:raise ValueError('Stale books')
            try:funds=c.g.funds()
            except Exception:funds=None
            settings=c.state().get('settings',{})
            day=datetime.fromtimestamp(now,IST).date().isoformat()
            j=journal(books['fills'],books['positions'],day,settings.get('brokerage',0))
            complete=bool(j['complete']) and (connection.mode!='live' or seen.get('discipline',{}).get('count_verified',False))
            realized=j['net_realised'] if complete else None
            net=None;exit_charges=None;quotes={}
            if realized is not None:
                try:
                    quotes={(r['symbol'],r['exchange']):c.g.quote(r['symbol'],r['exchange']) for r in j['open_positions']}
                    liquidated=liquidation(j,quotes,settings.get('brokerage',0),day,now)
                    net=liquidated['net'];exit_charges=liquidated['estimated_liquidation_costs']
                except (ValueError,KeyError,TypeError):pass
            from services.kotak_assistant.analysis import fees,number
            bases={(r['symbol'],r['exchange'],r['product']):r for r in j['open_positions']}
            marked=[]
            for position in books['positions']:
                p=dict(position);basis=bases.get((p['symbol'],p['exchange'],p['product']))
                q=quotes.get((p['symbol'],p['exchange']))
                if q and basis and 0<=now-q.get('time',0)<=5 and number(q.get('bid',0))>0:
                    qty=int(basis['quantity']);bid=number(q['bid'])
                    gross=round((bid-number(basis['average_price']))*qty,2)
                    cost=fees(0,bid*qty,p['exchange'],0,day)['total']+settings.get('brokerage',0)*1.18
                    p.update(ltp=q.get('ltp'),quote=q,average_entry=basis['average_price'],gross_open=gross,net_open=round(gross-cost,2))
                else:p.update(ltp=None,gross_open=None,net_open=None)
                marked.append(p)
            return AccountSnapshot(connection,books['time'],complete,net is not None,
                books['orders'],books['fills'],marked,{'availablecash':funds['cash']} if funds else None,
                realized,None if net is None or realized is None else round(net-realized,2),
                charges=j['charges'] if complete else None,
                estimated_exit_charges=round(exit_charges,2) if exit_charges is not None else None)
        except Exception:
            return AccountSnapshot(connection,now,False,False,error='Broker account snapshot unavailable')
