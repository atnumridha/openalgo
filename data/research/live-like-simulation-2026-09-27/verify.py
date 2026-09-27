"""Independent saved-ledger audit; no historical strategy recomputation."""
import json
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path
import simulate as s
import pandas as pd


def main():
    source={r['id']:r for p in s.PROFILES for r in s.read(s.READY/p/'trades.json')}
    accounts,filled,skipped,paused=0,0,0,0
    for folder in sorted(s.OUT.glob('*/*/*')):
        if not folder.is_dir() or not (folder/'summary.json').exists(): continue
        trades=s.read(folder/'trades.json');summary=s.read(folder/'summary.json')
        skips=s.read(folder/'skips.json');curve=s.read(folder/'equity.json')
        assert summary['unresolved'] is None, str(folder)
        assert len(trades)+len(skips)==summary['opportunities']
        assert dict(Counter(r['reason'] for r in skips))==summary['skips']
        assert len({r['id'] for r in trades})==len(trades)
        assert not {r['id'] for r in trades}&{r['id'] for r in skips}
        cash=Decimal(25000);losses=defaultdict(lambda: {'first':Decimal(0),'later':Decimal(0)})
        seen=Counter();previous_exit=None;net=[];pause_exit=None
        scenario=folder.parent.name
        costs=s.COSTS | {'slippage_bps':10 if scenario=='normal' else 30}
        for r in trades:
            entry=pd.Timestamp(r['entry_at']);exit=pd.Timestamp(r['exit_at'])
            assert entry<=exit<=entry+pd.Timedelta(minutes=15)
            assert previous_exit is None or previous_exit<=entry
            previous_exit=exit
            assert pause_exit is None, 'No auto-resume allowed'
            assert r['day']==source[r['id']]['day']
            assert r['units']==source[r['id']]['lot_size']
            assert abs(cash-s.D(r['cash_before']))<s.D('.001')
            entryfee=s.order_cost(s.D(r['entry_price'])*r['units'],'BUY',costs)
            exitfee=s.order_cost(s.D(r['exit_price'])*r['units'],'SELL',costs)
            assert entryfee==s.D(r['entry_fee']) and exitfee==s.D(r['exit_fee'])
            pnl=(s.D(r['exit_price'])-s.D(r['entry_price']))*r['units']-entryfee-exitfee
            assert abs(pnl-s.D(r['net_pnl']))<s.D('.001')
            debit=s.D(r['entry_price'])*r['units']+entryfee
            assert debit<=min(s.D(20000),cash*s.D('.8'))+s.D('.001')
            bucket='first' if seen[r['day']]==0 else 'later'
            assert r['bucket']==bucket
            used=losses[r['day']]
            risk=s.D(r['planned_risk']);peak=s.D(r['peak_before'])
            assert 0<risk<=1000-used[bucket]+s.D('.001')
            assert risk<=2000-sum(used.values())+s.D('.001')
            assert risk<=cash-peak*s.D('.8')+s.D('.001')
            seen[r['day']]+=1
            used[bucket]+=max(s.D(0),-pnl)
            cash+=pnl;net.append(pnl)
            assert abs(cash-s.D(r['cash_after']))<s.D('.001')
            if r['paused_after']: pause_exit=exit
        assert abs(cash-s.D(summary['ending_cash']))<s.D('.001')
        assert abs(sum(net)-s.D(summary['net_pnl']))<s.D('.001')
        assert summary['trades']==len(net) and summary['wins']==sum(p>0 for p in net)
        dd=max((s.D(r['peak'])-s.D(r['equity']) for r in curve),default=s.D(0))
        assert abs(dd-s.D(summary['max_drawdown']))<s.D('.001')
        assert summary['paused']==bool(pause_exit)
        accounts+=1;filled+=len(trades);skipped+=len(skips);paused+=int(summary['paused'])
    for name,h in s.read(s.OUT/'protocol.json')['source_hashes'].items():
        assert s.sha(s.ROOT/name)==h,name
    output={'passed':True,'accounts_audited':accounts,'trade_records_audited':filled,
            'skip_records_audited':skipped,'paused_accounts':paused,'unresolved_accounts':0,
            'note':'Overlapping windows/scenarios reuse observations; trade records are not independent samples.',
            'checks':['starting and ending cash','every entry/exit fee','net P&L','whole lots','cash buffer','one NIFTY position',
                      'first/later shared losses without profit refill','drawdown admission headroom','no auto resume',
                      'maximum holding period','summary reconciliation','production source hashes']}
    s.write(s.OUT/'verification.json',output)
    print(json.dumps(output,indent=2))


if __name__=='__main__':main()
