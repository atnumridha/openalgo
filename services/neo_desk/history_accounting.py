"""Preserved conservative FIFO accounting; no broker or persistence dependencies."""

import csv
import io
import json
from collections import defaultdict, deque
from collections.abc import Mapping
from datetime import UTC, datetime, time
from decimal import Decimal, InvalidOperation, localcontext
from zoneinfo import ZoneInfo

MAX_BYTES = 5 * 1024 * 1024
MAX_ROWS = 10_000
IST = ZoneInfo("Asia/Kolkata")
ALIASES = {
    "fill_id": ("fill_id", "trade_id", "flId"),
    "order_id": ("order_id", "nOrdNo"),
    "symbol": ("symbol", "trdSym"),
    "exchange": ("exchange", "exSeg"),
    "product": ("product", "prod"),
    "side": ("side", "trnsTp"),
    "quantity": ("quantity", "fldQty"),
    "price": ("price", "avgPrc"),
    "time": ("time", "broker_time", "exTm"),
    "fees": ("fees",),
}
IMMUTABLE = ("order_id", "symbol", "exchange", "product", "side", "quantity", "price", "time")


def _text(value, label):
    value = str(value or "").strip()
    if not value or len(value) > 120 or any(ord(c) < 32 for c in value):
        raise ValueError(f"invalid {label}")
    return value


def _number(value, label, minimum=Decimal(0)):
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number < minimum or number > Decimal("1e12"):
            raise ValueError(f"invalid {label}")
        if number.as_tuple().exponent < -12:
            raise ValueError(f"too much precision in {label}")
        return number
    except (InvalidOperation, TypeError) as error:
        raise ValueError(f"invalid {label}") from error


def _decimal(number):
    value = format(number, "f")
    return value.rstrip("0").rstrip(".") if "." in value else value


def _timestamp(value):
    if isinstance(value, datetime):
        parsed = value
    else:
        value = str(value or "").strip()
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            parsed = None
            for pattern in (
                "%d-%b-%Y %H:%M:%S",
                "%d/%m/%Y %H:%M:%S",
                "%d-%m-%Y %H:%M:%S",
                "%d %b %Y %H:%M:%S",
            ):
                try:
                    parsed = datetime.strptime(value, pattern)
                    break
                except ValueError:
                    continue
            if parsed is None:
                raise ValueError("invalid time: full date and time required") from None
        if len(value) <= 10:
            raise ValueError("invalid time: full date and time required")
    return (
        parsed.replace(tzinfo=IST).astimezone(UTC).isoformat()
        if parsed.tzinfo is None
        else parsed.astimezone(UTC).isoformat()
    )


def _trade_date(value):
    return datetime.fromisoformat(_timestamp(value)).astimezone(IST).date().isoformat()


def _date_bounds(start, end):
    def boundary(value, upper=False):
        if value is None or value == "":
            return None
        if isinstance(value, str) and len(value) == 10:
            try:
                return _timestamp(
                    datetime.combine(
                        datetime.fromisoformat(value).date(),
                        time.max if upper else time.min,
                        IST,
                    )
                )
            except ValueError:
                raise ValueError("invalid date filter") from None
        return _timestamp(value)

    lower, upper = boundary(start), boundary(end, True)
    if lower and upper and lower > upper:
        raise ValueError("start must precede end")
    return lower, upper


def _normalized(row, actual_fees):
    if not isinstance(row, Mapping):
        raise ValueError("fill must be an object")
    result = {}
    for field, aliases in ALIASES.items():
        values = [row[name] for name in aliases if name in row and row[name] not in (None, "")]
        if len({str(v).strip() for v in values}) > 1:
            raise ValueError(f"contradictory aliases for {field}")
        result[field] = values[0] if values else None
    if result["time"] is None and row.get("flDt") and row.get("flTm"):
        result["time"] = f"{row['flDt']} {row['flTm']}"
    for field in ("fill_id", "order_id", "symbol", "exchange", "product"):
        result[field] = _text(result[field], field)
    result["side"] = {"B": "BUY", "S": "SELL", "BUY": "BUY", "SELL": "SELL"}.get(
        str(result["side"]).upper()
    )
    if result["side"] is None:
        raise ValueError("invalid side")
    quantity = _number(result["quantity"], "quantity", Decimal(1))
    if quantity != quantity.to_integral_value() or quantity > 1_000_000_000:
        raise ValueError("invalid quantity")
    result["quantity"] = int(quantity)
    result["price"] = _decimal(_number(result["price"], "price", Decimal("0.000000000001")))
    result["time"] = _timestamp(result["time"])
    result["trade_date"] = _trade_date(result["time"])
    result["fees"] = (
        _decimal(_number(result["fees"], "fees"))
        if actual_fees and result["fees"] is not None
        else None
    )
    return result


