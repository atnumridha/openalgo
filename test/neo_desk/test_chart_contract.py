from types import SimpleNamespace
from flask import Flask
from blueprints.neo_desk import neo_desk_bp
from database import token_db


def test_chart_metadata_requires_session_and_returns_exact_master_tick(monkeypatch):
    monkeypatch.setenv('NEO_SAVED_LOGIN', 'TRUE')
    calls=[]
    from database import market_calendar_db
    monkeypatch.setattr(market_calendar_db,'get_market_timing',lambda exchange:dict(start_offset=33300000,end_offset=55800000))
    monkeypatch.setattr(token_db,'get_symbol_info',lambda symbol,exchange:calls.append((symbol,exchange)) or SimpleNamespace(tick_size='0.01',lotsize=1,session=dict(start=555,end=930,offset=19800)))
    app=Flask(__name__);app.secret_key='test-only';app.register_blueprint(neo_desk_bp)
    client=app.test_client()
    assert client.get('/neodesk/api/chart/contract?symbol=RELIANCE&exchange=NSE').status_code==401
    assert not calls
    with client.session_transaction() as s:s.update(user='fixture',logged_in=True,broker='kotak')
    result=client.get('/neodesk/api/chart/contract?symbol=RELIANCE&exchange=NSE')
    assert result.status_code==200
    assert result.json==dict(symbol='RELIANCE',exchange='NSE',tick_size='0.01',lotsize=1,session=dict(start=555,end=930,offset=19800))
    assert calls==[('RELIANCE','NSE')]
    monkeypatch.setattr(token_db,'get_symbol_info',lambda *args:None)
    assert client.get('/neodesk/api/chart/contract?symbol=UNKNOWN&exchange=NSE').status_code==404


def test_symbol_search_requires_session_and_bounds_master_query(monkeypatch):
    from database import symbol as symbol_db
    calls=[]
    monkeypatch.setenv('NEO_SAVED_LOGIN','TRUE')
    monkeypatch.setattr(symbol_db,'enhanced_search_symbols',lambda query,exchange,limit:calls.append((query,exchange,limit)) or [SimpleNamespace(symbol='RELIANCE',exchange='NSE',name='Reliance Industries')])
    app=Flask(__name__);app.secret_key='test-only';app.register_blueprint(neo_desk_bp)
    client=app.test_client()
    assert client.get('/neodesk/api/chart/search?query=REL').status_code==401
    assert calls==[]
    with client.session_transaction() as s:s.update(user='fixture',logged_in=True,broker='kotak')
    assert client.get('/neodesk/api/chart/search?query=R').json==dict(data=[])
    assert calls==[]
    result=client.get('/neodesk/api/chart/search?query=REL&exchange=NSE')
    assert result.json['data'][0]['symbol']=='RELIANCE'
    assert calls==[('REL','NSE',60)]
    client.get('/neodesk/api/chart/search',query_string={'query':'X'*120,'exchange':'E'*30})
    assert calls[-1]==('X'*100,'E'*20,60)
    assert client.get('/neodesk/api/chart/search?query=BTC').json['data'][-1]['exchange']=='DELTA'
