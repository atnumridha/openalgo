"""Flattrade-local Gateway; no global credential switching or Kotak mutations."""
import copy
import hashlib
import math
import os
import time
from datetime import datetime, timedelta

from services.kotak_assistant.broker import Gateway, unwrap
from services.kotak_assistant.analysis import IST, number


def fill_epoch(value):
    from services.kotak_assistant.analysis import fill_time
    if isinstance(value,str):
        for fmt in ('%H:%M:%S %d-%m-%Y','%d-%m-%Y %H:%M:%S','%d:%m:%Y %H:%M:%S'):
            try:return datetime.strptime(value,fmt).replace(tzinfo=IST).timestamp()
            except ValueError:pass
    return fill_time(value)


def account_key(user):
    parts = os.getenv('BROKER_API_KEY', '').split(':::')
    if len(parts) != 2 or not all(parts):
        raise ValueError('Flattrade account configuration unavailable')
    return hashlib.sha256((user+'\0'+parts[0]).encode()).hexdigest()[:24]


class FlattradeGateway(Gateway):
    def __init__(self, user, mode):
        super().__init__(user, mode)
        self.account = account_key(user)
        self.scope = f'combined:flattrade:{user}:{self.account}:{mode}'

    def credentials(self):
        from database.auth_db import get_api_key_for_tradingview, get_auth_token_broker, get_user_id
        key = get_api_key_for_tradingview(self.user)
        token, broker = get_auth_token_broker(key) if key else (None, None)
        client = os.getenv('BROKER_API_KEY', '').split(':::')[0]
        if not key or not token or broker != 'flattrade' or account_key(self.user) != self.account or get_user_id(self.user) != client:
            raise ValueError('Flattrade account session unavailable or changed')
        return key, token

    def other_controller(self, symbol, exchange, product):
        from database.scalping_db import get_active_sl_states
        if any(s.get('symbol') == symbol and s.get('exchange') == exchange and s.get('product') == product
               for s in get_active_sl_states(mode=self.mode)):
            return True
        from sqlalchemy import inspect
        from database import strategy_module_db as sm
        if not inspect(sm.engine).has_table('sm_strategy_run'):
            return False
        return sm.db_session.query(sm.SmStrategyOrder.id).join(sm.SmStrategyRun,
            sm.SmStrategyRun.id == sm.SmStrategyOrder.run_id).filter(
                sm.SmStrategyRun.stopped_at.is_(None), sm.SmStrategyRun.broker == 'flattrade',
                sm.SmStrategyRun.mode == self.mode, sm.SmStrategyOrder.symbol == symbol,
                sm.SmStrategyOrder.exchange == exchange, sm.SmStrategyOrder.product == product).first() is not None

    def quote(self, symbol, exchange):
        self.watch(symbol, exchange)
        def load():
            from broker.flattrade.api.data import BrokerData
            _, token = self.credentials()
            q = BrokerData(token).get_quotes(symbol, exchange)
            if not isinstance(q, dict) or number(q.get('ltp', 0)) <= 0:
                raise ValueError('Flattrade quote unavailable')
            return {**q, 'time': time.time(), 'source': 'Flattrade broker snapshot'}
        with self._lock:
            live = dict(self._ticks.get((symbol,exchange),{}))
        if live and 0<=time.time()-live.get('time',0)<=3 and 0<=time.time()-live.get('observed_time',live.get('time',0))<=5:
            bands=self.cached(('quote_bands',symbol,exchange),60,load)
            return {**bands,**live}
        # Preserve original capture time across fallback cache hits.
        return self.cached(('quote',symbol,exchange),4,load)

    def funds(self):
        if self.mode == 'analyze':return super().funds()
        from services.funds_service import get_funds_with_auth
        _, token = self.credentials()
        funds = self.cached('combined_funds_core', 10, lambda: unwrap(get_funds_with_auth(token, 'flattrade')))
        if not isinstance(funds, dict) or funds.get('availablecash') is None:
            raise ValueError('Flattrade funds unavailable')
        return {'cash': number(funds['availablecash'])}

    def books(self, include_cash=True):
        if self.mode == 'analyze':
            return super().books(include_cash)
        _, token = self.credentials()
        def load_core():
            from broker.flattrade.api import order_api as api
            from broker.flattrade.mapping import order_data as mapping
            def checked(raw):
                if raw == {'stat':'Not_Ok','emsg':'no data'}:
                    return []
                # Never convert a failed/malformed read to empty books.
                if not isinstance(raw, list) or any(not isinstance(r, dict) or r.get('stat') != 'Ok' for r in raw):
                    raise ValueError('Flattrade account books unavailable')
                client = os.getenv('BROKER_API_KEY', '').split(':::')[0]
                if any(r.get('actid', client) != client or r.get('uid', client) != client for r in raw):
                    raise ValueError('Flattrade account identity mismatch')
                return copy.deepcopy(raw)
            raw_orders, raw_positions, raw_fills = (checked(fn(token)) for fn in
                (api.get_order_book, api.get_positions, api.get_trade_book))
            # Normalize through the worker-local symbol database; retain stable IDs/tags.
            mapped_orders = mapping.map_order_data(raw_orders)
            orders = mapping.transform_order_data(mapped_orders)
            for order, raw in zip(orders, mapped_orders, strict=True):
                order.update(action={'B':'BUY','S':'SELL'}.get(order['action'], order['action']),
                             order_tag=raw.get('remarks',''), message=raw.get('rejreason',''))
            positions = mapping.transform_positions_data(mapping.map_position_data(raw_positions))
            mapped_fills = mapping.map_trade_data(raw_fills)
            fills = mapping.transform_tradebook_data(mapped_fills)
            for fill, raw in zip(fills, mapped_fills, strict=True):
                if not raw.get('flid'):
                    raise ValueError('Flattrade fill identity unavailable')
                fill.update(timestamp=fill_epoch(fill['timestamp']),tradeid=str(raw['flid']), action={'B':'BUY','S':'SELL'}.get(fill['action'],fill['action']))
            return {'orders':orders, 'positions':positions, 'fills':fills, 'time':time.time()}
        data = copy.deepcopy(self.cached('combined_book_core',5,load_core))
        if include_cash:
            data['cash'] = self.funds()['cash']
        return data

    def _protected_sell(self, symbol, exchange, trigger=None):
        from utils.mpp_slab import calculate_protected_price
        q, meta = self.quote(symbol, exchange), self.metadata(symbol, exchange)
        if not 0 <= time.time()-number(q.get('time',0)) <= 5:
            raise ValueError('Fresh stop/exit quote required')
        tick = number(meta['tick'])
        lower, upper, bid = (number(q.get(k,0) or 0) for k in ('lower_circuit','upper_circuit','bid'))
        if not 0 < lower <= bid <= upper or tick <= 0:
            raise ValueError('Broker price-band/tick constraints unavailable')
        base = number(trigger) if trigger is not None else bid
        if not lower <= base <= upper:
            raise ValueError('Stop outside broker price band')
        proposed = calculate_protected_price(base, 'SELL', symbol, instrument_type='CE' if symbol.endswith('CE') else 'PE', tick_size=tick)
        price = max(math.ceil(lower/tick)*tick, math.floor(proposed/tick)*tick)
        if not lower <= price <= upper or (trigger is not None and price > trigger):
            raise ValueError('No valid protected limit price')
        return round(price,8)

    def stop_limit(self, symbol, exchange, trigger):
        return self._protected_sell(symbol,exchange,trigger)

    def submit(self, data):
        data = dict(data)
        original = data.get('pricetype')
        if original not in ('LIMIT','SL','MARKET') or (original=='MARKET' and data.get('action')!='SELL'):
            return {'state':'rejected','message':'Flattrade V2 requires explicit LIMIT or SL-LIMIT orders'}
        _, token = self.credentials()
        if self.mode == 'analyze':
            return super().submit(data)
        if data.get('action')=='BUY':
            from database.settings_db import get_analyze_mode
            if get_analyze_mode():
                return {'state':'rejected','message':'Execution mode changed'}
        try:
            meta = self.metadata(data['symbol'],data['exchange'])
            qty = data.get('quantity')
            if isinstance(qty,bool) or not isinstance(qty,int) or qty<=0 or qty%meta['lot'] or qty>meta['freeze']:
                raise ValueError('Invalid contract quantity')
            if original=='MARKET':
                data.update(pricetype='LIMIT',price=self._protected_sell(data['symbol'],data['exchange']))
            price = number(data.get('price',0))
            if price <= 0 or not math.isclose(price/meta['tick'],round(price/meta['tick']),abs_tol=1e-6):
                raise ValueError('Invalid limit price')
            if data['pricetype']=='SL' and price>number(data.get('trigger_price',0)):
                raise ValueError('Invalid sell-stop limit')
        except (ValueError,KeyError,TypeError):
            return {'state':'rejected','message':'Invalid or unavailable Flattrade execution constraints'}
        from broker.flattrade.api.order_api import place_order_api
        try:
            response, raw, oid = place_order_api({**data,'_combined_terminal_tag':data.get('tag')}, token)
        except Exception:
            return {'state':'unknown','message':'Broker submission outcome unknown; reconcile before retrying'}
        self._cache.pop('combined_book_core',None)
        status = getattr(response,'status_code',None)
        state = 'accepted' if oid else 'rejected' if isinstance(raw,dict) and raw.get('stat')=='Not_Ok' and status is not None and status<500 else 'unknown'
        return {'state':state,'orderid':str(oid) if oid else None,'effective_pricetype':data['pricetype'],
                'message':'Protected LIMIT exit may remain unfilled' if original=='MARKET' else 'Flattrade '+state}

    def cancel(self, oid):
        if self.mode=='analyze':return super().cancel(oid)
        _,token=self.credentials()
        from broker.flattrade.api.order_api import cancel_order
        try:
            result, code=cancel_order(oid,token)
        except Exception:
            return {'state':'unknown','message':'Cancellation outcome unknown'}
        return {'state':'accepted' if result.get('status')=='success' else 'rejected' if code<500 else 'unknown',
                'message':'Cancellation requested; reconcile broker order state'}

    def history_range(self, symbol, exchange, interval, start, end):
        from services.history_service import get_history
        first,last=datetime.fromisoformat(start),datetime.fromisoformat(end)
        if first>last or (last-first).days>40:raise ValueError('Choose at most 40 history days')
        _,token=self.credentials()
        return self.cached(('history',symbol,exchange,interval,start,end),60,lambda:unwrap(
            get_history(symbol,exchange,interval,start,end,auth_token=token,broker='flattrade',background=True)))

    def history(self,symbol,exchange,interval):
        now=datetime.now(IST)
        return self.history_range(symbol,exchange,interval,(now-timedelta(days=10)).date().isoformat(),now.date().isoformat())

    def ladder(self,underlying,expiry,count):
        from services.option_chain_service import get_option_chain
        key,_=self.credentials()
        exchange='BSE_INDEX' if underlying=='SENSEX' else 'NSE_INDEX'
        # Quote only selected legs through the stream; do not poll every strike.
        return self.cached(('chain',underlying,expiry,count),10,lambda:unwrap(
            get_option_chain(underlying,exchange,expiry,count,key,with_quotes=False)))


def callback_client(client):
    parts=os.getenv('BROKER_API_KEY','').split(':::')
    if len(parts)!=2 or not all(parts) or not client or client!=parts[0]:
        raise ValueError('Flattrade callback account does not match configured client')
    return client
