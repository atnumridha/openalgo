"""Independent profit probabilities and fee-aware paper research for Delta futures.

No exchange mutations. Model inference belongs in the existing ML worker,
never a Flask request. Research probabilities are conditional on the recorded
fixed stop/target/holding policy and conservative candle-fill approximation.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.dummy import DummyClassifier
from services.crypto_fees import ContractFees, net_target_plan
from services.risk import PositionRisk, Side, evaluate_position


@dataclass(frozen=True)
class Config:
    symbol: str = "BTCUSD"
    contract_value: float = 0.001
    tick: float = 0.5
    quantity: int = 1
    leverage: int = 25
    max_risk: float = 1
    max_margin: float = 5
    max_notional: float = 1000
    net_rr: float = 3
    minimum_profit: float = 1
    slippage: float = 0.1
    hold_minutes: int = 28
    minimum_probability: float = 0.65
    maker_rate: float = 0.0002
    taker_rate: float = 0.0005
    gst_pct: float = 18
    seed: int = 43

    def contract(self):
        return ContractFees(self.symbol, maker_rate=self.maker_rate, taker_rate=self.taker_rate)


def profit_labels(long_net, short_net):
    outcomes = np.column_stack([long_net, short_net]).astype(float)
    return np.where(np.isfinite(outcomes), (outcomes > 0).astype(float), np.nan)


def select_side(probabilities, expected, minimum=0.65):
    p = np.asarray(probabilities, float)
    ev = np.asarray(expected, float)
    if p.shape != (2,) or ev.shape != (2,) or not np.isfinite(p).all() or not np.isfinite(ev).all():
        return 0
    if ((p < 0) | (p > 1)).any():
        return 0
    eligible = (p >= minimum) & (ev > 0)
    if not eligible.any():
        return 0
    return (1, -1)[int(np.argmax(np.where(eligible, ev, -np.inf)))]


def qualify(stats):
    if stats["trades"] < 100:
        return False, "Fewer than 100 non-overlapping holdout trades."
    if stats["net_usd"] <= 0 or stats["lower_expectancy"] <= 0:
        return False, "Positive net expectancy is not established."
    if stats["win_rate"] < 0.65:
        return False, "Observed holdout win rate is below 65%."
    if stats["profit_factor"] is None or stats["profit_factor"] < 1.2:
        return False, "Insufficient profit factor or loss observations."
    return (
        True,
        "Historical statistical checks passed; forward paper and exchange qualification remain required.",
    )


def exit_advice(
    *, side, entry, stop, target, price, opened_at, now, signal, streak=0, last_bar=None
):
    """Advisory exits: central hard protection, deadline, confirmed model flip.

    The opposite-side probability describes a new setup, not the value of
    holding an existing position. It is used only as a reversal indication.
    """
    if side not in (1, -1):
        raise ValueError("Known position side required")
    hard = evaluate_position(
        PositionRisk(
            side=Side.BUY if side == 1 else Side.SELL,
            entry_price=entry,
            quantity=1,
            stop_price=stop,
            target_price=target,
        ),
        price,
    )
    if hard.breached:
        return {
            "action": "EXIT",
            "reason": str(hard.reason),
            "streak": streak,
            "last_bar": last_bar,
        }
    if now - opened_at >= 28 * 60:
        return {
            "action": "EXIT",
            "reason": "holding_deadline",
            "streak": streak,
            "last_bar": last_bar,
        }
    result = {
        "action": "HOLD",
        "reason": "protection_active",
        "streak": streak,
        "last_bar": last_bar,
    }
    if not signal or not 0 <= now - float(signal.get("time", 0)) <= 90:
        return result
    bar = signal["time"]
    if last_bar is not None and bar <= last_bar:
        return result
    opposite = signal.get("side") == -side and signal.get("probability", 0) >= 0.65
    count = streak + 1 if opposite else 0
    return {
        "action": "EXIT" if count >= 2 else "HOLD",
        "reason": "confirmed_model_reversal" if count >= 2 else "protection_active",
        "streak": count,
        "last_bar": bar,
    }


def clean_bars(bars):
    frame = (
        pd.DataFrame(bars).copy().sort_values("time").drop_duplicates("time").reset_index(drop=True)
    )
    cols = ["time", "open", "high", "low", "close", "volume"]
    if not set(cols) <= set(frame) or len(frame) < 100:
        raise ValueError("At least 100 completed OHLCV candles required")
    values = frame[cols].to_numpy(float)
    if not np.isfinite(values).all() or (frame[["open", "high", "low", "close"]] <= 0).any().any():
        raise ValueError("Invalid candles")
    if (frame.high < frame[["open", "close", "low"]].max(axis=1)).any() or (
        frame.low > frame[["open", "close"]].min(axis=1)
    ).any():
        raise ValueError("Invalid candle ranges")
    return frame


def features_and_levels(frame):
    # Small causal feature set: all warmup windows fit in the live 500-bar buffer.
    close = frame.close
    change = close.diff()
    tr = pd.concat(
        [
            frame.high - frame.low,
            (frame.high - close.shift()).abs(),
            (frame.low - close.shift()).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = tr.rolling(14).mean()
    x = pd.DataFrame(index=frame.index)
    for n in (1, 3, 5, 15, 30):
        x[f"return_{n}"] = close.pct_change(n, fill_method=None)
    for n in (9, 20, 50):
        # Finite windows make training and a live window numerically identical.
        weights = np.exp(np.linspace(-4, 0, n))
        weights /= weights.sum()
        ema = close.rolling(n).apply(lambda a: float(a @ weights), raw=True)
        x[f"ema_{n}_distance"] = close / ema - 1
        x[f"ema_{n}_slope"] = ema.pct_change(3, fill_method=None)
    gain = change.clip(lower=0).rolling(14).mean()
    loss = (-change.clip(upper=0)).rolling(14).mean()
    x["rsi"] = gain / (gain + loss).replace(0, np.nan)
    x["atr_pct"] = atr / close
    x["volume_ratio"] = frame.volume / frame.volume.rolling(20).mean().replace(0, np.nan)
    x["candle_body"] = (frame.close - frame.open) / atr
    x["range_position"] = (close - frame.low.rolling(20).min()) / (
        frame.high.rolling(20).max() - frame.low.rolling(20).min()
    ).replace(0, np.nan)
    x["hour_sin"] = np.sin(frame.time % 86400 / 86400 * 2 * np.pi)
    x["hour_cos"] = np.cos(frame.time % 86400 / 86400 * 2 * np.pi)
    return x.replace([np.inf, -np.inf], np.nan), atr


def make_plan(cfg, side, entry, low, high, atr):
    buffer = max(2 * cfg.tick, 0.25 * atr)
    stop = low - buffer if side == 1 else high + buffer
    stop = (math.floor(stop / cfg.tick) if side == 1 else math.ceil(stop / cfg.tick)) * cfg.tick
    p = net_target_plan(
        side=side,
        entry=entry,
        stop=stop,
        quantity=cfg.quantity,
        contract_value=cfg.contract_value,
        tick=cfg.tick,
        contract=cfg.contract(),
        net_rr=cfg.net_rr,
        minimum_profit=cfg.minimum_profit,
        slippage=cfg.slippage,
        gst_pct=cfg.gst_pct,
    )
    notional = entry * cfg.quantity * cfg.contract_value
    p.update(notional=notional, margin=notional / cfg.leverage)
    p["fits_risk"] = (
        p["net_risk"] <= cfg.max_risk
        and p["margin"] <= cfg.max_margin
        and notional <= cfg.max_notional
    )
    return p


def paper_outcomes(frame, cfg):
    """One-bar maker wait, strict trade-through, pessimistic stop-first ties.

    OHLC cannot establish queue priority or a 15-second fill. These results
    are research estimates and never qualify exchange execution on their own.
    Full future horizons and consecutive bars are required; gaps are excluded.
    """
    n = len(frame)
    _, atr = features_and_levels(frame)
    low5 = frame.low.rolling(5).min().to_numpy()
    high5 = frame.high.rolling(5).max().to_numpy()
    o, h, l, c, t = [frame[k].to_numpy(float) for k in ("open", "high", "low", "close", "time")]
    nets = np.full((n, 2), np.nan)
    exits = np.full((n, 2), -1, int)
    holds = np.zeros((n, 2))
    filled = np.zeros((n, 2), bool)
    eligible = np.zeros((n, 2), bool)
    units = cfg.quantity * cfg.contract_value
    fees = np.full((n, 2), np.nan)
    gross = np.full((n, 2), np.nan)
    maker = cfg.maker_rate * (1 + cfg.gst_pct / 100)
    taker = cfg.taker_rate * (1 + cfg.gst_pct / 100)
    for i in range(60, n - cfg.hold_minutes - 1):
        if not np.all(np.diff(t[i - 60 : i + cfg.hold_minutes + 2]) == 60):
            continue
        # Exclude all usual 00/08/16 UTC settlement boundaries. Live qualification
        # still requires the actual product's next funding event, not this proxy.
        if int(t[i] // 28800) != int((t[i] + (cfg.hold_minutes + 1) * 60) // 28800):
            continue
        for col, side in enumerate((1, -1)):
            entry = (
                math.floor(c[i] / cfg.tick) if side == 1 else math.ceil(c[i] / cfg.tick)
            ) * cfg.tick
            try:
                p = make_plan(cfg, side, entry, low5[i], high5[i], float(atr.iloc[i]))
            except ValueError:
                continue
            if not p["fits_risk"]:
                continue
            eligible[i, col] = True
            j = i + 1
            if not (l[j] <= entry - cfg.tick if side == 1 else h[j] >= entry + cfg.tick):
                continue
            filled[i, col] = True
            end = i + cfg.hold_minutes
            price = c[end]
            target_exit = False
            for k in range(j, end + 1):
                gap = (side * (o[k] - p["stop"]) <= 0) if k > j else False
                stop_hit = l[k] <= p["stop"] if side == 1 else h[k] >= p["stop"]
                if gap or stop_hit:
                    end = k
                    price = o[k] if gap else p["stop"]
                    break
                # No target fills on the ambiguous entry candle; require trade-through.
                if k > j and (
                    h[k] >= p["target"] + cfg.tick if side == 1 else l[k] <= p["target"] - cfg.tick
                ):
                    end = k
                    price = p["target"]
                    target_exit = True
                    break
            fee = entry * units * maker + price * units * (maker if target_exit else taker)
            gross[i, col] = side * (price - entry) * units
            fees[i, col] = fee
            nets[i, col] = gross[i, col] - fee - cfg.slippage
            exits[i, col] = end
            holds[i, col] = (end - j + 1) * 60
    return {
        "net": nets,
        "exits": exits,
        "holds": holds,
        "filled": filled,
        "eligible": eligible,
        "fees": fees,
        "gross": gross,
    }


class ProfitModel:
    """One binary model per side, with disjoint train/calibration rows."""

    def __init__(self, seed=43):
        self.seed = seed

    def fit(self, X, y, cal_X, cal_y):
        self.models = []
        self.calibrators = []
        for col in range(2):
            mask = np.isfinite(y[:, col])
            target = y[mask, col].astype(int)
            if not len(target):
                raise ValueError("No filled eligible training trades for this side")
            model = (
                HistGradientBoostingClassifier(
                    max_iter=90,
                    max_leaf_nodes=15,
                    min_samples_leaf=60,
                    l2_regularization=5,
                    early_stopping=False,
                    random_state=self.seed + col,
                )
                if len(np.unique(target)) > 1
                else DummyClassifier(strategy="constant", constant=int(target[0]))
            )
            model.fit(X[mask], target)
            valid = np.isfinite(cal_y[:, col])
            calibration = None
            if valid.sum() >= 100 and len(np.unique(cal_y[valid, col])) == 2:
                calibration = IsotonicRegression(out_of_bounds="clip").fit(
                    self._positive(model, cal_X[valid]), cal_y[valid, col]
                )
            self.models.append(model)
            self.calibrators.append(calibration)
        return self

    @staticmethod
    def _positive(model, X):
        if 1 not in model.classes_:
            return np.zeros(len(X))
        return model.predict_proba(X)[:, list(model.classes_).index(1)]

    def predict_proba(self, X):
        columns = []
        for model, cal in zip(self.models, self.calibrators):
            p = self._positive(model, X)
            columns.append(cal.predict(p) if cal is not None else p)
        return np.column_stack(columns)


def statistics(rows, sides, outcome, seed=43):
    values = []
    holds = []
    indices = []
    next_free = 0
    attempted = 0
    fees = 0.0
    gross = 0.0
    for row, side in zip(rows, sides):
        if not side or row < next_free:
            continue
        col = 0 if side == 1 else 1
        if not outcome["eligible"][row, col]:
            continue
        attempted += 1
        if not np.isfinite(outcome["net"][row, col]):
            next_free = row + 1
            continue
        values.append(float(outcome["net"][row, col]))
        holds.append(float(outcome["holds"][row, col]))
        indices.append(int(row))
        fees += float(outcome["fees"][row, col])
        gross += float(outcome["gross"][row, col])
        next_free = int(outcome["exits"][row, col]) + 1
    v = np.asarray(values)
    count = len(v)
    wins = v[v > 0].sum()
    loss = -v[v <= 0].sum()
    equity = np.r_[0, np.cumsum(v)]
    peak = np.maximum.accumulate(equity)
    # Resample daily blocks of trade P&L rather than treating nearby trades as independent.
    blocks = {}
    for row, value in zip(indices, values):
        blocks.setdefault(row // 1440, []).append(value)
    b = list(blocks.values())
    lower = 0.0
    if len(b) >= 10:
        rng = np.random.default_rng(seed)
        estimates = []
        for _ in range(500):
            selected = [b[i] for i in rng.integers(0, len(b), len(b))]
            estimates.append(sum(map(sum, selected)) / sum(map(len, selected)))
        lower = float(np.quantile(estimates, 0.025))
    return {
        "trades": count,
        "net_usd": float(v.sum()),
        "net_inr": float(v.sum() * 85),
        "fees_usd": fees,
        "gross_usd": gross,
        "expectancy_usd": float(v.mean()) if count else 0,
        "lower_expectancy": lower,
        "win_rate": float((v > 0).mean()) if count else 0,
        "profit_factor": float(wins / loss) if loss else None,
        "drawdown_usd": float((peak - equity).max()),
        "median_holding_seconds": float(np.median(holds)) if count else 0,
        "maker_fill_rate": count / attempted if attempted else None,
        "attempts": attempted,
        "daily_blocks": len(b),
    }


def train_research(frame, cfg, progress=lambda s: None):
    """Train once, tune on validation only, test and serialize the same model."""
    frame = clean_bars(frame)
    n = len(frame)
    gap = cfg.hold_minutes + 61
    a = int(n * 0.55)
    b = int(n * 0.70)
    c = int(n * 0.85)
    parts = [
        np.arange(60, a - gap),
        np.arange(a, b - gap),
        np.arange(b, c - gap),
        np.arange(c, n - gap),
    ]
    if min(map(len, parts)) < 300:
        raise ValueError("More chronological history is required")
    progress("Building conservative maker-entry paper outcomes")
    outcome = paper_outcomes(frame, cfg)
    y = profit_labels(outcome["net"][:, 0], outcome["net"][:, 1])
    f, _ = features_and_levels(frame)
    medians = f.iloc[parts[0]].median().fillna(0)
    X = f.fillna(medians).to_numpy(np.float32)
    progress("Fitting separate LONG and SHORT profit models; then calibrating")
    model = ProfitModel(cfg.seed).fit(X[parts[0]], y[parts[0]], X[parts[1]], y[parts[1]])
    payoffs = []
    for col in range(2):
        v = outcome["net"][parts[1], col]
        v = v[np.isfinite(v)]
        payoffs.append(
            (
                float(v[v > 0].mean()) if (v > 0).any() else 0,
                float(-v[v <= 0].mean()) if (v <= 0).any() else 0,
            )
        )

    def decisions(rows, threshold):
        prob = model.predict_proba(X[rows])
        ev = np.column_stack(
            [prob[:, i] * payoffs[i][0] - (1 - prob[:, i]) * payoffs[i][1] for i in range(2)]
        )
        return np.array([select_side(p, e, threshold) for p, e in zip(prob, ev)]), prob

    trials = []
    for threshold in (0.65, 0.70, 0.75, 0.80):
        sides, _ = decisions(parts[2], threshold)
        score = statistics(parts[2], sides, outcome, cfg.seed)
        trials.append((threshold, score))
    viable = [t for t in trials if t[1]["trades"] >= 20 and t[1]["net_usd"] > 0]
    threshold = max(viable, key=lambda t: t[1]["net_usd"])[0] if viable else 0.80
    progress("Evaluating the exact calibrated models on the untouched final period")
    sides, prob = decisions(parts[3], threshold)
    if not viable:
        sides[:] = 0
    score = statistics(parts[3], sides, outcome, cfg.seed)
    qualified, reason = qualify(score)
    if not viable:
        qualified, reason = (
            False,
            "No probability threshold produced enough profitable validation trades.",
        )
    calibration = []
    for col in range(2):
        mask = np.isfinite(y[parts[3], col])
        truth = y[parts[3][mask], col]
        p = prob[mask, col]
        base = float(np.nanmean(y[parts[0], col]))
        brier = float(np.mean((p - truth) ** 2)) if len(truth) else None
        baseline = float(np.mean((base - truth) ** 2)) if len(truth) else None
        calibration.append(
            {
                "side": ("LONG", "SHORT")[col],
                "samples": int(len(truth)),
                "brier": brier,
                "baseline_brier": baseline,
                "calibrated": model.calibrators[col] is not None,
            }
        )
        if brier is None or brier >= baseline or model.calibrators[col] is None:
            qualified = False
            reason = "Probability estimates did not pass held-out calibration checks."
    card = {
        "config": asdict(cfg),
        "threshold": threshold,
        "test": score,
        "validation": [{"threshold": t, **s} for t, s in trials],
        "calibration": calibration,
        "research_qualified": qualified,
        "reason": reason,
        "live_ready": False,
        "probability_definition": "P(net P&L > 0 | maker filled, fixed SL/target and 28-minute policy)",
        "limits": [
            "OHLC maker fills approximate queue execution; not a 15-second fill validation.",
            "Funding-boundary exclusions assume 00/08/16 UTC; exchange schedule requires qualification.",
            "Model reversal advice is separate from the fixed-exit research results.",
        ],
        "periods": {
            name: [int(frame.time.iloc[idx[0]]), int(frame.time.iloc[idx[-1]])]
            for name, idx in zip(("train", "calibration", "validation", "test"), parts)
        },
    }
    return {
        "model": model,
        "columns": list(f.columns),
        "medians": medians.to_dict(),
        "payoffs": payoffs,
        "card": card,
    }
