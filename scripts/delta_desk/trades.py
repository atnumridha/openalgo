"""Read-only round trips reconstructed from Delta's actual fills and wallet costs.

A trade runs from flat to flat for one product. Reversals split quantity and fees
pro rata. Missing opening history, unsupported contracts or unreconciled costs
leave net unavailable. Decimal amounts include reported GST exactly once.
"""
from datetime import datetime
from decimal import Decimal, InvalidOperation
from itertools import groupby
from zoneinfo import ZoneInfo

D=Decimal
ZERO=D(0)
EPS=D('0.00000005')
IST=ZoneInfo('Asia/Kolkata')
MONEY=('gross','entry_fees','exit_fees','fees','cash_fees','credits_used','funding','rebates','promo_credits','net','cash_net')
PROMO_TYPES=('promo_credit','trading_credits','trading_fee_credits','trading_fee_credit','trading_fee_credit_awarded')


def dec(value):
    result=D(str(value))
    if not result.is_finite():raise ValueError('Non-finite amount')
    return result


def stamp(value):
    try:
        number=float(dec(value))
        return number/1e6 if number>1e12 else number
    except (ValueError,InvalidOperation):
        return datetime.fromisoformat(value.replace('Z','+00:00')).timestamp()


def sequence_fills(fills):
    """Use position continuity for timestamp ties, never API newest-first order."""
    inventory={}
    for _,group in groupby(fills,key=lambda f:f['at']):
        products={}
        for f in group:products.setdefault(f['product'],[]).append(f)
        for key,pending in products.items():
            while pending:
                def before(f):
                    return f['post']-f['qty']*(1 if f['side']=='buy' else -1) if f['post'] is not None else None
                expected=inventory.get(key,ZERO)
                choices=[f for f in pending if before(f)==expected]
                if key not in inventory and not choices:
                    # A carried position may start away from zero. Only infer
                    # its first observed fill when the chain has a unique head.
                    posts={f['post'] for f in pending}
                    choices=[f for f in pending if before(f) not in posts]
                if len(pending)>1 and len(choices)!=1:
                    for f in pending:f['issues'].append('Fill sequence is ambiguous at an identical timestamp.')
                f=choices[0] if len(choices)==1 else pending[0]
                pending.remove(f)
                if f['post'] is not None:inventory[key]=f['post']
                yield f


def reconcile_fees(fills,tx):
    debits={};reimbursements={};unlinked_credit=ZERO;unlinked_debit=False
    for t in tx:
        if t.get('asset_symbol')!='USD':continue
        ident=str((t.get('meta_data') or {}).get('fill_uuid') or '')
        amount=dec(t['amount']);kind=t['transaction_type']
        if kind in ('commission','liquidation_fee'):
            if ident:debits[ident]=debits.get(ident,ZERO)-amount
            elif amount:unlinked_debit=True
        elif kind in ('trading_fee_credits_paid','trading_fee_credits_paid_liquidation_fee'):
            if ident:reimbursements[ident]=reimbursements.get(ident,ZERO)+amount
            else:unlinked_credit+=amount
    pending=[]
    for f in fills:
        debit=debits.get(f['id'],ZERO);refund=reimbursements.get(f['id'],ZERO)
        cash_only=abs(debit-f['cash'])<=EPS and abs(refund)<=EPS
        full_fee=abs(debit-f['fee'])<=EPS and abs(refund-f['credits'])<=EPS
        if cash_only or full_fee:continue
        if abs(debit-f['fee'])<=EPS and f['credits']>0 and not refund:
            pending.append(f)
        else:f['issues'].append('Cash fees are awaiting wallet reconciliation.')
    # Older ledgers reimburse credits without fill IDs. Accept only an exact
    # aggregate match over the remaining full-fee debits, with complete linkage.
    linked_ids={f['id'] for f in fills}
    aggregate_ok=(not unlinked_debit and set(debits)<=linked_ids and
                  abs(unlinked_credit-sum((f['credits'] for f in pending),ZERO))<=EPS)
    if not aggregate_ok:
        for f in pending:f['issues'].append('Cash fees are awaiting wallet reconciliation.')


def new_trade(product,symbol,at,side,known):
    return {'product_id':product,'symbol':symbol,'direction':'Long' if side>0 else 'Short',
            'opened_at':at if known else None,'first_observed_at':at,'closed_at':None,
            'known':known,'entry_qty':ZERO,'exit_qty':ZERO,'entry_value':ZERO,'exit_value':ZERO,
            'gross':ZERO,'entry_fees':ZERO,'exit_fees':ZERO,'cash_fees':ZERO,'credits_used':ZERO,
            'funding':ZERO,'rebates':ZERO,'promo_credits':ZERO,'fills':[],
            'issues':[] if known else ['Entry history begins before the loaded day or is missing. Full-trade P&L is unavailable.']}


