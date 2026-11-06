from types import SimpleNamespace
import pytest


def gateway(monkeypatch):
    from services.combined_terminal.flattrade_gateway import FlattradeGateway
    from database import auth_db, settings_db
    monkeypatch.setattr(settings_db, 'get_analyze_mode', lambda:False)
    monkeypatch.setenv('BROKER_API_KEY', 'CLIENT:::api-key')
    monkeypatch.setattr(auth_db, 'get_api_key_for_tradingview', lambda user:'internal')
    monkeypatch.setattr(auth_db, 'get_auth_token_broker', lambda key:('token','flattrade'))
    monkeypatch.setattr(auth_db, 'get_user_id', lambda user:'CLIENT')
    return FlattradeGateway('alice', 'live')


def test_changed_login_refused(monkeypatch):
    from database import auth_db
    g = gateway(monkeypatch)
    monkeypatch.setattr(auth_db, 'get_user_id', lambda user:'OTHER')
    with pytest.raises(ValueError, match='account'):
        g.credentials()


@pytest.mark.parametrize('raw,code,oid,want', [
    ({'stat':'Ok','norenordno':'1'},200,'1','accepted'),
    ({'stat':'Not_Ok','emsg':'Rejected'},400,None,'rejected'),
    ({'stat':'Not_Ok','emsg':'Unknown'},503,None,'unknown'),
    ({},200,None,'unknown'),
])
def test_flattrade_submission_evidence(monkeypatch,raw,code,oid,want):
    from broker.flattrade.api import order_api
    g = gateway(monkeypatch)
    monkeypatch.setattr(order_api,'place_order_api',lambda *a:(SimpleNamespace(status_code=code),raw,oid))
    g.metadata=lambda *a:{'lot':65,'tick':.05,'freeze':1800}
    result=g.submit({'symbol':'NIFTY','exchange':'NFO','action':'BUY','pricetype':'LIMIT','quantity':65,'price':100,'tag':'id'})
    assert result['state']==want
    assert 'emsg' not in result


@pytest.mark.parametrize('kind',['SL-M','BO','CO'])
def test_unsupported_order_type_not_sent(monkeypatch,kind):
    from broker.flattrade.api import order_api
    g=gateway(monkeypatch)
    calls=[]
    monkeypatch.setattr(order_api,'place_order_api',lambda *a:calls.append(a))
    result=g.submit({'pricetype':kind,'symbol':'NIFTY','exchange':'NFO','action':'BUY'})
    assert result['state']=='rejected'
    assert calls==[]


def test_fresh_protected_exit_is_explicit_limit(monkeypatch):
    from broker.flattrade.api import order_api
    import time
    g=gateway(monkeypatch); calls=[]
    g.metadata=lambda *a:{'lot':65,'tick':.05,'freeze':1800}
    g.quote=lambda *a:{'ltp':100,'bid':99.95,'ask':100,'time':time.time(), 'lower_circuit':50,'upper_circuit':150}
    monkeypatch.setattr(order_api,'place_order_api',lambda d,t:(calls.append(d) or SimpleNamespace(status_code=200),{'stat':'Ok'},'exit'))
    r=g.submit({'pricetype':'MARKET','symbol':'NIFTY','exchange':'NFO','action':'SELL','quantity':65,'tag':'exit'})
    assert r['state']=='accepted'
    assert r['effective_pricetype']=='LIMIT'
    assert calls[0]['pricetype']=='LIMIT'
    assert 50 <= calls[0]['price'] < 100


def test_missing_or_stale_stop_constraints_refused(monkeypatch):
    import time
    g=gateway(monkeypatch)
    g.metadata=lambda *a:{'tick':.05}
    g.quote=lambda *a:{'ltp':100,'bid':99.95,'time':time.time()-10,'lower_circuit':50,'upper_circuit':150}
    with pytest.raises(ValueError):g.stop_limit('NIFTY','NFO',95)
    g.quote=lambda *a:{'ltp':100,'bid':99.95,'time':time.time()}
    with pytest.raises(ValueError):g.stop_limit('NIFTY','NFO',95)


def test_malformed_books_not_normalized_to_empty(monkeypatch):
    from broker.flattrade.api import order_api
    g=gateway(monkeypatch)
    monkeypatch.setattr(order_api,'get_order_book',lambda t:{'stat':'Not_Ok','emsg':'Session Expired'})
    with pytest.raises(ValueError):g.books()


def test_unfilled_sell_stop_stays_pending(monkeypatch):
    from broker.flattrade.api import order_api
    from broker.flattrade.mapping import order_data
    g=gateway(monkeypatch)
    order={'stat':'Ok','token':'1','tsym':'NIFTY','exch':'NFO','trantype':'S','qty':'65','fillshares':'0','avgprc':'0',
           'prc':'92','trgprc':'95','prctyp':'SL-LMT','prd':'M','norenordno':'sl1','status':'TRIGGER_PENDING','norentm':'20:10:2026 10:00:00','remarks':'ct1'}
    monkeypatch.setattr(order_api,'get_order_book',lambda t:[order])
    monkeypatch.setattr(order_api,'get_positions',lambda t:[])
    monkeypatch.setattr(order_api,'get_trade_book',lambda t:[])
    monkeypatch.setattr(order_data,'get_oa_symbol',lambda *a:'NIFTY')
    monkeypatch.setattr(order_data,'get_symbol',lambda *a:'NIFTY')
    result=g.books(include_cash=False)
    assert result['orders'][0]['filled_quantity']==0
    assert result['orders'][0]['pricetype']=='SL'
    assert result['orders'][0]['order_status'] in ('open',)


