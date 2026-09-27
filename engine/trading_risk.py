"""Trading-risk analytics layered onto Financial AI.

Uses historical market data to estimate empirical stop-hit probability,
expected downside, expectancy, and a risk-budget-aware position size.
This is a research heuristic, not a guarantee of future performance.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .stock import ticker_for
from .market_data import history as market_history
from .position_sizing import calculate_position_size
from .technical import atr as canonical_atr, price_zones, realized_volatility
from config import STOCK_PERIOD


def _finite(value: Any) -> float | None:
    try:
        v = float(value)
        return v if np.isfinite(v) else None
    except Exception:
        return None


def _atr(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    return canonical_atr(frame, period)


def _first_touch_stats(frame: pd.DataFrame, stop_pct: float, target_pct: float,
                       horizon: int = 20, side: str = "long") -> dict[str, float | int | None]:
    """Estimate first-touch probabilities from historical daily bars.

    Same-bar stop/target collisions are treated conservatively as stop-first.
    Unresolved trades are excluded from win/loss probability but reported via
    resolved_rate.
    """
    highs = frame["High"].to_numpy(dtype=float)
    lows = frame["Low"].to_numpy(dtype=float)
    closes = frame["Close"].to_numpy(dtype=float)
    total = max(0, len(frame) - horizon - 1)
    if total <= 20:
        return {"win_probability": None, "loss_probability": None, "resolved_rate": None,
                "sample_size": total}
    wins = losses = unresolved = 0
    long_side = side == "long"
    for i in range(total):
        entry = closes[i]
        if long_side:
            stop = entry * (1.0 - stop_pct)
            target = entry * (1.0 + target_pct)
        else:
            stop = entry * (1.0 + stop_pct)
            target = entry * (1.0 - target_pct)
        outcome = None
        for j in range(i + 1, min(i + horizon + 1, len(frame))):
            if long_side:
                if lows[j] <= stop:
                    outcome = "loss"
                    break
                if highs[j] >= target:
                    outcome = "win"
                    break
            else:
                if highs[j] >= stop:
                    outcome = "loss"
                    break
                if lows[j] <= target:
                    outcome = "win"
                    break
        if outcome == "win":
            wins += 1
        elif outcome == "loss":
            losses += 1
        else:
            unresolved += 1
    resolved = wins + losses
    if resolved == 0:
        return {"win_probability": None, "loss_probability": None,
                "resolved_rate": 0.0, "sample_size": total}
    return {
        "win_probability": wins / resolved,
        "loss_probability": losses / resolved,
        "resolved_rate": resolved / total,
        "sample_size": total,
    }


def _forward_mae_percent(frame: pd.DataFrame, horizon: int = 20, side: str = "long") -> np.ndarray:
    close = frame["Close"].to_numpy(dtype=float)
    low = frame["Low"].to_numpy(dtype=float)
    high = frame["High"].to_numpy(dtype=float)
    n = len(frame)
    out = []
    for i in range(max(0, n - horizon - 1)):
        entry = close[i]
        if entry <= 0:
            continue
        end = min(n, i + horizon + 1)
        if side == "long":
            mae = max(0.0, (entry - np.min(low[i + 1:end])) / entry)
        else:
            mae = max(0.0, (np.max(high[i + 1:end]) - entry) / entry)
        out.append(mae)
    return np.asarray(out, dtype=float)


def _peak_to_trough_drawdowns(close: pd.Series) -> np.ndarray:
    """Peak-to-trough drawdown episode depths as positive percentages."""
    running_peak = close.cummax()
    dd = (running_peak - close) / running_peak
    arr = dd.to_numpy(dtype=float)
    episodes: list[float] = []
    active = 0.0
    for value in arr:
        if value > 0:
            active = max(active, float(value))
        elif active > 0:
            episodes.append(active)
            active = 0.0
    if active > 0:
        episodes.append(active)
    return np.asarray(episodes, dtype=float)


def _candidate_distances(price: float, atr_value: float | None,
                         peak_trough_pctl: float | None,
                         mae_pctl: float | None) -> list[tuple[str, float]]:
    candidates: list[tuple[str, float]] = []
    if atr_value is not None and price > 0:
        atr_pct = atr_value / price
        for mult in (1.0, 1.5, 2.0, 2.5):
            candidates.append((f"{mult:.1f}× ATR14", atr_pct * mult))
    if mae_pctl is not None:
        candidates.append(("Historical forward MAE (80th pct)", mae_pctl))
    if peak_trough_pctl is not None:
        candidates.append(("Peak-to-trough drawdown (75th pct)", peak_trough_pctl))
    clean = [(label, float(pct)) for label, pct in candidates
             if 0.0025 <= pct <= 0.25 and np.isfinite(pct)]
    out: list[tuple[str, float]] = []
    for label, pct in sorted(clean, key=lambda x: x[1]):
        if not out or abs(pct - out[-1][1]) > 0.002:
            out.append((label, pct))
    return out


def _realized_volatility(close: pd.Series) -> dict[str, float | None]:
    return realized_volatility(close, (20, 60))


def _shrunk_win_probability(*samples: dict[str, float | int | None]) -> dict[str, float | int | None]:
    """Blend resolved train/holdout paths and shrink thin evidence to 50%."""
    estimated_wins = 0.0
    resolved_paths = 0.0
    for sample in samples:
        probability = _finite(sample.get("win_probability"))
        total = _finite(sample.get("sample_size"))
        resolved_rate = _finite(sample.get("resolved_rate"))
        if probability is None or total is None or resolved_rate is None:
            continue
        resolved = max(0.0, total * resolved_rate)
        estimated_wins += probability * resolved
        resolved_paths += resolved
    if resolved_paths <= 0:
        return {"probability": None, "resolved_paths": 0, "prior_paths": 20}
    prior_paths = 20.0
    probability = (estimated_wins + prior_paths * 0.50) / (resolved_paths + prior_paths)
    return {
        "probability": float(max(0.0, min(1.0, probability))),
        "resolved_paths": int(round(resolved_paths)),
        "prior_paths": int(prior_paths),
    }


def _position_size_for_method(
    method: str,
    *,
    account_equity: float | None,
    entry_price: float,
    stop_price: float,
    requested_risk_pct: float,
    target_r_multiple: float,
    win_probability: float | None,
    resolved_paths: int = 100,
    lot_size: int = 1,
) -> dict[str, Any]:
    """Calculate one cash-only sizing method without introducing leverage."""
    return calculate_position_size(
        method if method in {"fixed-fractional", "kelly", "half-kelly"} else "fixed-fractional",
        account_equity=account_equity,
        entry_price=entry_price,
        stop_price=stop_price,
        requested_risk_pct=requested_risk_pct,
        target_r_multiple=target_r_multiple,
        win_probability=win_probability,
        resolved_paths=resolved_paths,
        lot_size=lot_size,
    )


def analyze_trading_risk(company: str, entry_price: float | None = None,
                         account_equity: float | None = None, risk_pct: float = 1.0,
                         target_r_multiple: float = 2.0, horizon: int = 20,
                         side: str = "long", lookback_days: int = 756,
                         sizing_method: str = "fixed-fractional") -> dict[str, Any]:
    """Return an empirical trading-risk plan and stop-loss recommendation."""
    ticker = ticker_for(company)
    side = (side or "long").lower().strip()
    if side not in {"long", "short"}:
        side = "long"
    try:
        frame = market_history(ticker, period=STOCK_PERIOD, interval="1d", auto_adjust=False)
        if frame.empty:
            return {"status": "No market data available.", "ticker": ticker}
        frame = frame.dropna(subset=["High", "Low", "Close"]).tail(lookback_days).copy()
        if len(frame) < 120:
            return {"status": "Not enough market history for a reliable trading-risk estimate.",
                    "ticker": ticker, "data_points": len(frame)}

        close = frame["Close"].astype(float)
        current_price = _finite(close.iloc[-1])
        if current_price is None or current_price <= 0:
            return {"status": "Market price unavailable.", "ticker": ticker}
        try:
            entry = float(entry_price) if entry_price and float(entry_price) > 0 else current_price
        except Exception:
            entry = current_price
        try:
            account = float(account_equity) if account_equity and float(account_equity) > 0 else None
        except Exception:
            account = None
        try:
            risk_pct = max(0.05, min(float(risk_pct), 10.0))
        except Exception:
            risk_pct = 1.0
        try:
            target_r_multiple = max(1.0, min(float(target_r_multiple), 5.0))
        except Exception:
            target_r_multiple = 2.0
        try:
            horizon = max(5, min(int(horizon), 60))
        except Exception:
            horizon = 20
        sizing_method = str(sizing_method or "fixed-fractional").strip().lower()
        if sizing_method not in {"fixed-fractional", "kelly", "half-kelly"}:
            sizing_method = "fixed-fractional"

        atr_val = _finite(_atr(frame, 14).iloc[-1])
        drawdowns = _peak_to_trough_drawdowns(close)
        mae = _forward_mae_percent(frame, horizon=horizon, side=side)
        dd75 = float(np.quantile(drawdowns, 0.75)) if len(drawdowns) else None
        mae80 = float(np.quantile(mae, 0.80)) if len(mae) else None
        atr_pct = (atr_val / current_price) if atr_val else None
        volatility = _realized_volatility(close)

        zones = price_zones(close, (20, 60))
        support20 = float(zones["support20"])
        resistance20 = float(zones["resistance20"])
        support60 = float(zones["support60"])
        resistance60 = float(zones["resistance60"])
        candidates = _candidate_distances(current_price, atr_val, dd75, mae80)
        if not candidates:
            return {"status": "Unable to build a stop-loss range from available market history.", "ticker": ticker}

        split = max(60, int(len(frame) * 0.80))
        train = frame.iloc[:split].copy()
        scored = []
        for label, stop_pct in candidates:
            stats = _first_touch_stats(train, stop_pct, stop_pct * target_r_multiple,
                                       horizon=horizon, side=side)
            if stats["win_probability"] is None:
                continue
            p_win = float(stats["win_probability"])
            p_loss = float(stats["loss_probability"])
            expectancy = p_win * (stop_pct * target_r_multiple) - p_loss * stop_pct
            scored.append((expectancy, label, stop_pct, stats))
        if not scored:
            label, stop_pct = candidates[min(len(candidates) - 1, 1)]
            stats = _first_touch_stats(train, stop_pct, stop_pct * target_r_multiple,
                                       horizon=horizon, side=side)
            expectancy = None
        else:
            scored.sort(key=lambda x: (x[0], -x[2]), reverse=True)
            expectancy, label, stop_pct, stats = scored[0]

        # Structural reference: give recent support/resistance a chance to win if it
        # preserves most of the empirical expectancy and is not tighter than 0.8 ATR.
        buffer = 0.005
        if side == "long":
            structural_distance = max(0.0, (entry - support20 * (1 - buffer)) / entry)
        else:
            structural_distance = max(0.0, (resistance20 * (1 + buffer) - entry) / entry)
        if 0.0025 <= structural_distance <= 0.25 and atr_pct and structural_distance >= 0.8 * atr_pct:
            ss = _first_touch_stats(train, structural_distance,
                                    structural_distance * target_r_multiple,
                                    horizon=horizon, side=side)
            if ss["win_probability"] is not None:
                structural_exp = (float(ss["win_probability"]) * structural_distance * target_r_multiple
                                  - float(ss["loss_probability"]) * structural_distance)
                if expectancy is None or structural_exp >= expectancy * 0.90:
                    label, stop_pct, stats, expectancy = (
                        "Recent support/resistance + volatility buffer", structural_distance, ss, structural_exp
                    )

        if side == "long":
            stop_price = entry * (1 - stop_pct)
            target_price = entry * (1 + stop_pct * target_r_multiple)
        else:
            stop_price = entry * (1 + stop_pct)
            target_price = entry * (1 - stop_pct * target_r_multiple)

        per_unit_risk = abs(entry - stop_price)
        p_loss = float(stats["loss_probability"]) if stats.get("loss_probability") is not None else None
        p_win = float(stats["win_probability"]) if stats.get("win_probability") is not None else None
        holdout = _first_touch_stats(frame.iloc[split:].copy(), stop_pct,
                                     stop_pct * target_r_multiple, horizon=horizon, side=side)
        sizing_probability = _shrunk_win_probability(stats, holdout)
        sizing = _position_size_for_method(
            sizing_method,
            account_equity=account,
            entry_price=entry,
            stop_price=stop_price,
            requested_risk_pct=risk_pct,
            target_r_multiple=target_r_multiple,
            win_probability=_finite(sizing_probability.get("probability")),
            resolved_paths=int(sizing_probability.get("resolved_paths") or 0),
            lot_size=100 if ticker.endswith(".VN") else 1,
        )
        risk_budget = _finite(sizing.get("planned_loss_amount"))
        position_units = _finite(sizing.get("position_units"))
        position_value = _finite(sizing.get("position_value"))
        expected_loss_pct = p_loss * stop_pct if p_loss is not None else None
        expected_gain_pct = p_win * stop_pct * target_r_multiple if p_win is not None else None
        expected_loss_money = position_value * expected_loss_pct if position_value and expected_loss_pct is not None else None
        expected_gain_money = position_value * expected_gain_pct if position_value and expected_gain_pct is not None else None

        return {
            "status": "ok", "ticker": ticker, "side": side, "data_points": len(frame),
            "current_price": current_price, "entry_price": entry, "horizon_days": horizon,
            "atr14": atr_val, "atr14_pct": atr_pct * 100 if atr_pct is not None else None,
            "peak_to_trough": {"p75": dd75 * 100 if dd75 is not None else None,
                                "max": float(drawdowns.max() * 100) if len(drawdowns) else None,
                                "episodes": int(len(drawdowns))},
            "forward_mae": {"p80": mae80 * 100 if mae80 is not None else None},
            "reference_zones": {"support20": support20, "support60": support60,
                                "resistance20": resistance20, "resistance60": resistance60},
            "stop_plan": {"method": label, "stop_distance_pct": stop_pct * 100,
                          "stop_price": stop_price, "target_r_multiple": target_r_multiple,
                          "target_price": target_price,
                          "target_distance_pct": stop_pct * target_r_multiple * 100},
            "risk_budget": {"account_equity": account,
                            "risk_pct": sizing.get("planned_loss_pct_equity"),
                            "requested_risk_pct": risk_pct,
                            "risk_amount": risk_budget, "per_unit_risk": per_unit_risk,
                            "position_units": position_units, "position_value": position_value},
            "position_sizing": {
                **sizing,
                "evidence_win_probability_pct": (
                    float(sizing_probability["probability"]) * 100.0
                    if sizing_probability.get("probability") is not None else None
                ),
                "evidence_resolved_paths": sizing_probability.get("resolved_paths"),
                "probability_prior_paths": sizing_probability.get("prior_paths"),
                "volatility_20d_pct": (
                    float(volatility["vol20"]) * 100.0 if volatility.get("vol20") is not None else None
                ),
                "volatility_60d_pct": (
                    float(volatility["vol60"]) * 100.0 if volatility.get("vol60") is not None else None
                ),
            },
            "expectancy": {
                "win_probability_pct": p_win * 100 if p_win is not None else None,
                "loss_probability_pct": p_loss * 100 if p_loss is not None else None,
                "resolved_rate_pct": float(stats["resolved_rate"]) * 100 if stats.get("resolved_rate") is not None else None,
                "expected_loss_pct": expected_loss_pct * 100 if expected_loss_pct is not None else None,
                "expected_gain_pct": expected_gain_pct * 100 if expected_gain_pct is not None else None,
                "expectancy_pct": expectancy * 100 if expectancy is not None else None,
                "expected_loss_amount": expected_loss_money,
                "expected_gain_amount": expected_gain_money,
                "sample_size": stats.get("sample_size"),
            },
            "holdout": holdout,
            "candidates": [{"method": c[1], "stop_distance_pct": c[2] * 100,
                            "expectancy_pct": c[0] * 100} for c in scored[:6]],
            "warning": (
                "Historical heuristic, not a guarantee or personalized investment advice. "
                "Changing sizing method changes exposure, not the underlying company outlook. "
                "Stop placement should reflect market structure and your risk budget; gaps and slippage can exceed the planned stop."
            ),
        }
    except Exception as exc:
        return {"status": "Trading risk analysis unavailable.", "ticker": ticker, "error": str(exc)}
