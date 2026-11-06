"""User-selected entry orchestration; existing positions route only by saved owner."""
from dataclasses import asdict
import hashlib
import json
import time
import uuid
from sqlalchemy import update

from database.combined_terminal_db import Preview,Selection
from .contracts import ConnectionRef,EntryIntent,WorkerCommand,WorkerResult,identifier
from .ledger import encode,row


class TerminalCoordinator:
    def __init__(self,registry,ledger,transport,clock=time.time):
        self.registry,self.ledger,self.transport,self.clock=registry,ledger,transport,clock

    def select(self,user,context_id,connection_id):
        identifier(context_id)
        ref=self.registry.connection(user,connection_id)
        key=encode([user,context_id])
        generation=uuid.uuid4().hex
        with self.ledger.write() as db:
            values={'generation':generation,'reference':encode(asdict(ref))}
            if row(db,Selection,Selection.id==key):
                db.execute(update(Selection).where(Selection.id==key).values(**values))
            else:db.execute(Selection.__table__.insert().values(id=key,**values))
        return {'generation':generation,'connection_id':ref.id,'context_key':key}

    def _call(self,ref,action,payload,operation_id=None):
        command=WorkerCommand(operation_id or uuid.uuid4().hex,ref,action,payload,self.clock())
        result=self.transport.call(command)
        if result.connection!=ref or result.operation_id!=command.operation_id:
            raise ValueError('Worker response identity mismatch')
        return result

    def _check_market(self,ref,ticket):
        from services.kotak_assistant.analysis import number
        symbol,exchange=ticket['symbol'],ticket['exchange']
        meta=self._call(ref,'metadata',{'symbol':symbol,'exchange':exchange})
        quote=self._call(ref,'quote',{'symbol':symbol,'exchange':exchange})
        if meta.state!='accepted' or quote.state!='accepted':raise ValueError('Selected broker data unavailable')
        q=quote.data
        if not 0<=self.clock()-number(q.get('time',0))<=5 or number(q.get('ask',0))<=0 or number(q.get('bid',0))<=0:
            raise ValueError('Selected broker quote stale or unavailable')
        if number(q['ask'])<number(q['bid']):raise ValueError('Selected broker quote invalid')
        lot,tick,freeze=(number(meta.data.get(k,0)) for k in ('lot','tick','freeze'))
        qty=number(ticket['quantity'])
        if lot<=0 or tick<=0 or freeze<lot or qty<=0 or int(qty)!=qty or qty%lot or qty>freeze:
            raise ValueError('Selected broker contract metadata or quantity invalid')
        return meta.data,q

    def preview(self,user,connection_id,ticket):
        if not isinstance(ticket,dict):raise ValueError('Invalid ticket')
        ticket=dict(ticket)
        ref=self.registry.connection(user,connection_id)
        selection=self.select(user,ticket.pop('context_id','default'),connection_id)
        day=self.ledger.day(user,ref.mode,self.clock())
        if not day['entry_allowed']:raise ValueError(day['blocked_reason'])
        meta,quote=self._check_market(ref,ticket)
        prepared=self._call(ref,'preview',ticket)
        if prepared.state!='accepted' or not prepared.data.get('ticket'):
            raise ValueError(prepared.error or 'Selected broker preview unavailable')
        from services.kotak_assistant.analysis import number
        risk=number(prepared.data.get('plan',{}).get('risk',0))
        if not 0<risk<=1000:raise ValueError('Planned position loss must fit the shared ₹1,000 cap')
        expires=min(self.clock()+10,float(prepared.data.get('expires',0)))
        if expires<=self.clock():raise ValueError('Selected broker preview expired')
        pid=uuid.uuid4().hex
        payload_hash=hashlib.sha256(encode({'connection':asdict(ref),'ticket':ticket,'worker_ticket':prepared.data['ticket']}).encode()).hexdigest()
        with self.ledger.write() as db:
            current=row(db,Selection,Selection.id==selection['context_key'])
            if not current or current['generation']!=selection['generation']:
                raise ValueError('Ticket broker changed while preview was loading')
            db.execute(Preview.__table__.insert().values(id=pid,owner=user,context_key=selection['context_key'],
                generation=selection['generation'],reference=encode(asdict(ref)),payload=encode(ticket),
                payload_hash=payload_hash,worker_ticket=prepared.data['ticket'],
                snapshots=encode(self.ledger.snapshot_ids(user,ref.mode)),expires=expires))
        return {'preview_id':pid,'connection':asdict(ref),'expires':expires,'plan':prepared.data.get('plan',{}),
                'metadata':meta,'quote':quote,'ticket':ticket}

    def enter(self,user,preview_id,operation_id,*,connection_id=None):
        identifier(operation_id)
        with self.ledger.write() as db:
            preview=row(db,Preview,Preview.id==preview_id)
            if not preview or preview['owner']!=user:raise PermissionError('Preview unavailable')
            ref=ConnectionRef(**json.loads(preview['reference']))
            self.registry.config(ref)
            if connection_id is not None and connection_id!=ref.id:raise ValueError('Selected broker differs from preview')
            if preview['used_by']:
                if preview['used_by']!=operation_id:raise ValueError('Preview already consumed; reconcile original order')
                # Retry returns the durable receipt, regardless of later selection/expiry.
                return self.ledger.intent(user,operation_id)
            selected=row(db,Selection,Selection.id==preview['context_key'])
            if not selected or selected['generation']!=preview['generation'] or selected['reference']!=preview['reference']:
                raise ValueError('Ticket broker changed; refresh preview')
            if preview['expires']<=self.clock():raise ValueError('Preview expired; refresh preview')
        self._check_market(ref,json.loads(preview['payload']))
        # Claim the preview and reserve in one write transaction, through a nested
        # ledger call on the SAME connection (no second writer/deadlock window).
        with self.ledger.write() as db:
            fresh=row(db,Preview,Preview.id==preview_id)
            selected=row(db,Selection,Selection.id==preview['context_key'])
            if fresh['used_by']:
                if fresh['used_by']!=operation_id:raise ValueError('Preview already consumed')
                return self.ledger.intent(user,operation_id)
            if selected['generation']!=preview['generation'] or preview['expires']<=self.clock():
                raise ValueError('Ticket changed or expired')
            intent=EntryIntent(operation_id,ref,preview_id,preview['payload_hash'],'reserved')
            reserved=self.ledger.reserve_in(db,user,intent,json.loads(preview['snapshots']),self.clock())
            db.execute(update(Preview).where(Preview.id==preview_id).values(used_by=operation_id))
        try:
            result=self._call(ref,'enter',{'ticket':preview['worker_ticket']},operation_id)
        except Exception:
            result=WorkerResult(operation_id,ref,'unknown',{},self.clock(),'Broker outcome unknown; reconcile original intent')
        return self.ledger.record_result(operation_id,result)

    def mutate_trade(self,user,trade_id,action,payload):
        if action not in ('exit','stop'):raise ValueError('Unsupported trade action')
        try:
            broker,account,mode,kind,native=json.loads(trade_id)
        except (ValueError,TypeError):raise ValueError('Invalid trade identity') from None
        if kind!='trade' or not isinstance(native,str) or not native:raise ValueError('Invalid trade identity')
        matches=[r for r in self.registry.connections(user) if (r.broker,r.account,r.mode)==(broker,account,mode)]
        if len(matches)!=1:raise PermissionError('Owning connection unavailable')
        operation_id=payload.get('request_id')
        identifier(operation_id)
        if len(operation_id)>64:raise ValueError('Request identity too long')
        data={'trade_id':native}
        if action=='exit' and payload.get('quantity') is not None:data['quantity']=payload['quantity']
        if action=='stop':data['sl']=payload['sl']
        try:return self._call(matches[0],action,data,operation_id)
        except Exception:return WorkerResult(operation_id,matches[0],'unknown',{},self.clock(),'Exit/protection outcome unknown; reconcile original intent')

    def read_data(self,user,connection_id,action,payload):
        if action not in ('market','chart'):raise ValueError('Unsupported data operation')
        ref=self.registry.connection(user,connection_id)
        result=self._call(ref,action,payload)
        if result.state!='accepted':raise ValueError(result.error or 'Selected broker data unavailable')
        return result.data
