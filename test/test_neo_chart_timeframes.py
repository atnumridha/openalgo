from blueprints.scalping import CHART_INTERVAL_TRADING_DAYS


def test_neo_chart_timeframes_are_not_silently_downgraded_to_one_minute():
    assert {"1m", "3m", "5m", "15m", "30m", "1h", "1d"}.issubset(CHART_INTERVAL_TRADING_DAYS)
