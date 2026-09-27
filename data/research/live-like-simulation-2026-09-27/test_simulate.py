"""Synthetic mechanics checks only; never mixed with historical results."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import simulate as s
import pandas as pd
from dataclasses import replace
from datetime import datetime
from unittest.mock import patch
from services.risk.budget import BudgetTrade, evaluate_budget
from services.strategy_module import scalping


def fixture(profile='box15', low=99, high=101, opening=100):
    at=pd.Timestamp('2025-01-06 10:00',tz='Asia/Kolkata')
    row={'id':1,'profile':profile,'day':'2025-01-06','timestamp':at.isoformat(),
         'direction':'CE','lot_size':50,'data_source':'SYNTHETIC_UNIT_TEST_ONLY'}
    path={t:{'open':opening,'high':high,'low':low,'close':opening,'volume':10000}
          for t in pd.date_range(at,at+pd.Timedelta(minutes=15),freq='min')}
    context={'deadline':(at+pd.Timedelta(minutes=15)).isoformat(),'stop':990,'target':1020,'entry':1000}
    index={t:{'open':1000,'high':1001,'low':999,'close':1000} for t in path}
    return at,row,path,context,index


def test_flat_price_loses_costs_and_slippage():
    at,row,path,ctx,index=fixture()
    a=s.Account('normal');code,bucket,risk=a.admission(row,at,s.D(100),s.D(10),ctx)
    assert code is None
    t=a.trade(row,at,path,index,ctx,s.D(10),bucket,risk)
    assert t['reason']=='time' and t['net_pnl']<0 and t['entry_fee']>20
    assert a.cash==s.POLICY.capital+t['net_pnl']


def test_gap_loss_not_clipped_to_budget():
    at,row,path,ctx,index=fixture()
    path[at+pd.Timedelta(minutes=1)]={'open':60,'high':61,'low':59,'close':60,'volume':10000}
    a=s.Account('stress');t=a.trade(row,at,path,index,ctx,s.D(10),'first',s.D(600))
    assert t['net_pnl'] < -1000 and t['reason']=='account_guard_gap'


def test_stop_first_when_both_hit_and_delayed_fill():
    at,row,path,ctx,index=fixture(low=80,high=125)
    a=s.Account('normal');t=a.trade(row,at,path,index,ctx,s.D(10),'first',s.D(600))
    assert t['reason']=='premium_stop' and t['ambiguous'] and t['net_pnl']<0
    a=s.Account('stress');t=a.trade(row,at,path,index,ctx,s.D(10),'first',s.D(600))
    assert t['exit_at']==(at+pd.Timedelta(minutes=1)).isoformat()
    assert t['exit_price']==s.priced(100,a.slip)


def test_index_exit_uses_next_option_open():
    at,row,path,ctx,index=fixture('ema915')
    index[at]['high']=1030
    path[at+pd.Timedelta(minutes=1)]={'open':110,'high':111,'low':109,'close':110,'volume':10000}
    a=s.Account('normal');t=a.trade(row,at,path,index,ctx,s.D(10),'first',s.D(600))
    assert t['reason']=='index_target' and t['exit_price']==s.priced(110,a.slip)


def test_missing_bar_leaves_unresolved_exposure():
    at,row,path,ctx,index=fixture();del path[at+pd.Timedelta(minutes=1)]
    a=s.Account('normal');t=a.trade(row,at,path,index,ctx,s.D(10),'first',s.D(600))
    assert t is None and a.unresolved and len(a.trades)==0


def test_bucket_profits_do_not_refill_or_transfer():
    at,row,path,ctx,index=fixture()
    ledger=[BudgetTrade('1',row['day'],'first','closed',s.D(500),s.D(500),True),
            BudgetTrade('2',row['day'],'later','closed',s.D(800),s.D(-700),True),
            BudgetTrade('3',row['day'],'later','closed',s.D(100),s.D(900),True)]
    d=evaluate_budget(s.POLICY,ledger,row['day'],s.D(25700),s.D(25700),s.D(301))
    assert d.code=='later_budget_exhausted' and d.available==300
    # Unused first allowance cannot be transferred to later trades.
    assert d.metrics['first_remaining']==1000


def test_drawdown_pause_survives_next_day():
    at,row,path,ctx,index=fixture()
    a=s.Account('normal');a.mark(at,s.D(-5001),row,'first',s.D(600))
    assert a.paused
    a.cash=s.D(19999)
    row=row|{'day':'2025-01-07'}
    code,_,_=a.admission(row,at+pd.Timedelta(days=1),s.D(100),s.D(10),ctx)
    assert code=='portfolio_paused'


def test_governor_cutoff_and_cooldown():
    at,row,path,ctx,index=fixture()
    a=s.Account('normal')
    assert a.admission(row,at.replace(hour=14,minute=36),s.D(100),s.D(10),ctx)[0]=='option_window_closed'
    a.closed=[BudgetTrade(str(i),row['day'],'first' if i==0 else 'later','closed',s.D(100),s.D(-50),True) for i in range(2)]
    a.trades=[{'exit_at':at.isoformat()}]
    assert a.admission(row,at+pd.Timedelta(minutes=10),s.D(100),s.D(10),ctx)[0]=='cooldown'


def test_live_premium_stop_parity():
    class Clock:
        @staticmethod
        def now(tz): return datetime(2025,1,6,10,tzinfo=tz)
    for profile in s.PROFILES:
        for units in (25,50,75):
            for quote in (30,80,200):
                leg={'expiry':'09-JAN-25','quantity':units,'lot_size':units,'symbol':'TESTCE','exchange':'NFO'}
                with patch.object(scalping,'datetime',Clock),patch.object(scalping,'quote_price',return_value=quote),patch.object(scalping,'require_option_liquidity'):
                    result=scalping.protect_leg(leg,{'profile':profile},None)
                assert s.D(result['sl_pts'])==s.stop_points(profile,s.D(quote),units)
