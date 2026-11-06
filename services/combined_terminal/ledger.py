"""One transactional entry budget across all configured broker accounts."""
from contextlib import contextmanager
from dataclasses import asdict, replace
from datetime import datetime
import hashlib
import json
from zoneinfo import ZoneInfo
from sqlalchemy import select, update

from database.combined_terminal_db import Base,Intent,Observation,Fill,Day
from .contracts import EntryIntent,ConnectionRef,AccountSnapshot,scoped_id

IST=ZoneInfo('Asia/Kolkata')
RELEASED={'rejected','cancelled'}


def encode(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)


def day_at(now):
    return datetime.fromtimestamp(now,IST).date().isoformat()


def row(db,table,condition):
    result=db.execute(select(table).where(condition)).mappings().first()
    return dict(result) if result else None


def intent_row(value):
    return EntryIntent(value['id'],ConnectionRef(**json.loads(value['reference'])),
                       value['preview_id'],value['payload_hash'],value['state'])


class Ledger:
    def __init__(self,engine,connections):
        if engine.dialect.name!='sqlite':raise ValueError('Combined ledger requires SQLite')
        self.engine=engine
        self.connections={c.id:c for c in connections}
        if len(self.connections)!=len(connections):raise ValueError('Duplicate connection')
        Base.metadata.create_all(engine)
        with engine.connect() as db:
            db.exec_driver_sql('PRAGMA journal_mode=WAL')

    @contextmanager
    def write(self):
        with self.engine.connect() as db:
            db.exec_driver_sql('BEGIN IMMEDIATE')
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise

    def _refs(self,user,mode):
        return [c for c in self.connections.values() if c.owner==user and c.mode==mode]

    def _observations(self,db,user,mode):
        result={}
        for ref in self._refs(user,mode):
            seen=row(db,Observation,Observation.connection_id==ref.id)
            if seen:
                snap=AccountSnapshot.from_dict(json.loads(seen['body']))
                if snap.connection==ref:result[ref.id]=(seen['snapshot_id'],snap)
        return result

    def snapshot_ids(self,user,mode):
        with self.engine.connect() as db:
            return {key:seen[0] for key,seen in self._observations(db,user,mode).items()}

    def snapshots(self,user,mode):
        with self.engine.connect() as db:
            return [seen[1] for seen in self._observations(db,user,mode).values()]

    def _day(self,db,user,mode,now):
        day=day_at(now)
        key=encode([user,mode,day])
        old=row(db,Day,Day.id==key)
        previous=json.loads(old['body']) if old else {}
        fills=db.execute(select(Fill).where(Fill.owner==user,Fill.mode==mode,Fill.day==day)).mappings().all()
        entry_keys={f['order_key'] for f in fills if json.loads(f['body'])['action']=='BUY'}
        active=db.execute(select(Intent).where(Intent.owner==user,Intent.mode==mode)).mappings().all()
        reserved=[i for i in active if not i['filled'] and i['state'] not in RELEASED]
        pending_today=sum(i['day']==day for i in reserved)
        observations=self._observations(db,user,mode)
        required=self._refs(user,mode)
        complete=bool(required) and len(observations)==len(required) and all(
            s.books_complete and s.quotes_fresh and not s.error and 0<=now-s.captured_at<=5
            and s.realized_net is not None and s.estimated_open_net is not None
            for _,s in observations.values())
        net=round(sum(s.realized_net+s.estimated_open_net for _,s in observations.values()),2) if complete else None
        loss=previous.get('loss_reached',False) or (net is not None and net<=-1000)
        profit=previous.get('profit_reached',False) or (net is not None and net>=2000)
        entries=len(entry_keys)
        older=any(i['day']!=day for i in reserved)
        unknown=any(i['state']=='unknown' for i in reserved)
        reason='Prior session has an unresolved entry' if older else 'An unresolved unknown entry must reconcile before a replacement' if unknown else 'Combined account data incomplete or stale' if not complete else 'Daily loss limit reached' if loss else 'Daily entry limit reached' if entries+pending_today>=3 else None
        result={'date':day,'entries':entries,'reserved_entries':pending_today,'max_entries':3,
                'remaining_entries':max(0,3-entries-pending_today),'excess_entries':max(0,entries-3),
                'net':net,'pnl_available':net is not None,'loss_limit':1000,'profit_target':2000,
                'loss_reached':bool(loss),'profit_reached':bool(profit),'count_verified':complete,
                'blocked_reason':reason,'entry_allowed':reason is None,'updated_at':now}
        if not previous.get('loss_reached') and loss:result.update(loss_reached_at=now,loss_reached_net=net)
        elif previous.get('loss_reached_at'):result.update(loss_reached_at=previous['loss_reached_at'],loss_reached_net=previous.get('loss_reached_net'))
        if not previous.get('profit_reached') and profit:result.update(profit_reached_at=now,profit_reached_net=net)
        elif previous.get('profit_reached_at'):result.update(profit_reached_at=previous['profit_reached_at'],profit_reached_net=previous.get('profit_reached_net'))
        if old:db.execute(update(Day).where(Day.id==key).values(body=encode(result)))
        else:db.execute(Day.__table__.insert().values(id=key,body=encode(result)))
        return result

    def day(self,user,mode,now):
        with self.write() as db:return self._day(db,user,mode,now)

    def reserve(self,user,intent,snapshot_ids,now):
        with self.write() as db:
            return self.reserve_in(db,user,intent,snapshot_ids,now)

    def reserve_in(self,db,user,intent,snapshot_ids,now):
        ref=intent.connection
        if ref.owner!=user or self.connections.get(ref.id)!=ref:
            raise PermissionError('Connection unavailable')
        previous=row(db,Intent,Intent.id==intent.operation_id)
        if previous:
            if previous['owner']!=user:raise PermissionError('Intent unavailable')
            if (previous['reference'],previous['preview_id'],previous['payload_hash'])!=(encode(asdict(ref)),intent.preview_id,intent.payload_hash):
                raise ValueError('Intent payload changed')
            return intent_row(previous)
        current=self._observations(db,user,ref.mode)
        required={c.id for c in self._refs(user,ref.mode)}
        if set(snapshot_ids)!=required or set(current)!=required:
            raise ValueError('Account observation changed; refresh preview')
        status=self._day(db,user,ref.mode,now)
        if not status['entry_allowed']:raise ValueError(status['blocked_reason'])
        db.execute(Intent.__table__.insert().values(id=intent.operation_id,owner=user,mode=ref.mode,day=day_at(now),
            connection_id=ref.id,reference=encode(asdict(ref)),preview_id=intent.preview_id,
            payload_hash=intent.payload_hash,state='reserved',filled=False,created=now))
        return replace(intent,state='reserved')

    def intent(self,user,operation_id):
        with self.engine.connect() as db:
            result=row(db,Intent,Intent.id==operation_id)
            if not result or result['owner']!=user:raise PermissionError('Intent unavailable')
            return intent_row(result)

    def record_result(self,operation_id,result):
        with self.write() as db:
            saved=row(db,Intent,Intent.id==operation_id)
            if not saved or operation_id!=result.operation_id or json.loads(saved['reference'])!=asdict(result.connection):
                raise ValueError('Worker result identity mismatch')
            entry=next((o for o in result.data.get('ops',[]) if o.get('role')=='entry'),{})
            values={'state':'filled' if saved['filled'] else result.state,'result':encode(result.to_dict())}
            if entry.get('orderid'):values['broker_order_id']=str(entry['orderid'])
            if result.data.get('id'):values['worker_trade_id']=str(result.data['id'])
            db.execute(update(Intent).where(Intent.id==operation_id).values(**values))
            return intent_row({**saved,**values})

    def observe(self,snapshot,now):
        from services.kotak_assistant.analysis import fill_time,number
        ref=snapshot.connection
        if self.connections.get(ref.id)!=ref:raise PermissionError('Connection unavailable')
        if snapshot.captured_at>now+1:raise ValueError('Future account snapshot')
        failure=None
        with self.write() as db:
            old=row(db,Observation,Observation.connection_id==ref.id)
            if old and old['captured_at']>snapshot.captured_at:return old['snapshot_id']
            normalized=[]
            for f in snapshot.fills:
                try:
                    if not all(isinstance(f.get(k),str) and f[k] for k in ('orderid','tradeid','symbol','exchange','product')):raise ValueError()
                    qty,price=number(f['quantity']),number(f['average_price'])
                    if qty<=0 or int(qty)!=qty or price<=0 or f['action'] not in ('BUY','SELL'):raise ValueError()
                    stamp=fill_time(f['timestamp'])
                    body={k:f[k] for k in ('orderid','tradeid','symbol','exchange','product','action')}
                    body.update(quantity=int(qty),average_price=price,timestamp=stamp)
                    key=scoped_id(ref,'fill',encode([f['exchange'],f['orderid'],f['tradeid']]))
                    existing=row(db,Fill,Fill.id==key)
                    if existing and existing['body']!=encode(body):
                        raise ValueError('Broker fill changed; reconciliation required')
                    normalized.append((key,body,existing))
                except (ValueError,KeyError,TypeError):
                    failure='Broker fill changed or incomplete; reconciliation required'
                    break
            if not failure:
                from services.kotak_assistant.discipline import order_evidence
                historical=[json.loads(r['body']) for r in db.execute(select(Fill).where(Fill.connection_id==ref.id)).mappings()]
                evidence=order_evidence(snapshot.orders,[f for _,f,_ in normalized],day_at(now),historical)
                if not evidence['complete']:
                    snapshot=replace(snapshot,books_complete=False,quotes_fresh=False,error=evidence['reason'])
            if failure:
                snapshot=replace(snapshot,books_complete=False,quotes_fresh=False,error=failure)
            else:
                for key,f,existing in normalized:
                    order_key=scoped_id(ref,'order',encode([f['exchange'],f['orderid']]))
                    if not existing:db.execute(Fill.__table__.insert().values(id=key,owner=ref.owner,mode=ref.mode,
                        day=day_at(f['timestamp']),connection_id=ref.id,order_key=order_key,body=encode(f)))
                    if f['action']=='BUY':
                        db.execute(update(Intent).where(Intent.connection_id==ref.id,Intent.broker_order_id==f['orderid']).values(filled=True,state='filled'))
                if snapshot.books_complete:
                    for order in snapshot.orders:
                        if order.get('order_status','').lower() in ('cancelled','canceled','rejected') and number(order.get('filled_quantity',0))==0:
                            # Broker zero-fill evidence may release only an intent which
                            # has never been observed filled; historical fill rows win.
                            db.execute(update(Intent).where(Intent.connection_id==ref.id,Intent.broker_order_id==str(order.get('orderid','')),Intent.filled==False).values(state='cancelled'))
            body=encode(snapshot.to_dict())
            sid=hashlib.sha256(body.encode()).hexdigest()
            values={'snapshot_id':sid,'body':body,'captured_at':snapshot.captured_at}
            if old:db.execute(update(Observation).where(Observation.connection_id==ref.id).values(**values))
            else:db.execute(Observation.__table__.insert().values(connection_id=ref.id,**values))
            self._day(db,ref.owner,ref.mode,now)
        if failure:raise ValueError(failure)
        return sid
