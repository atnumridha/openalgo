from dataclasses import replace
import pytest
from test_ledger import NOW,connections,snapshot


def test_combined_net_keeps_realized_and_estimated_open_separate():
    from services.combined_terminal.aggregate import aggregate
    a,b=connections()
    result=aggregate([replace(snapshot(a,pnl=100),estimated_open_net=20),
                      replace(snapshot(b,pnl=-30),estimated_open_net=5)],{},NOW)
    assert result['summary']['realized_net']==70
    assert result['summary']['estimated_open_net']==25
    assert result['summary']['estimated_total_net']==95


def test_missing_or_stale_worker_does_not_become_zero():
    from services.combined_terminal.aggregate import aggregate
    a,b=connections()
    result=aggregate([snapshot(a,pnl=100),replace(snapshot(b),books_complete=False,error='Unavailable')],{},NOW)
    assert result['summary']['realized_net'] is None
    assert result['summary']['partial_realized_net']==100
    assert result['connections'][1]['entry_ready'] is False
    result=aggregate([snapshot(a),snapshot(b,at=NOW-11)],{},NOW)
    assert result['summary']['estimated_total_net'] is None


def test_mixed_live_and_paper_cannot_be_summed():
    from services.combined_terminal.aggregate import aggregate
    a,b=connections()
    with pytest.raises(ValueError):aggregate([snapshot(a,pnl=100),snapshot(replace(b,mode='analyze'),pnl=100)],{},NOW)


def test_unavailable_funds_block_entry_without_hiding_positions():
    from services.combined_terminal.aggregate import aggregate
    a=connections()[0]
    p={'symbol':'NIFTY','exchange':'NFO','product':'MIS','quantity':65,'ltp':101}
    s=replace(snapshot(a),funds=None,positions=[p])
    result=aggregate([s],{},NOW)
    assert result['connections'][0]['entry_ready'] is False
    assert result['positions'][0]['quantity']==65


def test_managed_trade_ids_keep_broker_ownership_and_do_not_double_count_positions():
    from services.combined_terminal.aggregate import aggregate
    a,b=connections()
    trade={'id':'same','symbol':'NIFTY','exchange':'NFO','product':'MIS','remaining':65,
           'status':'open','quote':{'ltp':101,'time':NOW}}
    pos={'symbol':'NIFTY','exchange':'NFO','product':'MIS','quantity':65,'ltp':101}
    sa=replace(snapshot(a),positions=[pos],managed_trades=[trade])
    sb=replace(snapshot(b),positions=[pos],managed_trades=[trade])
    result=aggregate([sa,sb],{},NOW)
    assert len(result['positions'])==2
    assert result['positions'][0]['trade_id']!=result['positions'][1]['trade_id']
    assert {p['broker'] for p in result['positions']}=={'kotak','flattrade'}


def test_duplicate_account_cannot_double_combined_pnl():
    from services.combined_terminal.aggregate import aggregate
    s=snapshot(connections()[0],pnl=100)
    with pytest.raises(ValueError):aggregate([s,s],{},NOW)


def test_each_account_summary_matches_combined_pnl_and_deduplicated_daily_entries():
    from services.combined_terminal.aggregate import aggregate
    from test_ledger import buy
    a,b=connections()
    fills=[buy('one','f1'),buy('one','f2'),buy('old',epoch=NOW-86400)]
    position={'symbol':'NIFTY','exchange':'NFO','product':'MIS','quantity':65,'ltp':101}
    orders=[{'orderid':'pending','order_status':'open'},{'orderid':'done','order_status':'complete'}]
    result=aggregate([replace(snapshot(a,pnl=100,fills=fills,orders=orders),estimated_open_net=20,positions=[position]),replace(snapshot(b,pnl=-30),estimated_open_net=5)],{},NOW)
    first,second=result['connections']
    assert first['estimated_total_net']==120 and second['estimated_total_net']==-25
    assert first['open_positions']==1 and first['pending_orders']==1 and first['filled_entries']==1
    assert sum(c['estimated_total_net'] for c in result['connections'])==result['summary']['estimated_total_net']


def test_stale_account_summary_is_unavailable_without_erasing_healthy_account():
    from services.combined_terminal.aggregate import aggregate
    a,b=connections()
    result=aggregate([snapshot(a,pnl=100),snapshot(b,pnl=200,at=NOW-11)],{},NOW)
    assert result['connections'][0]['estimated_total_net']==100
    assert result['connections'][1]['estimated_total_net'] is None
    assert result['connections'][1]['filled_entries'] is None
    assert result['summary']['estimated_total_net'] is None
