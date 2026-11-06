"""Durable local Auto owner. Every financial action uses the existing intent ledger."""
import hashlib
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4, uuid5, NAMESPACE_URL

from .service import Rejected, digest, number, symbol_value


def evaluate_strategy(*args):
    from .strategy_ensemble import decide
    state, fast, slow, settings, observed, now, *extra = args
    histories = {"1m": fast, "5m": slow, **(extra[0] if extra else {})}
    return decide(state, histories, settings, observed, now)


class Automation:
    def __init__(self, service):
        self.service, self.store = service, service.store
        self.stopping = threading.Event()
        with self.store.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS delta_automation (user TEXT PRIMARY KEY,account TEXT,symbol TEXT,enabled INTEGER,generation TEXT,settings TEXT,value TEXT,last_checked REAL,next_check REAL)')
            db.execute('CREATE TABLE IF NOT EXISTS delta_auto_attempts (request_id TEXT PRIMARY KEY,user TEXT,generation TEXT,source REAL,payload TEXT,fingerprint TEXT,response TEXT,UNIQUE(user,generation,source))')
            db.execute('CREATE TABLE IF NOT EXISTS delta_auto_setups (user TEXT,account TEXT,symbol TEXT,setup_id TEXT,request_id TEXT,PRIMARY KEY(user,account,symbol,setup_id))')
            db.execute('CREATE TABLE IF NOT EXISTS delta_auto_plan_trends (plan_id TEXT PRIMARY KEY,direction TEXT,source REAL)')
            if 'daily_key' not in {r[1] for r in db.execute('PRAGMA table_info(delta_auto_attempts)')}:
                db.execute('ALTER TABLE delta_auto_attempts ADD COLUMN daily_key TEXT')
            db.execute('CREATE UNIQUE INDEX IF NOT EXISTS delta_auto_daily_once ON delta_auto_attempts(user,daily_key) WHERE daily_key IS NOT NULL')
            db.execute('CREATE TABLE IF NOT EXISTS delta_auto_events (id INTEGER PRIMARY KEY AUTOINCREMENT,user TEXT,event_key TEXT,at REAL,kind TEXT,source REAL,details TEXT,UNIQUE(user,event_key))')

    def row(self, user):
        with self.store.db() as db:
            row=db.execute('SELECT * FROM delta_automation WHERE user=?',(user,)).fetchone()
        return dict(row) if row else None

    def status(self, user, account, symbol):
        row=self.row(user)
        result=dict(owner='backend',enabled=False,account=account,symbol=symbol,leverage=50,balance_fraction=1,manual_quantity=1,generation='',status='off',message='Off · no automatic entries.',checked_at=None,next_check_at=None,context=None,events=[])
        if not row:return result
        result.update(json.loads(row['settings']))
        result.update(json.loads(row['value']))
        result.update(enabled=bool(row['enabled']),account=row['account'],symbol=row['symbol'],generation=row['generation'],checked_at=row['last_checked'],next_check_at=row['next_check'])
        with self.store.db() as db:
            events=db.execute('SELECT id,at,kind,source,details FROM delta_auto_events WHERE user=? ORDER BY id DESC LIMIT 20',(user,)).fetchall()
        result['events']=[dict(id=e['id'],at=e['at'],kind=e['kind'],source_time=e['source'],details=json.loads(e['details'])) for e in events]
        return result

    def event(self,user,key,kind,source,details):
        with self.store.db() as db:
            db.execute('INSERT OR IGNORE INTO delta_auto_events(user,event_key,at,kind,source,details) VALUES(?,?,?,?,?,?)',(user,key,time.time(),kind,source,json.dumps(details,allow_nan=False)))
            db.execute('DELETE FROM delta_auto_events WHERE user=? AND id NOT IN (SELECT id FROM delta_auto_events WHERE user=? ORDER BY id DESC LIMIT 10000)',(user,user))

    def configure(self,user,data):
        if not isinstance(data,dict) or type(data.get('enabled')) is not bool:
            raise Rejected('Auto requires an explicit On or Off selection')
        _,account=self.service.client(user)
        if data.get('account')!=account:raise Rejected('Account changed; refresh before changing Auto')
        symbol=symbol_value(data.get('symbol'))
        # Same global entry lock as TradingService: an Off acknowledgement is a
        # barrier after any already-started placement, not a cancellation promise.
        key=hashlib.sha256(self.service.credentials(user)[0].encode()).hexdigest()
        with self.service.plans.lock('delta-entry',key,'*'):
            old=self.row(user)
            if data['enabled']:
                lev=data.get('leverage',50); fraction=data.get('balance_fraction',1); qty=data.get('manual_quantity',1)
                if type(lev) is not int or not 1<=lev<=200 or type(qty) is not int or qty<1:
                    raise Rejected('Use leverage 1–200 and a positive whole lot size')
                if fraction is not None and (type(fraction) not in (int,float) or fraction not in (.1,.25,.5,.75,1)):
                    raise Rejected('Use a valid balance percentage or fixed lots')
                settings=dict(leverage=lev,balance_fraction=fraction,manual_quantity=qty)
                if old and old['enabled']:
                    if old['account']==account and old['symbol']==symbol and json.loads(old['settings'])==settings:
                        return self.status(user,account,symbol)
                    raise Rejected('Turn Auto Off before changing its symbol or sizing')
            else:
                settings=json.loads(old['settings']) if old else dict(leverage=50,balance_fraction=1,manual_quantity=1)
                if old and not old['enabled']:return self.status(user,account,symbol)
                if old:symbol=old['symbol']
            generation=str(uuid4()); value=dict(status='reconciling' if data['enabled'] else 'off',message='Reconciling account, orders and saved intents before scanning.' if data['enabled'] else 'Off · new entries stopped; existing trades retain protection.',context=json.loads(old['value']).get('context') if old else None)
            with self.store.db() as db:
                db.execute('INSERT INTO delta_automation VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(user) DO UPDATE SET account=excluded.account,symbol=excluded.symbol,enabled=excluded.enabled,generation=excluded.generation,settings=excluded.settings,value=excluded.value,next_check=0',(user,account,symbol,int(data['enabled']),generation,json.dumps(settings),json.dumps(value),None,0))
            self.event(user,'config:'+generation,'control',None,dict(enabled=data['enabled'],symbol=symbol,settings=settings))
        return self.status(user,account,symbol)

    def authorize_entry(self,user,data):
        _, current_account = self.service.client(user)
        if data.get('account') != current_account:
            raise Rejected('Account connection changed; no entry was sent')
        row=self.row(user); generation=data.get('automation_generation')
        if generation and self.stopping.is_set():
            raise Rejected('Backend is stopping; no new entry was sent')
        if not row or not row['enabled']:
            if generation:raise Rejected('Auto permission was revoked; no order was sent')
            if getattr(self.service,'enforce_server_automation',False) and data.get('entry_mode')!='manual':
                raise Rejected('Automatic entries are backend-owned. Reload the chart and use backend Auto.')
            return
        if row['account']!=data.get('account') or row['symbol']!=data.get('symbol') or generation!=row['generation']:
            raise Rejected('Backend Auto is running. Turn it Off before placing a manual or browser entry.')
        observed=data.get('automation_observed_at')
        if observed is not None and (time.time()-float(number(observed,True))>30 or float(number(observed,True))>time.time()):
            raise Rejected('Auto decision data expired; no order was sent')
        with self.store.db() as db:
            attempt=db.execute('SELECT fingerprint FROM delta_auto_attempts WHERE user=? AND generation=? AND request_id=?',(user,generation,data.get('request_id'))).fetchone()
        if not attempt or attempt['fingerprint']!=digest(data):raise Rejected('Unverified backend Auto decision; no order was sent')

    def read_histories(self,client,symbol):
        observed=time.time()
        def read(resolution,seconds):
            rows=client.request('GET','/v2/history/candles',params=dict(symbol=symbol,resolution=resolution,start=int(observed-301*seconds),end=int(observed)),private=False)
            if not isinstance(rows,list):raise Rejected('Fresh candle history is unavailable')
            return rows
        with ThreadPoolExecutor(max_workers=2,thread_name_prefix='delta-auto-candles') as pool:
            fast=pool.submit(read,'1m',60);slow=pool.submit(read,'5m',300)
            first, second = fast.result(), slow.result()
        with ThreadPoolExecutor(max_workers=4,thread_name_prefix='delta-auto-context') as pool:
            futures = {interval: pool.submit(read,interval,span) for interval,span in [('15m',900),('1h',3600),('4h',14400),('1d',86400)]}
            extra = {}
            for interval,future in futures.items():
                try:extra[interval]=future.result()
                except Exception:extra[interval]=[]
        return first, second, observed, extra

    def update(self,row,status,message,context=None,delay=5):
        now=time.time()
        value=dict(status=status,message=message,context=context if context is not None else json.loads(row['value']).get('context'))
        with self.store.db() as db:
            changed=db.execute('UPDATE delta_automation SET value=?,last_checked=?,next_check=? WHERE user=? AND generation=?',(json.dumps(value,allow_nan=False),now,now+delay,row['user'],row['generation'])).rowcount
        if changed:
            source=(value['context'] or {}).get('source_time')
            key=digest(dict(generation=row['generation'],source=source,status=status,message=message))
            self.event(row['user'],key,status,source,dict(message=message,context={k:v for k,v in (value['context'] or {}).items() if k!='bars'}))

    def tick(self):
        with self.store.db() as db:users=[r[0] for r in db.execute('SELECT user FROM delta_automation WHERE next_check<=?',(time.time(),))]
        for user in users:self.tick_one(user)

    def tick_one(self,user,force=False):
        row=self.row(user)
        if not row or (not force and row['next_check']>time.time()):return
        try:
            client,account=self.service.client(user)
            if account!=row['account']:raise Rejected('Account connection changed. Turn Auto Off and review the connection.')
            key=hashlib.sha256(self.service.credentials(user)[0].encode()).hexdigest()
            with self.service.plans.lock('delta-auto-owner',key,'*'):
                row=self.row(user)
                if not row or (not force and row['next_check']>time.time()):return
                self._evaluate(row,client,account)
        except Exception as exc:
            self.update(row,'waiting',str(exc) if isinstance(exc,Rejected) else 'Broker data unavailable. Waiting for a fresh verified account snapshot.',delay=10)

    def remember_outcomes(self, row, client, state):
        """Store observed owned round trips; unknown costs never become learning labels."""
        completed=[p for p in state.get('managed_plans',[]) if p.get('status')=='completed']
        if not completed or not hasattr(self.service,'recent_fills') or not state.get('product'):
            return
        from .auto_outcomes import completed_trade_outcome
        product=state['product']
        fills=None
        for plan in completed:
            key='outcome:'+plan['id']
            with self.store.db() as db:
                saved=db.execute('SELECT 1 FROM delta_auto_events WHERE user=? AND event_key=?',(row['user'],key)).fetchone()
            if saved:
                continue
            if fills is None:
                fills=self.service.recent_fills(client,row['account'],product['id'])
            raw=self.service.plans.get(row['user'],plan['id'])
            outcome=completed_trade_outcome(raw,product,fills,isinstance(fills,list))
            self.event(row['user'],key if outcome['available'] else 'outcome-wait:'+plan['id'],
                       'outcome' if outcome['available'] else 'outcome_unavailable',
                       plan.get('source_time'),outcome)

    def management_status(self,row,responses,context=None):
        """A failed protection observation is never a normal managing state."""
        issues=[]
        for plan_id,response in responses:
            blocked=response.get('status')=='rejected' or response.get('plan_status')=='blocked'
            pending=response.get('status')=='pending'
            if not (blocked or pending):
                continue
            kind='protection_blocked' if blocked else 'protection_pending'
            message=response.get('message') or 'Protection needs broker reconciliation.'
            details=dict(plan_id=plan_id,message=message,plan_status=response.get('plan_status'))
            self.event(row['user'],'protection:'+digest(dict(kind=kind,**details)),kind,
                       (context or {}).get('source_time'),details)
            issues.append((blocked,kind,message))
        if issues:
            _,kind,message=max(issues,key=lambda issue:issue[0])
            self.update(row,kind,message+' New entries wait while this trade is unresolved.',context,delay=5)
            return True
        return False

    @staticmethod
    def last_fill_time(state):
        from .service import fill_timestamp
        stamps=[]
        for fill in state.get('fills',[]):
            try:
                stamp=fill_timestamp(fill['created_at'])
                stamps.append(float(stamp))
            except (KeyError,ValueError,TypeError,OverflowError,Rejected):
                raise Rejected('Fill timestamps are unverified; waiting before reusing a setup.') from None
        return max(stamps) if stamps else None

    def _evaluate(self,row,client,account):
        user,symbol=row['user'],row['symbol']
        state=self.service.state(user,symbol)
        if not state.get('connected') or state.get('account')!=account or not 0<=time.time()-state.get('asof',0)<=10:
            raise Rejected('Waiting for fresh verified Delta account data')
        self.remember_outcomes(row,client,state)
        active=[p for p in state.get('managed_plans',[]) if p['status'] not in ('completed','cancelled','rejected')]
        blocked=[(p['id'],dict(status='rejected',plan_status='blocked',message=p.get('message','Owned protection is blocked.'))) for p in active if p.get('status')=='blocked']
        if blocked:
            self.management_status(row,blocked);return
        if not row['enabled'] and not active:
            self.update(row,'off','Off · no automatic entries.',delay=30);return
        if state.get('pending'):
            self.update(row,'reconciling','Waiting for broker confirmation. No new entry will be sent.',delay=5);return
        # A durable unknown outcome blocks even if a temporary account read looks flat.
        with self.store.db() as db:
            attempts=db.execute('SELECT request_id,response FROM delta_auto_attempts WHERE user=?',(user,)).fetchall()
        for item in attempts:
            if item['response'] and json.loads(item['response']).get('status')!='pending':continue
            with self.store.db() as db:receipt=db.execute('SELECT response FROM intents WHERE user=? AND request_id=?',(user,item['request_id'])).fetchone()
            response=json.loads(receipt[0]) if receipt else None
            if not response and item['response'] is None:
                # No durable TradingService intent exists, so the process died
                # before this reservation reached financial submission. Consume
                # that candle without placing a replacement request.
                response=dict(status='rejected',request_id=item['request_id'],message='Reserved decision ended before durable submission; no retry for this candle.')
            if not response or response.get('status')=='pending':
                self.update(row,'reconciling','Waiting for broker confirmation of the saved Auto request.',delay=5);return
            with self.store.db() as db:db.execute('UPDATE delta_auto_attempts SET response=? WHERE request_id=?',(json.dumps(response),item['request_id']))
        try:
            fast,slow,observed,*extras=self.read_histories(client,symbol)
        except Exception:
            responses=[]
            for plan in active:
                try:responses.append((plan['id'],self.service.plans.manage(user,dict(plan_id=plan['id'],decision='sync'),protection_only=True)))
                except Exception:responses.append((plan['id'],dict(status='pending',plan_status='pending',message='Protection reconciliation unavailable; verify broker SL.')))
            if self.management_status(row,responses):return
            raise Rejected('Candle history is unavailable; entry waits and existing broker SL is retained.')
        histories={"1m":fast,"5m":slow,**(extras[0] if extras else {})}
        if not active and not 0<=time.time()-state.get('asof',0)<=10:
            raise Rejected('Account quote aged during candle reads; waiting for fresh setup prices.')
        result=evaluate_strategy(state,fast,slow,json.loads(row['settings']),observed,time.time(),extras[0] if extras else {})
        context=result.get('context') or {}
        position=state.get('position')
        if active or (position and number(position.get('size',0))) or state.get('orders'):
            responses=[]
            for plan in active:
                from .auto_strategy import _segment, _reading
                from decimal import Decimal
                seconds=plan.get('interval_seconds',60)
                resolution={60:'1m',300:'5m',900:'15m',3600:'1h',14400:'4h',86400:'1d'}.get(seconds)
                try:
                    bars=_segment(histories.get(resolution,[]),seconds,Decimal(str(observed)),Decimal(str(time.time())))
                    direction,_,_=_reading(bars); stamp=bars[-1]['time']
                except Exception:
                    try:responses.append((plan['id'],self.service.plans.manage(user,dict(plan_id=plan['id'],decision='sync'),protection_only=True)))
                    except Exception:responses.append((plan['id'],dict(status='pending',plan_status='pending',message='Protection reconciliation unavailable; verify broker SL.')))
                    continue
                with self.store.db() as db:
                    prior=db.execute('SELECT direction,source FROM delta_auto_plan_trends WHERE plan_id=?',(plan['id'],)).fetchone()
                expected='up' if plan['side']=='buy' else 'down'
                opposite=direction==('down' if expected=='up' else 'up')
                strategy=plan.get('strategy_id','ema')
                baseline = prior['direction'] if prior else plan.get('entry_trend_direction')
                changed = strategy=='ema' or (baseline==expected and (not prior or stamp>prior['source']))
                decision='sync'
                if row['enabled'] and plan['status']=='active' and plan.get('target_mode','fixed')=='fixed':
                    decision='let_run'
                if opposite and changed and not plan.get('manual_entry') and stamp>plan['source_time']:
                    if position and plan['status']=='active':decision='exit'
                    elif not position and plan['status']=='awaiting_entry':decision='cancel_entry'
                managed=self.service.manage(user,dict(plan_id=plan['id'],decision=decision,source_time=stamp))
                responses.append((plan['id'],managed))
                # A failed/unknown dispatch must retain the last aligned trend so
                # that the same reversal is still actionable after restart.
                terminal_dispatch = managed.get('status')=='confirmed' and managed.get('plan_status') in ('closing','completed','cancelled')
                if decision not in ('exit','cancel_entry') or terminal_dispatch:
                    with self.store.db() as db:
                        if not prior or stamp>prior['source']:
                            db.execute('INSERT INTO delta_auto_plan_trends VALUES(?,?,?) ON CONFLICT(plan_id) DO UPDATE SET direction=excluded.direction,source=excluded.source',(plan['id'],direction,stamp))
            if self.management_status(row,responses,context):return
            self.update(row,'managing','Existing order/trade is being managed; new entries wait until it exits and sibling orders finish.',context,delay=5);return
        if not row['enabled']:
            self.update(row,'off','Off · no automatic entries.',context,delay=30);return
        if not result.get('action'):
            self.update(row,'watching',result.get('reason') or 'Waiting for an eligible 1m/5m EMA setup.',context);return
        action=dict(result['action'],action='entry',symbol=symbol,account=account,automation_generation=row['generation'],automation_observed_at=observed,target_mode='trend')
        # Remember the strategy's actual EMA context at entry. A countertrend
        # reversal setup must not invent an aligned entry baseline.
        try:
            from .auto_strategy import _segment, _reading
            from decimal import Decimal
            span=action['auto_protection']['interval_seconds']
            resolution={60:'1m',300:'5m',900:'15m',3600:'1h',14400:'4h',86400:'1d'}[span]
            entrybars=_segment(histories.get(resolution,[]),span,Decimal(str(observed)),Decimal(str(time.time())))
            action['entry_trend_direction']=_reading(entrybars)[0]
        except Exception:
            action['entry_trend_direction']=context.get('ema_direction',context.get('direction'))
        source=context.get('source_time')
        if not source:raise Rejected('The completed source candle is unavailable')
        if state.get('fills_complete') is not True:
            self.update(row,'watching','Waiting for verified recent fills before accepting a fresh post-exit setup.',context);return
        setup_id=action.get('setup_id')
        setup_time=action.get('setup_time',source)
        last_exit=self.last_fill_time(state)
        if last_exit is not None and float(number(setup_time,True)) <= last_exit:
            self.update(row,'watching','Waiting for a fresh completed setup formed after the last exit; the previous move is not reused.',context);return
        if setup_id is not None and (not isinstance(setup_id,str) or not 1<=len(setup_id)<=200):
            raise Rejected('Invalid setup identity; no order was sent')
        daily_key = action.get('daily_key')
        if daily_key is not None:
            daily_key = ':'.join((account,symbol,action.get('strategy_id','ema'),action['side'],str(daily_key)))
        rid=str(uuid5(NAMESPACE_URL,'delta-backend-scalp-v1\0'+user+'\0'+account+'\0'+row['generation']+'\0'+str(source)))
        action['request_id']=rid
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            latest=db.execute('SELECT enabled,generation FROM delta_automation WHERE user=?',(user,)).fetchone()
            if not latest or not latest['enabled'] or latest['generation']!=row['generation']:return
            prior=db.execute('SELECT 1 FROM delta_auto_attempts WHERE user=? AND ((generation=? AND source=?) OR (daily_key IS NOT NULL AND daily_key=?))',(user,row['generation'],source,daily_key)).fetchone()
            if not prior and setup_id is not None:
                prior=db.execute('SELECT 1 FROM delta_auto_setups WHERE user=? AND account=? AND symbol=? AND setup_id=?',(user,account,symbol,setup_id)).fetchone()
            if not prior:
                if setup_id is not None:
                    db.execute('INSERT INTO delta_auto_setups VALUES(?,?,?,?,?)',(user,account,symbol,setup_id,rid))
                db.execute('INSERT INTO delta_auto_attempts(request_id,user,generation,source,payload,fingerprint,response,daily_key) VALUES(?,?,?,?,?,?,NULL,?)',(rid,user,row['generation'],source,json.dumps(action,allow_nan=False),digest(action),daily_key))
        if prior:
            self.update(row,'watching','This candle or setup already has an Auto attempt. Waiting for a fresh pullback and confirmation.',context);return
        self.update(row,'placing','Checking and placing '+('Long' if action['side']=='buy' else 'Short')+' maker entry.',context)
        try:response=self.service.action(user,action)
        except Rejected as exc:response=dict(status='rejected',request_id=rid,message=str(exc))
        except Exception:response=dict(status='pending',request_id=rid,message='Outcome unknown; waiting for broker reconciliation.')
        with self.store.db() as db:db.execute('UPDATE delta_auto_attempts SET response=? WHERE request_id=?',(json.dumps(response),rid))
        status=response.get('status')
        self.event(user,'attempt:'+rid,'entry_'+str(status),source,dict(request_id=rid,side=action['side'],size=action['size'],price=action['price'],stop=action['auto_protection']['stop'],target=action['auto_protection']['target'],result=response))
        self.update(row,'reconciling' if status=='pending' else 'resting' if status=='confirmed' else 'watching','Waiting for broker confirmation.' if status=='pending' else 'Maker entry accepted; waiting for a fill.' if status=='confirmed' else 'Entry rejected: '+response.get('message','Delta rejected the entry.'),context)


class AutomationWorker:
    def __init__(self,automation,context_factory,interval=1):
        self.automation=automation;self.context_factory=context_factory;self.interval=interval;self.stopped=automation.stopping;self.thread=None
    def start(self):
        if self.thread:return self
        def run():
            while not self.stopped.is_set():
                try:
                    with self.context_factory():self.automation.tick()
                except Exception:pass
                self.stopped.wait(self.interval)
        self.thread=threading.Thread(target=run,name='delta-backend-auto',daemon=True);self.thread.start();return self