def test_quote_retains_broker_circuit_bounds(monkeypatch):
    from broker.flattrade.api import data
    monkeypatch.setenv('BROKER_API_KEY','CLIENT:::key')
    monkeypatch.setattr(data,'get_br_symbol',lambda *a:'NIFTY')
    monkeypatch.setattr(data,'get_token',lambda *a:'1')
    monkeypatch.setattr(data,'get_api_response',lambda *a,**k:{'stat':'Ok','lp':'100','bp1':'99.95','sp1':'100','ti':'.05','lc':'50','uc':'150'})
    q=data.BrokerData('token').get_quotes('NIFTY','NFO')
    assert q['lower_circuit']==50
    assert q['upper_circuit']==150


def test_documented_empty_books_are_distinct_from_session_error(monkeypatch):
    from broker.flattrade.api import order_api
    g=gateway(monkeypatch)
    for name in ('get_order_book','get_positions','get_trade_book'):
        monkeypatch.setattr(order_api,name,lambda t:{'stat':'Not_Ok','emsg':'no data'})
    data=g.books(include_cash=False)
    assert data['orders']==data['positions']==data['fills']==[]


def test_noren_fill_time_normalizes_without_inventing_date():
    from services.combined_terminal.flattrade_gateway import fill_epoch
    from datetime import datetime
    from zoneinfo import ZoneInfo
    assert fill_epoch('10:01:02 20-10-2026')==datetime(2026,10,20,10,1,2,tzinfo=ZoneInfo('Asia/Kolkata')).timestamp()
    with pytest.raises(ValueError):fill_epoch('10:01:02')


def test_combined_order_tag_survives_broker_mapping(monkeypatch):
    from broker.flattrade.mapping import transform_data as mapping
    monkeypatch.setattr(mapping,'get_br_symbol',lambda *a:'NIFTYCE')
    data={'apikey':'CLIENT','symbol':'NIFTYCE','exchange':'NFO','product':'MIS','action':'BUY',
          'quantity':65,'price':100,'pricetype':'LIMIT','_combined_terminal_tag':'ka123456789012345678'}
    result=mapping.transform_data(data,'1')
    assert result['remarks']=='ka123456789012345678'


def test_monitor_and_management_share_book_reads(monkeypatch):
    from broker.flattrade.api import order_api
    g=gateway(monkeypatch);calls=[]
    def empty(token):calls.append('read');return []
    for name in ('get_order_book','get_positions','get_trade_book'):
        monkeypatch.setattr(order_api,name,empty)
    first=g.books(include_cash=False)
    second=g.books(include_cash=False)
    assert first==second
    assert len(calls)==3


def test_stream_quotes_keep_their_source_and_cache_only_band_lookup(monkeypatch):
    import time
    from broker.flattrade.api.data import BrokerData
    g=gateway(monkeypatch);calls=[]
    monkeypatch.setattr(g,'watch',lambda *a:None)
    g._ticks[('NIFTY','NFO')]={'ltp':101,'bid':100.95,'ask':101,'time':time.time(),'source':'Live feed'}
    def quote(*a):calls.append('quote');return {'ltp':100,'bid':99.95,'ask':100,'lower_circuit':50,'upper_circuit':150}
    monkeypatch.setattr(BrokerData,'get_quotes',quote)
    first=g.quote('NIFTY','NFO');second=g.quote('NIFTY','NFO')
    assert first['ltp']==second['ltp']==101
    assert first['source']=='Live feed'
    assert first['lower_circuit']==50
    assert len(calls)==1


def test_rest_fallback_leaves_budget_for_history_and_protection(monkeypatch):
    from broker.flattrade.api import order_api
    from broker.flattrade.api.data import BrokerData
    from services import funds_service
    from services.combined_terminal import flattrade_gateway
    g=gateway(monkeypatch);calls=[];at=[1000.]
    monkeypatch.setattr(flattrade_gateway.time,'time',lambda:at[0])
    monkeypatch.setattr(g,'watch',lambda *a:None)
    def empty(*a):calls.append('books');return []
    for name in ('get_order_book','get_positions','get_trade_book'):monkeypatch.setattr(order_api,name,empty)
    def funds(*a):calls.append('funds');return True,{'status':'success','data':{'availablecash':30000}},200
    monkeypatch.setattr(funds_service,'get_funds_with_auth',funds)
    def quote(*a):calls.append('quote');return {'ltp':100,'bid':99.95,'ask':100}
    monkeypatch.setattr(BrokerData,'get_quotes',quote)
    for second in range(60):
        at[0]=1000+second
        g.books();g.books()  # central observation + independent protection
        for symbol in ('NIFTY','CE','PE'):
            assert 0<=at[0]-g.quote(symbol,'NFO')['time']<=5
            g.quote(symbol,'NFO')
    assert len(calls)<=90  # 110/min shared limiter leaves >=20 chart/history reads.