def add_fill(row,f,qty,role):
    fraction=qty/f['qty']
    row[role+'_qty']+=qty
    row[role+'_value']+=qty*f['price']
    row[role+'_fees']+=f['fee']*fraction
    row['cash_fees']+=f['cash']*fraction
    row['credits_used']+=f['credits']*fraction
    row['gross']+=qty*f['price']*f['contract']*(1 if f['side']=='sell' else -1)
    row['issues'].extend(f['issues'])
    row['fills'].append({'fill_id':f['id'],'order_id':f['order'],'at':f['at'],'side':f['side'],'role':role,
                         'liquidity':f['liquidity'],'contracts':str(qty),'price':str(f['price']),
                         'fee_usd':str(f['fee']*fraction),'cash_fee_usd':str(f['cash']*fraction),
                         'credits_used_usd':str(f['credits']*fraction),'allocation':str(fraction)})


def trade_report(fills,transactions,now):
    start=datetime.fromtimestamp(now,IST).replace(hour=0,minute=0,second=0,microsecond=0).timestamp()
    tx={str(t['uuid']):t for t in transactions if start<=stamp(t['created_at'])<=now}
    clean=[];issues=[];seen=set()
    for raw in sorted(fills,key=lambda f:stamp(f['created_at'])):
        ident=str(raw['id']);at=stamp(raw['created_at'])
        if ident in seen or not start<=at<=now or raw.get('settling_asset_symbol')!='USD':continue
        seen.add(ident)
        try:
            m=raw.get('meta_data') or {};p=raw.get('product') or {};notes=[]
            commission=dec(raw.get('commission',0));credits=dec(m.get('tfc_used_for_commission',m.get('trading_fee_credits_used',0)) or 0)
            total=dec(m.get('total_commission_in_settling_asset',commission+credits))
            liquidation=dec(m.get('total_liquidation_fee_in_settling_asset',m.get('liquidation_fee_in_settling_asset',0)) or 0)
            liq_credit=dec(m.get('tfc_used_for_liquidation_fee',0) or 0)
            credit=credits+liq_credit;fee=total+liquidation;cash=fee-credit
            if min(cash,credit,fee)<0 or abs(fee-cash-credit)>EPS:notes.append('Fill fee components do not reconcile.')
            if p.get('notional_type')!='vanilla':notes.append('This contract needs a separate P&L calculation.')
            qty=dec(raw['size']);price=dec(raw['price']);contract=dec(p['contract_value'])
            if min(qty,price,contract)<=0 or raw['side'] not in ('buy','sell'):raise ValueError('Invalid fill')
            post=(m.get('new_position') or {}).get('size')
            clean.append({'id':ident,'order':str(raw['order_id']),'at':at,'product':raw['product_id'],
                          'symbol':raw['product_symbol'],'side':raw['side'],'qty':qty,'price':price,
                          'contract':contract,'post':dec(post) if post is not None else None,
                          'fee':fee,'cash':cash,'credits':credit,'liquidity':raw.get('role','unknown'),'issues':notes})
        except (ValueError,InvalidOperation,KeyError,TypeError):issues.append('A fill could not be valued; the report is incomplete.')
    reconcile_fees(clean,tx.values())
    active={};inventory={};rows=[]
    for f in sequence_fills(clean):
        key=f['product'];signed=f['qty']*(1 if f['side']=='buy' else -1)
        before=f['post']-signed if f['post'] is not None else inventory.get(key,ZERO)
        if key in inventory and inventory[key]!=before:
            if key in active:active[key]['issues'].append('Position continuity is incomplete.')
            f['issues'].append('Position continuity is incomplete.')
        if f['post'] is None:f['issues'].append('Exchange position snapshot is missing.')
        if key not in active:
            active[key]=new_trade(key,f['symbol'],f['at'],before or signed,before==0 and f['post'] is not None)
            rows.append(active[key])
        row=active[key]
        if before==0 or (before>0)==(signed>0):
            add_fill(row,f,f['qty'],'entry')
        else:
            closing=min(abs(before),f['qty']);add_fill(row,f,closing,'exit')
            if closing==abs(before):
                row['closed_at']=f['at'];active.pop(key)
            if f['qty']>closing:
                row=new_trade(key,f['symbol'],f['at'],signed,True)
                active[key]=row;rows.append(row);add_fill(row,f,f['qty']-closing,'entry')
        inventory[key]=before+signed
    # Link ledger items to exact fills when possible, otherwise uniquely to a
    # product's holding interval. Unattributed adjustments stay visible outside totals.
    unmatched=[]
    for t in tx.values():
        kind=t['transaction_type'];asset=t.get('asset_symbol');field=None
        if asset=='USD' and kind=='funding':field='funding'
        elif asset=='USD' and kind=='commission_rebate':field='rebates'
        elif asset in ('USD','TFC_USD') and kind in PROMO_TYPES:field='promo_credits'
        if field is None:continue
        meta=t.get('meta_data') or {};fill_id=meta.get('fill_uuid');at=stamp(t['created_at'])
        if fill_id:
            matches=[(row,dec(f['allocation'])) for row in rows for f in row['fills'] if f['fill_id']==str(fill_id)]
        else:
            matches=[(row,D(1)) for row in rows if (row['product_id']==t.get('product_id') or row['symbol']==meta.get('product_symbol')) and (row['opened_at'] or start)<=at<(row['closed_at'] or now+1)]
        if (fill_id and matches) or len(matches)==1:
            for row,part in matches:row[field]+=dec(t['amount'])*part
        else:unmatched.append({'kind':kind,'amount_usd':str(dec(t['amount'])),'at':at})
    output=[]
    for row in reversed(rows):
        notes=sorted(set(row['issues']));closed=row['closed_at'] is not None
        known=row['known'] and not notes
        gross=row['gross'] if closed and known else None
        fees=row['entry_fees']+row['exit_fees']
        net=gross-fees+row['funding']+row['rebates'] if gross is not None else None
        result={k:row[k] for k in ('symbol','direction','opened_at','closed_at','first_observed_at','fills')}
        result.update(id=row['fills'][0]['fill_id']+':'+row['direction'],status='incomplete' if not known else 'closed' if closed else 'open',issues=notes,
                      contracts=str(row['entry_qty']) if row['known'] else None,
                      entry_price=str(row['entry_value']/row['entry_qty']) if row['known'] and row['entry_qty'] else None,
                      exit_price=str(row['exit_value']/row['exit_qty']) if row['exit_qty'] else None,
                      holding_seconds=row['closed_at']-row['opened_at'] if closed and row['opened_at'] else None,
                      entry_order_ids=list(dict.fromkeys(f['order_id'] for f in row['fills'] if f['role']=='entry')),
                      exit_order_ids=list(dict.fromkeys(f['order_id'] for f in row['fills'] if f['role']=='exit')))
        values={k:row.get(k,ZERO) for k in MONEY}
        values.update(gross=gross,fees=fees,net=net,cash_net=gross-row['cash_fees']+row['funding']+row['rebates'] if gross is not None else None)
        for name,value in values.items():
            result[name+'_usd']=str(value) if value is not None else None
            result[name+'_inr']=str(value*85) if value is not None else None
        output.append(result)
    complete=[r for r in output if r['status']=='closed']
    totals={k+'_usd':str(sum((dec(r[k+'_usd']) for r in complete),ZERO)) for k in MONEY}
    return {'day':datetime.fromtimestamp(now,IST).date().isoformat(),'asof':now,'rows':output[:200],'total_rows':len(output),
            'closed_count':len(complete),'totals':totals,'issues':issues,'unattributed':unmatched,
            'scope':'Today, India time. Flat-to-flat trades; partial fills grouped. Prior-day entries are incomplete. Totals include fully reconstructed closed trades only.'}


def with_trade_details(original):
    if getattr(original,'_delta_trade_details',False):return original
    def report(wallet,positions,fills,transactions,orders,now):
        result=original(wallet,positions,fills,transactions,orders,now)
        try:
            result['trade_report']=trade_report(fills,transactions,now)
            start=datetime.fromtimestamp(now,IST).replace(hour=0,minute=0,second=0,microsecond=0).timestamp()
            awards={str(t['uuid']):t for t in transactions if start<=stamp(t['created_at'])<=now and t.get('asset_symbol') in ('USD','TFC_USD') and t['transaction_type'] in PROMO_TYPES}
            result['promo_credits_usd']=str(sum((dec(t['amount']) for t in awards.values()),ZERO))
        except Exception:
            result['trade_report']={'day':datetime.fromtimestamp(now,IST).date().isoformat(),'asof':now,'rows':[], 'closed_count':0,'totals':{},'unattributed':[], 'issues':['Trade reconstruction is unavailable; account totals remain separate.']}
        return result
    report._delta_trade_details=True
    return report
