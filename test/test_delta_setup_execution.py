from decimal import Decimal as D
from services.delta_chart.strategy_ensemble import _action,_setup
from test_delta_strategy_ensemble import bars,account,SETTINGS

def test_structural_stop_has_volatility_room_not_one_tick_only():
 b=bars();c=_setup('breakout_retest',True,b,D(98),300);c['atr']=D(4)
 a=_action(account(D(100)),SETTINGS,c)
 assert D(str(a['auto_protection']['stop'])) <= D(96)
 assert a['setup_id'] and a['setup_time']==b[-1]['time']

def test_short_mirrors_buffer_and_noise_floor():
 b=bars();c=_setup('breakout_retest',False,b,D(102),300);c['atr']=D(4)
 a=_action(account(D(100),True),SETTINGS,c)
 assert D(str(a['auto_protection']['stop'])) >= D(104)
