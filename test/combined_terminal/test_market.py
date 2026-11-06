from types import SimpleNamespace
import pytest
from test_ledger import NOW


class Gateway:
    def __init__(self):self.calls=[]
    def quote(self,symbol,exchange):
        self.calls.append(('quote',symbol,exchange))
        return {'ltp':23000 if exchange=='NSE_INDEX' else 100,'bid':99.95,'ask':100,'time':NOW,'source':'Own broker snapshot'}
    def ladder(self,underlying,expiry,count):
        return {'atm_strike':23000,'chain':[{'strike':23000,'ce':{'symbol':f'NIFTY{expiry}23000CE'},'pe':{'symbol':f'NIFTY{expiry}23000PE'}}]}
    def metadata(self,symbol,exchange):return {'underlying':'NIFTY','lot':65,'tick':.05,'freeze':1800,'expiry':'2026-10-22'}
    def history(self,symbol,exchange,interval):
        self.calls.append(('history',symbol,exchange,interval));return []
    def history_range(self,symbol,exchange,interval,start,end):
        return [{'timestamp':NOW-60,'open':100,'high':102,'low':99,'close':101,'volume':10},
                {'timestamp':NOW+60,'open':100,'high':102,'low':99,'close':101,'volume':10}]


def market():
    from services.combined_terminal.market import MarketData
    g=Gateway()
    c=SimpleNamespace(g=g,clock=lambda:NOW,state=lambda:{'settings':{}})
    return MarketData(c,expiry_loader=lambda u,e:['27-OCT-26','22-OCT-26'],
                      setup_evaluator=lambda *a,**k:{'stage':'waiting_break','reason':'Waiting for level break','eligible':False}),g


def test_nearest_expiry_and_selected_pe_use_only_own_gateway():
    data,g=market()
    first=data.snapshot({'underlying':'NIFTY'})
    assert first['expiry']=='22OCT26'
    assert first['symbol']=='NIFTY22OCT2623000CE'
    selected=data.snapshot({'underlying':'NIFTY','expiry':'22OCT26','symbol':'NIFTY22OCT2623000PE'})
    assert selected['symbol']=='NIFTY22OCT2623000PE'
    assert selected['quote']['source']=='Own broker snapshot'
    assert ('history','NIFTY22OCT2623000PE','NFO','1m') in g.calls
    assert not selected['setup']['eligible']


def test_invalid_contract_does_not_silently_switch_to_another():
    data,g=market()
    with pytest.raises(ValueError):data.snapshot({'underlying':'NIFTY','symbol':'SENSEX22OCT2680000CE'})


def test_chart_uses_real_rows_and_does_not_emit_future_bars():
    data,g=market()
    result=data.chart({'symbol':'NIFTY22OCT2623000CE','exchange':'NFO','interval':'1m'})
    assert len(result['candles'])==1
    assert result['candles'][0]['close']==101
    assert result['candles'][0]['time']==int((NOW-60+19800)//60)*60
    with pytest.raises(ValueError):data.chart({'symbol':'NIFTY','exchange':'WRONG','interval':'1m'})
