"""Delta-only adapter for explicitly adopted reduce-only protection."""
import hashlib
import json
import math
import time
from datetime import datetime

from services.delta_profit_guard import ProtectionError, NotSubmitted, ProtectionChanged, UnsentProtectionChanged


def number(value):
    if isinstance(value, bool) or not math.isfinite(float(value)):
        raise ProtectionError('Broker returned an invalid price or quantity')
    return float(value)


def timestamp(value):
    if isinstance(value, str) and ('T' in value or '-' in value):
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            raise ProtectionError('Entry time has no verified timezone')
        return parsed.timestamp()
    value = number(value)
    return value / 1_000_000 if value > 1e14 else value / 1000 if value > 1e11 else value


class Gateway:
    def auth(self, user):
        from database.auth_db import get_api_key_for_tradingview, get_auth_token_broker
        auth, broker = get_auth_token_broker(get_api_key_for_tradingview(user))
        if not auth or broker != 'deltaexchange':
            raise ProtectionError('Reconnect the same Delta account before using profit protection')
        return auth

    def call(self, auth, path, *, method='GET', body=None, params=None):
        from broker.deltaexchange.api.order_api import get_api_response
        response = get_api_response(path, auth, method=method,
                                    payload=json.dumps(body) if body is not None else '', params=params)
        if not isinstance(response, dict) or not response.get('success'):
            raise ProtectionError('Delta did not confirm the request; check broker orders before retrying')
        return response

    def conflict(self, symbol):
        from database.scalping_db import get_active_sl_states
        from database import strategy_module_db as sm
        from blueprints.leverage import _read_risk_states
        if any(r.get('symbol') == symbol and r.get('exchange') == 'CRYPTO'
               for r in get_active_sl_states(mode='live')):
            raise ProtectionChanged('The scalping monitor already manages this contract; use its existing controls')
        if any(s.get('running') and s.get('mode') == 'live' and s.get('symbol') == symbol
               for s in _read_risk_states()):
            raise ProtectionChanged('A Python strategy already manages this contract')
        # The single-user instance must not give a manual guard a contract
        # that a live strategy module run owns, including during recovery.
        for run in sm.list_open_runs():
            if run.mode == 'live' and run.broker == 'deltaexchange':
                cp = sm.latest_checkpoint(run.id)
                legs = (cp or {}).get('leg_state', {})
                if not legs or any(leg.get('symbol') == symbol for leg in legs.values()):
                    raise ProtectionChanged('A live strategy owns this contract or its ownership is still recovering')

    def info(self, symbol):
        from database.token_db_enhanced import get_symbol_info
        row = get_symbol_info(symbol, 'CRYPTO')
        if not row or str(row.instrumenttype).upper() not in ('PERPFUT', 'FUT'):
            raise ProtectionError('Profit protection supports Delta perpetual/futures contracts only')
        product_id, tick, cv = int(row.token), number(row.tick_size), number(row.contract_value)
        if min(product_id, tick, cv) <= 0:
            raise ProtectionError('Contract tick size and multiplier must be available')
        return product_id, tick, cv, row.brsymbol

    def position(self, auth, product_id):
        realtime = self.call(auth, '/v2/positions', params={'product_id': product_id})['result']
        quantity = number(realtime['size'])
        if quantity != int(quantity):
            raise ProtectionError('A whole-contract Delta position is required')
        if not quantity:
            return {**realtime, 'size': 0}
        rows = self.call(auth, '/v2/positions/margined')['result']
        if not isinstance(rows, list):
            raise ProtectionError('Position details are unavailable')
        row = next((r for r in rows if int(r['product_id']) == product_id), None)
        if not row or number(row['size']) != quantity or number(row['entry_price']) != number(realtime['entry_price']):
            raise ProtectionError('Position updates have not reconciled yet; waiting for matching broker evidence')
        return row

    def order(self, auth, product_id, stop_id, side, quantity):
        row = self.call(auth, f'/v2/orders/{stop_id}')['result']
        if (int(row['product_id']) != product_id or row.get('side') != ('sell' if side > 0 else 'buy')
                or row.get('reduce_only') is not True or row.get('stop_order_type') != 'stop_loss_order'
                or row.get('order_type') != 'market_order' or number(row.get('trail_amount') or 0) != 0
                or number(row.get('size')) < abs(quantity) or number(row.get('size'))-number(row.get('unfilled_size', row.get('size'))) != 0):
            raise ProtectionChanged('An unchanged, full-size reduce-only stop-market order is required')
        return row

    def snapshot(self, user, symbol, stop_id=None, enabled_at=None):
        started = time.time()
        auth = self.auth(user)
        self.conflict(symbol)
        pid, tick, cv, brsymbol = self.info(symbol)
        pos = self.position(auth, pid)
        qty = number(pos['size'])
        account = hashlib.sha256(auth.encode()).hexdigest()
        if not qty:
            return dict(quantity=0, account=account, asof=time.time())
        side = 1 if qty > 0 else -1
        if stop_id is None:
            response = self.call(auth, '/v2/orders', params={'page_size': 50, 'product_ids':str(pid), 'states':'open,pending'})
            if (response.get('meta') or {}).get('after'):
                raise ProtectionError('Complete open-order coverage is required before adoption')
            orders = [o for o in response['result'] if int(o['product_id']) == pid and o['state'] in ('open', 'pending')]
            stops = [o for o in orders if o.get('stop_order_type') == 'stop_loss_order']
            extras = [o for o in orders if o.get('stop_order_type') != 'stop_loss_order']
            if len(stops) != 1 or any(o.get('stop_order_type') != 'take_profit_order'
                    or o.get('reduce_only') is not True or o.get('side') != ('sell' if side > 0 else 'buy')
                    for o in extras):
                raise ProtectionError('Keep one broker stop and only reduce-only profit targets before adopting this position')
            stop_id = str(stops[0]['id'])
        stop = self.order(auth, pid, stop_id, side, qty)
        ticker = self.call(auth, f'/v2/tickers/{brsymbol}')['result']
        quotes = ticker.get('quotes') or {}
        bid, ask = number(quotes.get('best_bid')), number(quotes.get('best_ask'))
        if not 0 < bid <= ask:
            raise ProtectionError('A current two-sided quote is required')
        method = stop.get('stop_trigger_method')
        if method not in ('mark_price', 'last_traded_price'):
            raise ProtectionError('Only mark-price or last-traded-price stops can be adopted')
        trigger = number(ticker['mark_price'] if method == 'mark_price' else ticker['close'])
        # Conservatively stay clear of both executable and trigger prices.
        price = min(bid, trigger) if side > 0 else max(ask, trigger)
        from services.crypto_fee_service import contract_fees, fee_profile
        from services.crypto_fees import scalper_window_minutes
        contract, _ = contract_fees(symbol)
        profile = fee_profile()
        rate = contract.rate('taker') * (1+profile.gst_pct/100)
        opened = timestamp(pos.get('created_at'))
        if not 0 < opened <= time.time():
            raise ProtectionError('A verified entry time is required')
        window = scalper_window_minutes(contract, profile)
        eligible = window is not None and window > 1
        end = opened+window*60 if eligible else 0
        units = abs(qty)*cv
        entry = number(pos['entry_price'])
        cost = max(abs(number(pos.get('commission') or 0)), entry*units*rate)
        added = False
        if enabled_at:
            params = {'start_time':int(enabled_at*1e6), 'page_size':50, 'product_ids':str(pid)}
            seen = set()
            for _ in range(20):
                fills = self.call(auth, '/v2/fills', params=params)
                added = added or any(int(f['product_id']) == pid and f.get('side') == ('buy' if side > 0 else 'sell')
                                    and timestamp(f['created_at']) >= enabled_at for f in fills['result'])
                cursor = (fills.get('meta') or {}).get('after')
                if not cursor or added:
                    break
                if cursor in seen:
                    raise ProtectionError('Fill history could not be reconciled; verify broker protection')
                seen.add(cursor)
                params = {**params, 'after':cursor}
            else:
                raise ProtectionError('Fill history exceeds monitoring coverage; verify broker protection')
        now = time.time()
        if now-started > 5:
            raise ProtectionError('Broker reads were too slow; waiting for a fresh snapshot')
        return dict(symbol=symbol, account=account, side=side, quantity=qty, units=units,
                    entry=entry, opened_at=pos['created_at'], stop_id=str(stop_id),
                    stop=number(stop['stop_price']), tick=tick, opening_cost=cost,
                    funding=number(pos.get('realized_funding') or 0), exit_rate=rate,
                    exit_at=end-60 if eligible else 0, window_end=end, eligible=eligible,
                    price=price, asof=now, order_open=stop['state'] in ('open','pending'),
                    product_id=pid, added=added)

    def prepare(self, user, symbol):
        p = self.snapshot(user, symbol)
        if not p['quantity'] or not p['order_open']:
            raise ProtectionError('An open position with an accepted broker stop is required')
        return p

    def load(self, user, p):
        return self.snapshot(user, p['symbol'], p['stop_id'], p['enabled_at'])

    def tighten(self, user, p, desired):
        current = self.load(user, p)
        if (current.get('account') != p['account'] or current.get('entry') != p['entry']
                or current.get('opened_at') != p['opened_at'] or current.get('added')
                or not current.get('order_open') or current['quantity']*p['quantity'] <= 0
                or abs(current['quantity']) > p['remaining_quantity']):
            raise ProtectionChanged('Position changed before stop modification; review before restarting')
        from services.risk.profit_protection import evaluate
        fresh = {**p, **{k:current[k] for k in ('units', 'opening_cost', 'funding', 'exit_rate')}}
        fresh['stop'] = max(p['stop'], current['stop']) if p['side'] > 0 else min(p['stop'], current['stop'])
        fresh['window_end'] = min(p['window_end'], current['window_end'])
        fresh['exit_at'] = min(p['exit_at'], current['exit_at'])
        decision = evaluate(fresh, current['price'], time.time(), eligible=current['eligible'] and p['eligible'])
        if decision['action'] != 'tighten':
            raise ProtectionError('Stop conditions changed during the check; existing protection retained')
        sign = p['side']
        desired = max(desired, decision['stop']) if sign > 0 else min(desired, decision['stop'])
        if sign*(desired-current['stop']) <= 0:
            return current['stop']
        if sign*(current['price']-desired) < p['tick']:
            raise ProtectionError('Price reached the proposed stop; existing protection retained')
        auth = self.auth(user)
        response = self.call(auth, '/v2/orders', method='PUT', body={
            'id':int(p['stop_id']), 'product_id':p['product_id'],
            'size':int(abs(current['quantity'])), 'stop_price':str(desired), 'reduce_only':True,
        })['result']
        if (str(response.get('id')) != p['stop_id'] or response.get('reduce_only') is not True
                or response.get('state') not in ('open','pending')):
            raise ProtectionError('Stop modification is awaiting broker confirmation')
        return number(response['stop_price'])

    def close(self, user, p, client_id):
        try:
            current = self.load(user, p)
        except ProtectionChanged as exc:
            raise UnsentProtectionChanged(str(exc)) from exc
        except Exception as exc:
            raise NotSubmitted('Exit preflight could not verify the position; no exit submitted') from exc
        if (current.get('account') != p['account'] or current.get('entry') != p['entry']
                or current.get('opened_at') != p['opened_at'] or current.get('added')
                or current['quantity']*p['quantity'] <= 0 or abs(current['quantity']) > p['remaining_quantity']):
            raise NotSubmitted('Position changed before exit; waiting for reconciliation')
        from services.risk.profit_protection import evaluate
        fresh = {**p, **{k:current[k] for k in ('units', 'opening_cost', 'funding', 'exit_rate')}}
        fresh['stop'] = max(p['stop'], current['stop']) if p['side'] > 0 else min(p['stop'], current['stop'])
        fresh['window_end'] = min(p['window_end'], current['window_end'])
        fresh['exit_at'] = min(p['exit_at'], current['exit_at'])
        decision = evaluate(fresh, current['price'], time.time(), eligible=current['eligible'] and p['eligible'])
        if decision['action'] != 'exit':
            raise NotSubmitted('The profitable exit condition changed; broker stop retained')
        result = self.call(self.auth(user), '/v2/orders', method='POST', body={
            'product_id':p['product_id'], 'size':int(abs(current['quantity'])),
            'side':'sell' if p['side'] > 0 else 'buy', 'order_type':'market_order',
            'reduce_only':True, 'client_order_id':client_id,
        })['result']
        return str(result['id'])

    def reconcile(self, user, p):
        # Exit identity reconciliation must not depend on an untouched stop.
        auth = self.auth(user)
        pid, _, _, _ = self.info(p['symbol'])
        row = self.call(auth, '/v2/positions', params={'product_id':pid})['result']
        return dict(quantity=number(row['size']), account=hashlib.sha256(auth.encode()).hexdigest(), asof=time.time())

    def exit_status(self, user, p):
        intent = p['exit_intent']
        path = f"/v2/orders/{intent['order_id']}" if intent.get('order_id') else f"/v2/orders/client_order_id/{intent['client_id']}"
        return self.call(self.auth(user), path)['result']

    def view(self, user):
        """Read-only position details; never changes product leverage or orders."""
        from database.token_db import get_symbol
        auth = self.auth(user)
        positions = self.call(auth, '/v2/positions/margined')['result']
        if not isinstance(positions, list) or len(positions) > 10:
            raise ProtectionError('Broker position coverage is unavailable')
        result = []
        for row in positions:
            quantity = number(row['size'])
            if not quantity:
                continue
            pid = int(row['product_id'])
            item = dict(symbol=get_symbol(str(pid), 'CRYPTO') or row.get('product_symbol'),
                        quantity=quantity, entry=number(row['entry_price']),
                        leverage=None, stops=[], targets=[], checked_at=time.time())
            try:
                item['leverage'] = number(self.call(auth, f'/v2/products/{pid}/orders/leverage')['result']['leverage'])
            except Exception:
                item['leverage_error'] = 'Broker leverage unavailable'
            try:
                response = self.call(auth, '/v2/orders', params={'product_ids':str(pid), 'states':'open,pending', 'page_size':50})
                if (response.get('meta') or {}).get('after'):
                    raise ProtectionError('Broker protection coverage incomplete')
                for order in response['result']:
                    if (int(order['product_id']) != pid or order.get('state') not in ('open','pending')
                            or order.get('reduce_only') is not True
                            or order.get('side') != ('sell' if quantity > 0 else 'buy')
                            or number(order.get('unfilled_size', order.get('size'))) < abs(quantity)):
                        continue
                    kind = order.get('stop_order_type')
                    if kind in ('stop_loss_order', 'take_profit_order'):
                        item['stops' if kind == 'stop_loss_order' else 'targets'].append(number(order['stop_price']))
            except Exception:
                item['protection_error'] = 'Broker protection unavailable'
            result.append(item)
        return result
