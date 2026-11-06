import tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from contextlib import contextmanager
from services.delta_chart.service import Store,Rejected,digest
from services.delta_chart.automation import Automation

class FakeService:
    def __init__(self,store):
        from services.delta_chart.plans import ManagedPlans
        self.store=store; self.plans=ManagedPlans(self); self.calls=[]; self.credentials=lambda u:('fake-key','fake-secret')
        self.account='account-a';self.position=None;self.orders=[];self.pending=[]
    def client(self,user):return self,self.account
    def request(self,*args,**kw):return []
    def state(self,user,symbol):return dict(connected=True,environment='india_prod',account=self.account,symbol=symbol,asof=time.time(),position=self.position,orders=self.orders,pending=self.pending,managed_plans=getattr(self,'managed_plans',[]),fills_complete=True,fills=[])
    def action(self,user,data):
        self.auto.authorize_entry(user,data);self.calls.append(data);return dict(status='confirmed',request_id=data['request_id'],order_id='one')
    def manage(self,*a):raise AssertionError('No plan expected')

class AutomationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=Store(Path(self.tmp.name)/'db');self.service=FakeService(self.store);self.auto=Automation(self.service);self.service.auto=self.auto
    def config(self,**extra):return self.auto.configure('alice',dict(account='account-a',symbol='BTCUSD',enabled=True,leverage=50,balance_fraction=1,manual_quantity=1,**extra))
    def decision(self,*a):return dict(context=dict(source_time=60,direction='up',higher_direction='up'),action=dict(side='buy',size=1,price=99.5,leverage=50,order_type='limit_order',auto_protection=dict(stop=95,target=108.5,source_time=60,interval_seconds=60,reason='fixture')),reason='Eligible Long')
    def run_tick(self):
        with patch.object(self.auto,'read_histories',return_value=([],[],time.time())),patch('services.delta_chart.automation.evaluate_strategy',side_effect=self.decision):self.auto.tick_one('alice',force=True)
    def test_default_off_and_account_bound(self):
        self.assertFalse(self.auto.status('alice','account-a','BTCUSD')['enabled'])
        with self.assertRaises(Rejected):self.auto.configure('alice',dict(account='foreign',symbol='BTCUSD',enabled=True))
    def test_durable_config_resume_does_not_enable_new_accounts(self):
        self.config();other=Automation(self.service)
        self.assertTrue(other.status('alice','account-a','BTCUSD')['enabled'])
        self.assertFalse(other.status('bob','account-a','BTCUSD')['enabled'])
    def test_only_one_attempt_per_source_even_with_new_worker(self):
        self.config();self.run_tick();self.run_tick()
        self.assertEqual(len(self.service.calls),1)
        self.service.auto=Automation(self.service);self.auto=self.service.auto;self.run_tick()
        self.assertEqual(len(self.service.calls),1)
    def test_off_revokes_old_reserved_entry_but_does_not_close(self):
        self.config();self.run_tick();payload=self.service.calls[0]
        self.auto.configure('alice',dict(account='account-a',symbol='BTCUSD',enabled=False))
        with self.assertRaises(Rejected):self.auto.authorize_entry('alice',payload)
        self.assertEqual(len(self.service.calls),1)
    def test_enabled_blocks_browser_and_manual_entries(self):
        self.config()
        with self.assertRaises(Rejected):self.auto.authorize_entry('alice',dict(account='account-a',symbol='BTCUSD',action='entry',request_id='fake',entry_mode='manual'))
    def test_open_position_or_pending_outcome_blocks_entry(self):
        self.config()
        for name,value in [('position',dict(size=1)),('orders',[dict(id='one')]),('pending',[dict(request_id='unknown')])]:
            setattr(self.service,name,value);self.run_tick();self.assertEqual(self.service.calls,[]);setattr(self.service,name,None if name=='position' else [])
    def test_unknown_outcome_never_retried(self):
        self.config()
        def unknown(u,data):self.service.calls.append(data);return dict(status='pending',request_id=data['request_id'],message='unknown')
        self.service.action=unknown;self.run_tick();self.run_tick();self.assertEqual(len(self.service.calls),1)
        self.assertIn('confirmation',self.auto.status('alice','account-a','BTCUSD')['message'].lower())
    def test_changed_connection_blocks_saved_enabled_config(self):
        self.config();self.service.account='changed';self.run_tick();self.assertEqual(self.service.calls,[])
    def test_invalid_settings_rejected(self):
        for values in [dict(leverage=201),dict(balance_fraction=.3),dict(manual_quantity=0),dict(leverage=True),dict(enabled='true')]:
            data=dict(account='account-a',symbol='BTCUSD',enabled=True,leverage=50,balance_fraction=1,manual_quantity=1);data.update(values)
            with self.assertRaises(Rejected):self.auto.configure('alice',data)
    def test_same_enabled_config_is_idempotent(self):
        a=self.config();b=self.config();self.assertEqual(a['generation'],b['generation'])
    def test_status_memory_is_read_only_and_bounded(self):
        self.config();self.run_tick();state=self.auto.status('alice','account-a','BTCUSD')
        self.assertEqual(state['context']['direction'],'up');self.assertTrue(state['events'])
        before=len(self.service.calls);self.auto.status('alice','account-a','BTCUSD');self.assertEqual(before,len(self.service.calls))
    def test_drain_during_candle_read_prevents_a_new_entry(self):
        from services.delta_chart.automation import AutomationWorker
        from contextlib import nullcontext
        worker=AutomationWorker(self.auto,nullcontext)
        self.config()
        def history(*a):worker.stopped.set();return [],[],time.time()
        with patch.object(self.auto,'read_histories',side_effect=history),patch('services.delta_chart.automation.evaluate_strategy',side_effect=self.decision):self.auto.tick_one('alice',force=True)
        self.assertEqual(self.service.calls,[])

    def test_non_ema_exit_transition_survives_transient_management_failure(self):
        self.config();self.service.position={'size':1}
        self.service.managed_plans=[dict(id='p',status='active',side='buy',strategy_id='range_rsi',target_mode='trend',source_time=60,interval_seconds=300)]
        with self.store.db() as db:db.execute('INSERT INTO delta_auto_plan_trends VALUES(?,?,?)',('p','up',60))
        calls=[]
        def manage(user,body):
            calls.append(body['decision'])
            if len(calls)==1:raise Rejected('Transient preflight failure')
            return dict(status='confirmed',plan_status='closing',order_id='exit')
        self.service.manage=manage
        with patch.object(self.auto,'read_histories',return_value=([],[],time.time())),patch('services.delta_chart.automation.evaluate_strategy',side_effect=self.decision),patch('services.delta_chart.auto_strategy._segment',return_value=[{'time':120}]),patch('services.delta_chart.auto_strategy._reading',return_value=('down',0,0)):
            self.auto.tick_one('alice',force=True);self.auto.tick_one('alice',force=True)
        self.assertEqual(calls,['exit','exit'])
