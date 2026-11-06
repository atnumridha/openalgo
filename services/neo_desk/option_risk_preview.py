"""Read-only long-option chart planning; never changes protection or sends orders."""
from datetime import datetime
from decimal import Decimal as D, InvalidOperation

from services.neo_desk.fees import FeePlan, estimate_charges
from services.neo_desk.types import IST
from services.risk.option_costs import money


def decimal(value, name):
    try:
        result = D(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"Enter a valid {name}.") from None
    if not result.is_finite():
        raise ValueError(f"Enter a valid {name}.")
    return result


def option_risk_preview(body, contract, day=None):
    if not isinstance(body, dict) or set(body) - {"symbol", "exchange", "entry", "stop", "lots", "slippage", "broker", "target", "position"}:
        raise ValueError("Unexpected preview fields.")
    position = body.get('position', False)
    if not (isinstance(position, bool) or isinstance(position, str) and position in ('true', 'false')):
        raise ValueError('Invalid position valuation flag.')
    position = position is True or position == 'true'
    broker = body.get('broker', 'kotak')
    if broker not in ('kotak', 'flattrade'):
        raise ValueError('Choose a verified Kotak or Flattrade fee profile.')
    if (not contract or contract.exchange not in ("NFO", "BFO")
        or not contract.symbol.endswith(("CE", "PE"))
        or body.get("symbol") != contract.symbol or body.get("exchange") != contract.exchange):
        raise ValueError("Select an exact listed CE or PE contract.")
    lot = decimal(contract.lotsize, "contract lot size")
    tick = decimal(contract.tick_size, "contract tick size")
    if lot <= 0 or lot != lot.to_integral_value() or tick <= 0:
        raise ValueError("Contract lot size or tick size is unavailable.")
    lots = decimal(body.get("lots"), "whole number of lots")
    if isinstance(body.get("lots"), bool) or lots != lots.to_integral_value() or not 1 <= lots <= 10000:
        raise ValueError("Choose 1 to 10,000 whole lots.")
    entry, stop = decimal(body.get("entry"), "entry"), decimal(body.get("stop"), "SL")
    slip = decimal(body.get("slippage", "0"), "exit slippage")
    if not (0 < stop <= 1000000 and 0 < entry <= 1000000 and (position or stop < entry)) or not 0 <= slip < stop:
        raise ValueError("SL must be positive and below entry; exit slippage must be below SL.")
    if any(value % tick for value in (entry, stop, slip)):
        raise ValueError(f"Prices must follow the contract's ₹{tick} tick size.")
    day = day or datetime.now(IST).date()
    if not "2026-04-01" <= day.isoformat() <= "2026-12-31":
        raise ValueError("A verified fee schedule is unavailable for this date.")
    quantity = int(lots * lot)
    target = decimal(body['target'], 'target') if 'target' in body else entry + 2 * (entry - stop)
    if not entry < target <= 1000000 or target % tick:
        raise ValueError('Target must be above entry and follow the contract tick size.')

    def scenario(exit):
        if broker == 'flattrade':
            from services.neo_desk.flattrade_fees import flattrade_option_fees
            fees = flattrade_option_fees(entry, exit, quantity, contract.exchange)
            return fees, money((exit-entry)*quantity - D(fees['total']))
        fills = [dict(fill_id=side, order_id=side, symbol=contract.symbol,
                      exchange=contract.exchange, side=side, quantity=quantity,
                      price=str(price), trade_date=day.isoformat())
                 for side, price in (("BUY", entry), ("SELL", exit))]
        fees = estimate_charges(fills, plan=FeePlan(brokerage=None))
        return fees, money((exit-entry)*quantity - D(fees["total"]))

    profit_fees, net_profit = scenario(target-slip)
    loss_fees, stop_pnl = scenario(stop-slip)
    loss = -stop_pnl
    from services.kotak_assistant.analysis import account_brokerage

    return dict(symbol=contract.symbol, exchange=contract.exchange, quantity=quantity,
                lots=int(lots), lot_size=int(lot), tick_size=str(tick), entry=str(money(entry)),
                stop=str(money(stop)), target=str(money(target)), gross_reward_risk=str(money((target-entry)/(entry-stop))) if stop < entry else None,
                net_profit=str(net_profit), net_loss=str(loss),
                net_reward_risk=str(money(net_profit/loss)) if loss > 0 else None, net_at_stop=str(stop_pnl),
                profit_fees=profit_fees["total"], loss_fees=loss_fees["total"],
                profit_fee_breakdown=profit_fees["breakdown"],
                loss_fee_breakdown=loss_fees["breakdown"],
                slippage=str(money(slip)), broker=broker,
                brokerage_per_order='0.00' if broker == 'flattrade' else str(money(account_brokerage(day.isoformat()))),
                fee_source=profit_fees["source"], fee_version=profit_fees["version"],
                fee_date=day.isoformat(), estimated=True)
