"""Declared post-run diagnostic: separate slippage sensitivity from exit latency."""
from datetime import datetime, UTC
import simulate as s


def main():
    assert not (s.OUT/'cost-sensitivity-results.json').exists()
    s.SCENARIOS['cost_stress']={'slippage_bps':30,'delay_protective':False}
    s.write(s.OUT/'cost-sensitivity-protocol.json',{
        'registered_at':datetime.now(UTC).isoformat(),
        'reason':'The delayed-exit scenario sometimes benefits from a price rebound. Isolate increased slippage with identical normal stop execution, without selecting an optimum.',
        'scenario':s.SCENARIOS['cost_stress'], 'original_protocol_sha256':s.sha(s.OUT/'protocol.json'),
        'script_sha256':s.sha(s.OUT/'simulate.py'), 'no_strategy_changes':True,
    })
    rows,paths,signals,index,installed,_=s.load()
    results={}
    windows=s.read(s.OUT/'protocol.json')['windows'] | {'older_regime_only':['2017-01-01','2020-12-31']}
    for name,(first,last) in windows.items():
        results[name]={}
        profiles=['regime50200'] if name=='older_regime_only' else [*s.PROFILES,'combined']
        for profile in profiles:
            account,summary=s.replay(rows,paths,signals,index,installed,'cost_stress',list(s.PROFILES) if profile=='combined' else [profile],first,last)
            results[name][profile]=summary
            folder=s.OUT/name/'cost_stress'/profile
            folder.mkdir(parents=True,exist_ok=True)
            for filename,value in [('trades',account.trades),('skips',account.skips),('equity',account.curve),('summary',summary)]:
                s.write(folder/(filename+'.json'),value)
        print(name,{p:(r['trades'],round(float(r['net_pnl']),2)) for p,r in results[name].items()},flush=True)
    s.write(s.OUT/'cost-sensitivity-results.json',results)


if __name__=='__main__': main()
