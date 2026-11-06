import tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from test_delta_automation import FakeService
import test_delta_automation as fixture
from services.delta_chart.service import Store
from services.delta_chart.automation import Automation

class LossRootFixTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.store=Store(Path(self.tmp.name)/'db');self.service=FakeService(self.store);self.auto=Automation(self.service);self.service.auto=self.auto
  self.auto.configure('alice',dict(account='account-a',symbol='BTCUSD',enabled=True,leverage=50,balance_fraction=1,manual_quantity=1))
 def result(self,stamp=60,setup='ema:buy:10',setup_time=10):
  result=fixture.AutomationTests.decision(self)
  result['context']['source_time']=stamp
  result['action']['auto_protection']['source_time']=stamp
  result['action'].update(setup_id=setup,setup_time=setup_time)
  return result
 def tick(self,result=None):
  with patch.object(self.auto,'read_histories',return_value=([],[],time.time())),patch('services.delta_chart.automation.evaluate_strategy',return_value=result or self.result()),patch('services.delta_chart.auto_strategy._segment',return_value=[{'time':120}]),patch('services.delta_chart.auto_strategy._reading',return_value=('up',0,0)):
   self.auto.tick_one('alice',force=True)
 def test_rejected_management_is_never_reported_as_managing(self):
  self.service.position={'size':1};self.service.managed_plans=[dict(id='p',status='active',side='buy',strategy_id='ema',target_mode='trend',source_time=60,interval_seconds=60)]
  self.service.manage=lambda *a:dict(status='rejected',plan_status='blocked',message='Owned SL cancelled')
  self.tick();s=self.auto.status('alice','account-a','BTCUSD')
  self.assertEqual(s['status'],'protection_blocked');self.assertIn('Owned SL cancelled',s['message']);self.assertTrue(any(e['kind']=='protection_blocked'for e in s['events']))
 def test_pending_management_has_specific_waiting_status(self):
  self.service.position={'size':1};self.service.managed_plans=[dict(id='p',status='active',side='buy',strategy_id='ema',target_mode='trend',source_time=60,interval_seconds=60)]
  self.service.manage=lambda *a:dict(status='pending',plan_status='pending',message='SL modification awaiting broker proof')
  self.tick();self.assertEqual(self.auto.status('alice','account-a','BTCUSD')['status'],'protection_pending')
 def test_blocked_plan_visible_even_when_history_unavailable(self):
  self.service.managed_plans=[dict(id='p',status='blocked',message='Owned stop is cancelled')]
  with patch.object(self.auto,'read_histories',side_effect=AssertionError('Must not read history before protection status')):self.auto.tick_one('alice',force=True)
  self.assertEqual(self.auto.status('alice','account-a','BTCUSD')['status'],'protection_blocked')
 def test_management_still_syncs_when_candle_fetch_fails(self):
  self.service.position={'size':1};self.service.managed_plans=[dict(id='p',status='active',side='buy',source_time=60,interval_seconds=60)]
  called=[];self.service.plans.manage=lambda user,body,**kw:called.append(dict(body,**kw))or dict(status='rejected',plan_status='blocked',message='SL unavailable')
  with patch.object(self.auto,'read_histories',side_effect=RuntimeError('public OHLC down')):self.auto.tick_one('alice',force=True)
  self.assertEqual(called[0]['decision'],'sync');self.assertTrue(called[0]['protection_only']);self.assertEqual(self.auto.status('alice','account-a','BTCUSD')['status'],'protection_blocked')
 def test_same_setup_cannot_repeat_on_new_candle_or_after_off_on(self):
  self.tick();self.tick(self.result(120))
  self.assertEqual(len(self.service.calls),1)
  self.auto.configure('alice',dict(account='account-a',symbol='BTCUSD',enabled=False))
  self.auto.configure('alice',dict(account='account-a',symbol='BTCUSD',enabled=True,leverage=50,balance_fraction=1,manual_quantity=1))
  self.tick(self.result(180));self.assertEqual(len(self.service.calls),1)
 def test_new_setup_can_enter_and_no_daily_loss_halt_is_added(self):
  self.tick();self.tick(self.result(120,'ema:buy:80',80));self.assertEqual(len(self.service.calls),2)
 def test_old_setup_cannot_be_reused_after_recent_exit(self):
  self.service.state=lambda *a:dict(connected=True,account='account-a',asof=time.time(),position=None,orders=[],pending=[],managed_plans=[],fills_complete=True,fills=[dict(created_at='1970-01-01T00:01:30Z')])
  self.tick(self.result(120,setup_time=60));self.assertEqual(self.service.calls,[])
  self.assertIn('fresh',self.auto.status('alice','account-a','BTCUSD')['message'].lower())

 def test_numeric_fill_timestamp_is_not_a_fresh_setup_bypass(self):
  self.service.state=lambda *a:dict(connected=True,account='account-a',asof=time.time(),position=None,orders=[],pending=[],managed_plans=[],fills_complete=True,fills=[dict(created_at='90')])
  self.tick(self.result(120,setup_time=60));self.assertEqual(self.service.calls,[])

 def test_unverified_fill_history_cannot_reuse_a_setup(self):
  original=self.service.state
  self.service.state=lambda *a:dict(original(*a),fills_complete=False)
  self.tick();self.assertEqual(self.service.calls,[])
 def test_malformed_fill_time_cannot_bypass_freshness(self):
  original=self.service.state
  self.service.state=lambda *a:dict(original(*a),fills=[dict(created_at='broken')])
  self.tick();self.assertEqual(self.service.calls,[])
