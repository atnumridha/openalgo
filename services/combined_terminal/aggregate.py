"""Read-only combined view. Unknown/stale account values are never zero-filled."""
from dataclasses import asdict
import json
import math
from datetime import datetime
from services.kotak_assistant.analysis import IST,fill_time
from .contracts import scoped_id


def aggregate(snapshots,day,now):
    if len({s.connection.mode for s in snapshots})>1:
        raise ValueError('Live and paper ledgers cannot be combined')
    identities=[s.connection.id for s in snapshots]
    if len(set(identities))!=len(identities):raise ValueError('Duplicate account snapshot')
    connections,positions,history,fills,orders=[],[],[],[],[]
    realized,opened=[],[]
    all_realized=bool(snapshots);all_open=bool(snapshots)
    for s in snapshots:
        c=s.connection
        age=now-s.captured_at
        book_ok=not s.error and s.books_complete and 0<=age<=10
        quote_ok=book_ok and s.quotes_fresh and 0<=age<=5
        balance=s.funds.get('availablecash') if isinstance(s.funds,dict) else None
        funds_ok=isinstance(balance,(int,float)) and not isinstance(balance,bool) and math.isfinite(balance) and balance>=0
        ready=quote_ok and funds_ok
        error=s.error or ('Account books unavailable or stale' if not book_ok else
                         'Quote data unavailable or stale' if not quote_ok else
                         'Available funds unavailable' if not funds_ok else None)
        connections.append({'connection':asdict(c),'entry_ready':ready,'books_complete':book_ok,
                            'quotes_fresh':quote_ok,'captured_at':s.captured_at,'age_seconds':max(0,age),
                            'funds':{'availablecash':balance} if funds_ok else None,'error':error,
                            'realized_net':s.realized_net if book_ok else None,
                            'charges':s.charges if book_ok else None,
                            'estimated_exit_charges':s.estimated_exit_charges if quote_ok else None,
                            'estimated_open_net':s.estimated_open_net if quote_ok else None})
        if book_ok and s.realized_net is not None:realized.append(s.realized_net)
        else:all_realized=False
        if quote_ok and s.estimated_open_net is not None:opened.append(s.estimated_open_net)
        else:all_open=False
        represented=set()
        for t in s.managed_trades:
            if not isinstance(t,dict) or not isinstance(t.get('id'),str):continue
            record={**t,'trade_id':scoped_id(c,'trade',t['id']),'broker':c.broker,
                    'connection_id':c.id,'account':c.account,'mode':c.mode,'captured_at':s.captured_at,
                    'data_fresh':quote_ok,'managed':True}
            history.append(record)
            if t.get('status') in ('closed','rejected'):continue
            represented.add((t.get('symbol'),t.get('exchange'),t.get('product')))
            record['quantity']=t.get('remaining',0)
            broker_position=next((p for p in s.positions if all(p.get(k)==t.get(k) for k in ('symbol','exchange','product'))),None)
            observed_quote=(broker_position or {}).get('quote') or t.get('quote',{})
            price=observed_quote.get('ltp')
            stamp=observed_quote.get('time',0)
            if broker_position and broker_position.get('quantity')==t.get('remaining'):
                record.update(gross_open=broker_position.get('gross_open'),net_open=broker_position.get('net_open'))
            record['ltp']=price if quote_ok and 0<=now-stamp<=5 else None
            if not quote_ok:record.update(gross_open=None,net_open=None)
            positions.append(record)
        for p in s.positions:
            if (p.get('symbol'),p.get('exchange'),p.get('product')) in represented or not p.get('quantity'):continue
            positions.append({**p,'broker':c.broker,'connection_id':c.id,'account':c.account,'mode':c.mode,
                              'captured_at':s.captured_at,'data_fresh':quote_ok,'managed':False,
                              'ltp':p.get('ltp') if quote_ok else None})
        account_positions=[p for p in positions if p['connection_id']==c.id and p.get('quantity',0)]
        entry_ids=set()
        count_known=book_ok
        for fill in s.fills:
            try:
                if datetime.fromtimestamp(fill_time(fill['timestamp']),IST).date()!=datetime.fromtimestamp(now,IST).date():continue
                if fill.get('action')=='BUY' and float(fill.get('quantity',0))>0:
                    entry_ids.add((fill['exchange'],fill['orderid']))
            except (KeyError,ValueError,TypeError):count_known=False
        for order in s.orders:
            if not order.get('orderid'):continue
            orders.append({**order,'order_key':scoped_id(c,'order',json.dumps([order.get('exchange'),order['orderid']])),
                           'broker':c.broker,'connection_id':c.id,'mode':c.mode,'captured_at':s.captured_at,'data_fresh':book_ok})
        pending={(o.get('exchange'),o.get('orderid')) for o in s.orders if str(o.get('order_status','')).strip().lower() not in ('complete','completed','cancelled','canceled','rejected')}
        connections[-1].update(
            estimated_total_net=round(s.realized_net+s.estimated_open_net,2) if book_ok and quote_ok and s.realized_net is not None and s.estimated_open_net is not None else None,
            open_positions=len(account_positions) if book_ok else None,
            pending_orders=len(pending) if book_ok else None,
            filled_entries=len(entry_ids) if count_known else None)
        seen=set()
        for f in s.fills:
            if not f.get('orderid') or not f.get('tradeid'):continue
            key=scoped_id(c,'fill',json.dumps([f.get('exchange'),f['orderid'],f['tradeid']]))
            if key in seen:continue
            seen.add(key)
            try:stamp=fill_time(f['timestamp'])
            except (KeyError,ValueError,TypeError):stamp=None
            fills.append({**f,'timestamp':stamp,'fill_id':key,'broker':c.broker,'connection_id':c.id,'mode':c.mode})
    complete=all_realized and all_open
    real=round(sum(realized),2) if all_realized else None
    op=round(sum(opened),2) if all_open else None
    return {'connections':connections,'positions':positions,'history':history,'fills':fills,'orders':orders,'day':day,
            'summary':{'complete':complete,'realized_net':real,'estimated_open_net':op,
                       'estimated_total_net':round(real+op,2) if complete else None,
                       'partial_realized_net':round(sum(realized),2),
                       'partial_estimated_open_net':round(sum(opened),2),
                       'reason':None if complete else 'Combined P&L incomplete; unavailable accounts are not counted as zero'},
            'updated_at':now}
