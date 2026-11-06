"""Shared chart/setup presentation fed exclusively by the selected broker worker."""
from datetime import datetime,timedelta
import math
from services.kotak_assistant.analysis import IST,DEFAULTS,completed,number


class MarketData:
    def __init__(self,controller,expiry_loader=None,setup_evaluator=None):
        self.c=controller
        self.expiry_loader=expiry_loader or self._expiries
        self.setup_evaluator=setup_evaluator

    def _expiries(self,underlying,exchange):
        from services.expiry_service import get_expiry_dates
        from services.kotak_assistant.broker import unwrap
        key,_=self.c.g.credentials()
        return unwrap(get_expiry_dates(underlying,exchange,'options',key))

    def snapshot(self,payload):
        c,g=self.c,self.c.g
        underlying=payload.get('underlying','NIFTY')
        if underlying not in ('NIFTY','BANKNIFTY','SENSEX'):raise ValueError('Unsupported index')
        exchange='BFO' if underlying=='SENSEX' else 'NFO'
        ix='BSE_INDEX' if underlying=='SENSEX' else 'NSE_INDEX'
        strategy,mode=payload.get('strategy','trend'),payload.get('signal_mode','confirmed')
        if strategy not in ('trend','opening_reversal') or mode not in ('confirmed','early'):
            raise ValueError('Unsupported strategy')
        lots,ratio=int(payload.get('lots',1)),float(payload.get('ratio',2))
        if not 1<=lots<=100 or ratio not in (1.5,2,3,4,5,6):raise ValueError('Invalid lots/reward multiple')
        now=c.clock();today=datetime.fromtimestamp(now,IST).date()
        expiries=[]
        for raw in self.expiry_loader(underlying,exchange):
            try:
                normal=raw.replace('-','').replace(' ','').upper()
                date=datetime.strptime(normal,'%d%b%y').date()
                if date>=today:expiries.append((date,normal))
            except (ValueError,TypeError,AttributeError):continue
        ordered=[e for _,e in sorted(set(expiries))]
        expiry=payload.get('expiry') or (ordered[0] if ordered else '')
        if expiry and expiry not in ordered:raise ValueError('Selected expiry is unavailable')
        index_quote=g.quote(underlying,ix)
        result={'underlying':underlying,'exchange':exchange,'index_quote':index_quote,'expiries':ordered,
                'expiry':expiry,'chain':None,'symbol':'','quote':None,'quotes':{},'metadata':None,
                'template':None,'setup':{'stage':'waiting_history','reason':'Waiting for selected broker data','eligible':False},
                'captured_at':now,'strategy':strategy,'signal_mode':mode}
        if not expiry:return result
        chain=g.ladder(underlying,expiry,8)
        rows=chain.get('chain',[])
        legs={v['symbol']:(r,v) for r in rows for side in ('ce','pe')
              if isinstance((v:=r.get(side)),dict) and isinstance(v.get('symbol'),str)}
        symbol=payload.get('symbol')
        if not symbol and rows:
            ranked=sorted(rows,key=lambda r:abs(number(r['strike'])-number(chain.get('atm_strike',index_quote['ltp']))))
            symbol=next((r.get('ce',{}).get('symbol') for r in ranked if r.get('ce')),None)
        if not symbol or symbol not in legs:raise ValueError('Selected contract is unavailable in this expiry')
        row,_=legs[symbol]
        quotes={}
        for side in ('ce','pe'):
            leg=row.get(side)
            if leg:
                try:quotes[leg['symbol']]=g.quote(leg['symbol'],exchange)
                except Exception:quotes[leg['symbol']]={'source':'Unavailable','time':0}
        q=quotes[symbol]
        meta=g.metadata(symbol,exchange)
        option_bars=g.history(symbol,exchange,'1m')
        one,five=g.history(underlying,ix,'1m'),g.history(underlying,ix,'5m')
        if self.setup_evaluator:
            setup=self.setup_evaluator(c,underlying,one,five,index_quote,strategy,mode)
        else:
            from services.kotak_assistant.setup_live import refresh
            setup=refresh(c,underlying,one,five,index_quote,strategy,mode,keep_alive=False)
            setup.pop('current_quote',None)
        template=None
        if number(q.get('ask',0) or 0)>0 and 0<=now-number(q.get('time',0))<=5:
            from services.kotak_assistant.ticket_plans import trend_plan
            settings={**DEFAULTS,**c.state().get('settings',{})}
            template=trend_plan(number(q['ask']),completed(option_bars,now,60),lots*meta['lot'],meta['tick'],meta['lot'],
                                exchange,settings,ratio,today.isoformat())
        result.update(chain=chain,symbol=symbol,quote=q,quotes=quotes,metadata=meta,template=template,setup=setup,
                      strike=row['strike'],ce=row.get('ce'),pe=row.get('pe'))
        return result

    def chart(self,payload):
        c,g=self.c,self.c.g
        symbol,exchange,interval=payload['symbol'],payload['exchange'],payload.get('interval','5m')
        if interval not in ('1m','5m','15m'):raise ValueError('Unsupported chart interval')
        index=symbol in ('NIFTY','BANKNIFTY','SENSEX')
        if index:
            if exchange!=('BSE_INDEX' if symbol=='SENSEX' else 'NSE_INDEX'):raise ValueError('Index exchange mismatch')
        else:g.metadata(symbol,exchange)
        now=c.clock();today=datetime.fromtimestamp(now,IST).date()
        day=payload.get('date')
        end=datetime.strptime(day,'%Y-%m-%d').date() if day else today
        if end>today:raise ValueError('Future history is unavailable')
        start=end-timedelta(days=4 if interval=='1m' else 14)
        rows=g.history_range(symbol,exchange,interval,start.isoformat(),end.isoformat())
        candles={}
        for r in rows:
            try:
                stamp=number(r.get('time',r.get('timestamp')))
                if stamp>1e12:stamp/=1000
                values={k:number(r[k]) for k in ('open','high','low','close')}
                volume=number(r.get('volume',0) or 0)
                if stamp>now or min(values.values())<=0 or values['low']>min(values['open'],values['close']) or values['high']<max(values['open'],values['close']) or volume<0:continue
                time=int((stamp+19800)//60)*60
                candles[time]={'time':time,**values,'volume':volume}
            except (ValueError,KeyError,TypeError):continue
        return {'status':'success','symbol':symbol,'exchange':exchange,'interval':interval,'date':end.isoformat(),
                'candles':[candles[k] for k in sorted(candles)]}