class TradeArchive:
    @staticmethod
    def _match(fills):
        with localcontext() as context:
            context.prec = 64
            return TradeArchive._match_fifo(fills)

    @staticmethod
    def _match_fifo(fills):
        # IDs only stabilize display; they do not establish execution sequence.
        # Different economics at the same timestamp make FIFO pairing provisional.
        groups = defaultdict(set)
        for row in fills:
            group = (row["exchange"], row["symbol"], row["product"], row["time"])
            fee_rate = Decimal(row["fees"]) / row["quantity"] if row["fees"] is not None else None
            groups[group].add((row["side"], row["price"], fee_rate))
        ambiguous_groups = {group for group, economics in groups.items() if len(economics) > 1}
        inventory, matches = defaultdict(deque), []
        for fill in fills:
            key = (fill["exchange"], fill["symbol"], fill["product"])
            queue = inventory[key]
            remaining = fill["quantity"]
            fill_ambiguous = (*key, fill["time"]) in ambiguous_groups
            # A flat SELL may close older unrecorded holdings. Only a reversal of
            # tracked long inventory or extension of a tracked short is resolved.
            opening_unresolved = fill["side"] == "SELL" and (
                not queue or any(lot["unresolved"] for lot in queue)
            )
            while remaining and queue and queue[0]["fill"]["side"] != fill["side"]:
                lot = queue[0]
                entry = lot["fill"]
                quantity = min(remaining, lot["remaining"])
                gross = (
                    (Decimal(fill["price"]) - Decimal(entry["price"]))
                    * quantity
                    * (1 if entry["side"] == "BUY" else -1)
                )
                known = entry["fees"] is not None and fill["fees"] is not None
                fees = (
                    (
                        Decimal(entry["fees"]) * quantity / entry["quantity"]
                        + Decimal(fill["fees"]) * quantity / fill["quantity"]
                    )
                    if known
                    else None
                )
                unresolved = lot["unresolved"]
                ambiguous = lot["ambiguous"] or fill_ambiguous
                matches.append(
                    {
                        "trade_id": json.dumps(
                            [
                                entry["exchange"],
                                entry["trade_date"],
                                entry["fill_id"],
                                fill["trade_date"],
                                fill["fill_id"],
                            ],
                            separators=(",", ":"),
                        ),
                        "symbol": fill["symbol"],
                        "exchange": fill["exchange"],
                        "product": fill["product"],
                        "side": "long" if entry["side"] == "BUY" else "short",
                        "quantity": quantity,
                        "entry_side": entry["side"],
                        "exit_side": fill["side"],
                        "entry_time": entry["time"],
                        "exit_time": fill["time"],
                        "entry_price": entry["price"],
                        "exit_price": fill["price"],
                        "entry_trade_date": entry["trade_date"],
                        "exit_trade_date": fill["trade_date"],
                        "entry_fill_id": entry["fill_id"],
                        "exit_fill_id": fill["fill_id"],
                        "gross_pnl": None if unresolved or ambiguous else _decimal(gross),
                        "fees": _decimal(fees) if known and not ambiguous else None,
                        "net_pnl": _decimal(gross - fees)
                        if known and not unresolved and not ambiguous
                        else None,
                        "fees_source": "broker_report_allocated"
                        if known and not ambiguous
                        else "unavailable",
                        "fee_coverage": "ambiguous_allocation"
                        if ambiguous
                        else "complete"
                        if known
                        else "partial"
                        if entry["fees"] is not None or fill["fees"] is not None
                        else "unavailable",
                        "fees_allocation": "proportional_fill_quantity"
                        if known and not ambiguous
                        else None,
                        "status": "ambiguous_execution_order"
                        if ambiguous
                        else "unresolved_opening_inventory"
                        if unresolved
                        else "closed"
                        if quantity == lot["remaining"]
                        else "partial_close",
                        "provenance": {"entry": entry["provenance"], "exit": fill["provenance"]},
                    }
                )
                remaining -= quantity
                lot["remaining"] -= quantity
                if not lot["remaining"]:
                    queue.popleft()
            if remaining:
                queue.append(
                    {
                        "fill": fill,
                        "remaining": remaining,
                        "unresolved": opening_unresolved,
                        "ambiguous": fill_ambiguous,
                    }
                )
        opens = [
            {
                "symbol": lot["fill"]["symbol"],
                "exchange": lot["fill"]["exchange"],
                "product": lot["fill"]["product"],
                "side": lot["fill"]["side"],
                "quantity": lot["remaining"],
                "entry_time": lot["fill"]["time"],
                "entry_price": lot["fill"]["price"],
                "status": "ambiguous_execution_order"
                if lot["ambiguous"]
                else "unresolved_opening_inventory"
                if lot["unresolved"]
                else "open",
                "fill_id": lot["fill"]["fill_id"],
                "trade_date": lot["fill"]["trade_date"],
            }
            for queue in inventory.values()
            for lot in queue
        ]
        return matches, opens

    def page(self, offset=0, limit=50, symbol="", start=None, end=None):
        if (
            not isinstance(offset, int)
            or offset < 0
            or not isinstance(limit, int)
            or not 1 <= limit <= 500
        ):
            raise ValueError("invalid pagination: limit must be 1..500")

        lower, upper = _date_bounds(start, end)
        fills = self.fills()
        matches, opens = self._match(fills)
        filtered = [
            row
            for row in matches
            if (not symbol or row["symbol"] == symbol)
            and (not lower or row["exit_time"] >= lower)
            and (not upper or row["exit_time"] <= upper)
        ]
        filtered_fills = [
            row
            for row in fills
            if (not symbol or row["symbol"] == symbol)
            and (not lower or row["time"] >= lower)
            and (not upper or row["time"] <= upper)
        ]

        def total_amount(records, field):
            with localcontext() as context:
                context.prec = 64
                return _decimal(
                    sum(
                        (Decimal(row[field]) for row in records if row[field] is not None),
                        Decimal(0),
                    )
                )

        known_net = sum(row["net_pnl"] is not None for row in filtered)
        summary = {
            "gross_pnl": total_amount(filtered, "gross_pnl"),
            "gross_known_count": sum(row["gross_pnl"] is not None for row in filtered),
            "closed_count": len(filtered),
            "fees": total_amount(filtered_fills, "fees"),
            "fees_known_fill_count": sum(row["fees"] is not None for row in filtered_fills),
            "fill_count": len(filtered_fills),
            "fees_scope": "actual charges on filtered fills, including open inventory",
            "allocated_trade_fees": total_amount(filtered, "fees"),
            "net_pnl": total_amount(filtered, "net_pnl") if known_net == len(filtered) else None,
            "net_known_pnl": total_amount(filtered, "net_pnl"),
            "net_known_count": known_net,
        }
        coverage = {
            "lifetime_complete": False,
            "fill_count": len(fills),
            "first_fill_time": fills[0]["time"] if fills else None,
            "last_fill_time": fills[-1]["time"] if fills else None,
            "recorded_dates": sorted(
                {
                    datetime.fromisoformat(row["time"]).astimezone(IST).date().isoformat()
                    for row in fills
                }
            ),
            "fees_known_fill_count": sum(row["fees"] is not None for row in fills),
            "note": (
                "Recorded broker fills and imports only. Date coverage does not establish "
                "complete lifetime history or opening inventory."
            ),
        }
        return {
            "rows": filtered[offset : offset + limit],
            "summary": summary,
            "symbols": sorted({row["symbol"] for row in fills}),
            "total": len(filtered),
            "offset": offset,
            "limit": limit,
            "coverage": coverage,
            "open_inventory": [row for row in opens if not symbol or row["symbol"] == symbol],
            "source": "Kotak Neo broker archive",
            "accounting": (
                "FIFO by exchange, symbol and product; actual fill fees allocated by quantity"
            ),
        }

    def export_csv(self, symbol="", start=None, end=None):
        lower, upper = _date_bounds(start, end)
        rows, _ = self._match(self.fills())
        output = io.StringIO()
        fields = [
            "trade_id",
            "symbol",
            "exchange",
            "product",
            "side",
            "quantity",
            "entry_time",
            "exit_time",
            "entry_trade_date",
            "exit_trade_date",
            "entry_price",
            "exit_price",
            "gross_pnl",
            "fees",
            "net_pnl",
            "fees_source",
            "fee_coverage",
            "fees_allocation",
            "status",
            "provenance",
            "lifetime_complete",
        ]
        writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            if (
                (symbol and row["symbol"] != symbol)
                or (lower and row["exit_time"] < lower)
                or (upper and row["exit_time"] > upper)
            ):
                continue
            record = dict(row, provenance=json.dumps(row["provenance"]), lifetime_complete=False)
            for field in ("trade_id", "symbol", "exchange", "product"):
                if record[field].startswith(("=", "+", "-", "@")):
                    record[field] = "'" + record[field]
            writer.writerow(record)
        return output.getvalue()
