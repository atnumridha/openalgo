import json
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4
from services.delta_chart.service import TradingService, Store, Rejected, digest
from test_delta_chart_maker import MakerClient

class EntryGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store=Store(Path(self.tmp.name)/'test.db'); self.client=MakerClient(); self.client.size=0
        self.service=TradingService(self.store,lambda u:('key','secret'),lambda k,s:self.client)
        self.account=self.service.state('alice','BTCUSD')['account']
    def entry(self):
        return self.service.action('alice',dict(request_id=str(uuid4()),account=self.account,symbol='BTCUSD',action='entry',side='buy',size=1,price=99.5))
    def assert_blocked(self):
        with self.assertRaises(Rejected):self.entry()
        self.assertFalse(any(m!='GET' for m,p,b in self.client.calls))
    def test_blocks_existing_selected_position_even_without_managed_plan(self):
        self.client.size=1;self.assert_blocked()
    def test_blocks_other_symbol_position(self):
        original=self.client.request
        self.client.request=lambda m,p,**kw: ([{'product_id':3136,'size':1}] if m=='GET' and p=='/v2/positions/margined' and not kw.get('params') else original(m,p,**kw))
        self.assert_blocked()
    def test_blocks_any_pending_account_order(self):
        self.client.orders=[dict(id=42,product_id=3136,state='pending')];self.assert_blocked()
    def test_final_check_catches_position_opened_during_preflight(self):
        original=self.client.request; seen=0
        def req(m,p,**kw):
            nonlocal seen
            if m=='GET' and p=='/v2/positions/margined' and not kw.get('params'):
                seen+=1;return [] if seen==1 else [{'size':1}]
            return original(m,p,**kw)
        self.client.request=req;self.assert_blocked()
    def test_unknown_account_snapshot_fails_closed(self):
        original=self.client.request
        self.client.request=lambda m,p,**kw: ({} if m=='GET' and p=='/v2/positions/margined' and not kw.get('params') else original(m,p,**kw))
        self.assert_blocked()
    def test_flat_account_can_submit_one_maker_entry(self):
        self.assertEqual(self.entry()['status'],'confirmed')
        before=len([x for x in self.client.calls if x[0]!='GET'])
        with self.assertRaises(Rejected):self.entry()
        self.assertEqual(before,len([x for x in self.client.calls if x[0]!='GET']))
    def test_pending_other_symbol_intent_blocks_entry(self):
        self.store.claim('alice',dict(request_id=str(uuid4()),account='lock',symbol='ETHUSD',action='entry'),'one')
        with self.assertRaises(Rejected):self.store.claim('alice',dict(request_id=str(uuid4()),account='lock',symbol='BTCUSD',action='entry'),'two')
    def test_unfilled_post_only_cancel_reconciles_rejected_not_accepted(self):
        rid=str(uuid4()); data=dict(request_id=rid,account=self.account,symbol='BTCUSD',action='entry')
        self.store.claim('alice',data,digest(data))
        self.store.evidence('alice',rid,dict(method='POST',path='/v2/orders',payload=dict(client_order_id=rid.replace('-',''),size=1)))
        original=self.client.request
        self.client.request=lambda m,p,**kw: (dict(id=88,product_id=27,client_order_id=rid.replace('-',''),size=1,unfilled_size=1,state='cancelled',cancellation_reason='immediate_execution_post_only') if '/client_order_id/' in p else original(m,p,**kw))
        self.service.reconcile('alice','BTCUSD',self.client,27)
        self.assertEqual(self.store.receipts('alice','BTCUSD')[0]['status'],'rejected')
        self.assertEqual(self.store.receipts('alice','BTCUSD')[0]['order_id'],'88')
    def test_partial_fill_then_cancel_is_not_reported_as_an_unfilled_rejection(self):
        order=dict(state='cancelled',size=2,unfilled_size=1,cancellation_reason='cancelled_by_user')
        self.assertIsNone(self.service.unfilled_cancellation(order,dict(size=2)))
    def test_cancelled_immediate_ack_is_rejected_without_retry(self):
        original=self.client.request
        def req(m,p,**kw):
            if m=='POST' and p=='/v2/orders':
                self.client.calls.append((m,p,kw.get('payload')))
                return dict(id=88,state='cancelled',size=1,unfilled_size=1,cancellation_reason='immediate_execution_post_only')
            return original(m,p,**kw)
        self.client.request=req
        with self.assertRaisesRegex(Rejected,'Maker-only'):self.entry()
        self.assertEqual(len([x for x in self.client.calls if x[0]=='POST']),1)
    def test_exit_and_protection_are_available_with_an_open_position(self):
        self.client.size=1
        state=self.service.state('alice','BTCUSD')
        self.assertEqual(self.service.action('alice',dict(request_id=str(uuid4()),account=self.account,symbol='BTCUSD',action='protect',stop=95,position_version=state['position']['version']))['status'],'confirmed')
        self.assertEqual(self.service.action('alice',dict(request_id=str(uuid4()),account=self.account,symbol='BTCUSD',action='close',position_version=state['position']['version']))['status'],'confirmed')
