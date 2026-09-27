"""Explainable technical-indicator, VSA, and trade-planning research.

The module deliberately keeps observations, interpretations, and conditional
plans separate.  It does not convert a chart pattern into a guaranteed order.
All calculations are deterministic so they can be tested with supplied OHLCV
frames and audited in the interface.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
from typing import Any, Iterable

import numpy as np
import pandas as pd

from config import STOCK_PERIOD
from engine.stock import ticker_for
from .market_data import batch_history as market_batch_history, history as market_history
from .position_sizing import calculate_position_size
from .technical import atr as canonical_atr, rsi as canonical_rsi


MINIMUM_ROWS = 80
SCREEN_LIMIT = 10
RECENT_EVENT_BARS = 8


@dataclass(frozen=True)
class ResearchProfile:
    key: str
    label: str
    score_floor: float
    risk_reward: float
    max_risk_pct: float
    max_position_pct: float
    max_sector_pct: float
    wait_sessions: tuple[int, int]
    hold_sessions: tuple[int, int]


PROFILES = {
    "conservative": ResearchProfile(
        "conservative", "Conservative", 72.0, 2.5, 0.5, 7.5, 20.0, (5, 20), (40, 120)
    ),
    "balanced": ResearchProfile(
        "balanced", "Balanced", 62.0, 2.0, 1.0, 10.0, 30.0, (2, 10), (20, 60)
    ),
    "active": ResearchProfile(
        "active", "Active", 54.0, 1.6, 1.5, 15.0, 40.0, (1, 5), (5, 25)
    ),
}


def _finite(value: Any, digits: int | None = None) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return round(number, digits) if digits is not None else number


def _bounded(value: Any, low: float, high: float, fallback: float) -> float:
    number = _finite(value)
    if number is None:
        number = fallback
    return max(low, min(high, number))


def _profile(value: str | None) -> ResearchProfile:
    return PROFILES.get(str(value or "balanced").strip().lower(), PROFILES["balanced"])


def _date_label(value: Any) -> str:
    try:
        return pd.Timestamp(value).date().isoformat()
    except Exception:
        return str(value)


def _standardize_frame(frame: pd.DataFrame | None) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    result = frame.copy()
    if isinstance(result.columns, pd.MultiIndex):
        # A single-ticker yfinance response can still carry a second level.
        result.columns = result.columns.get_level_values(0)
    canonical = {}
    for column in result.columns:
        key = str(column).strip().lower()
        if key in {"open", "high", "low", "close", "volume"}:
            canonical[column] = key.title()
    result = result.rename(columns=canonical)
    required = ["Open", "High", "Low", "Close", "Volume"]
    if not set(required).issubset(result.columns):
        return pd.DataFrame()
    result = result[required].apply(pd.to_numeric, errors="coerce")
    result = result.replace([np.inf, -np.inf], np.nan).dropna(subset=required)
    result = result[(result["High"] >= result["Low"]) & (result["Close"] > 0)]
    return result.sort_index()


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    return canonical_rsi(close, period)


def _indicator_frame(frame: pd.DataFrame) -> pd.DataFrame:
    open_ = frame["Open"]
    high = frame["High"]
    low = frame["Low"]
    close = frame["Close"]
    volume = frame["Volume"].clip(lower=0)
    result = frame.copy()

    result["sma20"] = close.rolling(20).mean()
    result["sma50"] = close.rolling(50).mean()
    result["sma200"] = close.rolling(200).mean()
    result["ema12"] = close.ewm(span=12, adjust=False).mean()
    result["ema26"] = close.ewm(span=26, adjust=False).mean()
    result["macd"] = result["ema12"] - result["ema26"]
    result["macd_signal"] = result["macd"].ewm(span=9, adjust=False).mean()
    result["rsi14"] = canonical_rsi(close, 14)

    previous_close = close.shift(1)
    true_range = pd.concat(
        [(high - low), (high - previous_close).abs(), (low - previous_close).abs()], axis=1
    ).max(axis=1)
    result["atr14"] = canonical_atr(frame, 14)

    upward = high.diff()
    downward = -low.diff()
    plus_dm = pd.Series(np.where((upward > downward) & (upward > 0), upward, 0.0), index=frame.index)
    minus_dm = pd.Series(np.where((downward > upward) & (downward > 0), downward, 0.0), index=frame.index)
    smooth_tr = true_range.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean() / smooth_tr.replace(0, np.nan)
    minus_di = 100 * minus_dm.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean() / smooth_tr.replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    result["adx14"] = dx.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    result["plus_di"] = plus_di
    result["minus_di"] = minus_di

    standard_deviation = close.rolling(20).std()
    result["bb_mid"] = result["sma20"]
    result["bb_upper"] = result["sma20"] + 2 * standard_deviation
    result["bb_lower"] = result["sma20"] - 2 * standard_deviation

    typical_price = (high + low + close) / 3
    raw_money_flow = typical_price * volume
    positive_flow = raw_money_flow.where(typical_price.diff() > 0, 0.0).rolling(14).sum()
    negative_flow = raw_money_flow.where(typical_price.diff() < 0, 0.0).rolling(14).sum()
    money_ratio = positive_flow / negative_flow.replace(0, np.nan)
    result["mfi14"] = (100 - 100 / (1 + money_ratio)).where(negative_flow.ne(0), 100.0)

    direction = np.sign(close.diff()).fillna(0)
    result["obv"] = (direction * volume).cumsum()
    obv_change = result["obv"].diff(20)
    result["obv_slope20"] = obv_change / volume.rolling(20).mean().replace(0, np.nan)

    spread = (high - low).replace(0, np.nan)
    result["spread"] = spread
    result["spread_ratio"] = spread / spread.rolling(20).mean().replace(0, np.nan)
    result["close_location"] = ((close - low) / spread).clip(0, 1).fillna(0.5)
    result["volume_ratio"] = volume / volume.rolling(20).mean().replace(0, np.nan)
    volume_std = volume.rolling(20).std().replace(0, np.nan)
    result["volume_z"] = (volume - volume.rolling(20).mean()) / volume_std
    money_flow_multiplier = ((close - low) - (high - close)) / spread
    result["cmf20"] = (
        (money_flow_multiplier.fillna(0) * volume).rolling(20).sum()
        / volume.rolling(20).sum().replace(0, np.nan)
    )
    result["return20"] = close.pct_change(20, fill_method=None) * 100
    result["return60"] = close.pct_change(60, fill_method=None) * 100
    result["range_high20"] = high.rolling(20).max().shift(1)
    result["range_low20"] = low.rolling(20).min().shift(1)
    result["range_high60"] = high.rolling(60).max()
    result["range_low60"] = low.rolling(60).min()
    result["bar_up"] = close > previous_close
    result["bar_down"] = close < previous_close
    result["body_up"] = close >= open_
    return result.replace([np.inf, -np.inf], np.nan)


def _event(
    index: Any,
    name: str,
    bias: str,
    strength: str,
    explanation: str,
    confirmation: str,
) -> dict[str, Any]:
    return {
        "date": _date_label(index),
        "name": name,
        "bias": bias,
        "strength": strength,
        "explanation": explanation,
        "confirmation": confirmation,
    }


def _vsa_events(data: pd.DataFrame) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    start = max(2, len(data) - 30)
    for position in range(start, len(data)):
        row = data.iloc[position]
        previous = data.iloc[position - 1]
        prior_two_volume = data["Volume"].iloc[position - 2 : position]
        volume_ratio = _finite(row["volume_ratio"]) or 0.0
        spread_ratio = _finite(row["spread_ratio"]) or 0.0
        close_location = _finite(row["close_location"]) or 0.5
        index = data.index[position]
        high_volume = volume_ratio >= 1.5
        ultra_volume = volume_ratio >= 2.2
        low_volume = volume_ratio <= 0.72 and row["Volume"] < prior_two_volume.min()
        wide = spread_ratio >= 1.35
        narrow = spread_ratio <= 0.78
        prior_trend = (_finite(previous.get("return20")) or 0.0)

        if low_volume and narrow and bool(row["bar_down"]) and close_location >= 0.45:
            events.append(_event(
                index, "No supply", "bullish", "moderate",
                "A narrow down bar printed on less volume than the prior two bars, suggesting reduced selling activity.",
                "Require a higher close or a demand bar before treating supply as exhausted.",
            ))
        if low_volume and narrow and bool(row["bar_up"]) and close_location <= 0.60:
            events.append(_event(
                index, "No demand", "bearish", "moderate",
                "A narrow up bar printed on less volume than the prior two bars, suggesting weak participation from buyers.",
                "Require a lower close or renewed supply before treating demand as absent.",
            ))
        if high_volume and bool(row["bar_down"]) and close_location >= 0.58:
            events.append(_event(
                index, "Stopping volume", "bullish", "strong" if ultra_volume else "moderate",
                "Heavy activity appeared on a down bar, but the close recovered into the upper part of its range.",
                "Look for a low-volume retest that holds this bar's low.",
            ))
        if high_volume and bool(row["bar_up"]) and close_location <= 0.38:
            events.append(_event(
                index, "Supply entering", "bearish", "strong" if ultra_volume else "moderate",
                "High activity accompanied an up bar that closed poorly, consistent with supply absorbing demand.",
                "Confirm with failure to regain this bar's high and a subsequent lower close.",
            ))
        if ultra_volume and wide and bool(row["bar_down"]) and prior_trend <= -5 and close_location >= 0.42:
            events.append(_event(
                index, "Possible selling climax", "bullish", "strong",
                "Exceptional volume and range followed an established decline, while the close recovered from the low.",
                "A climax is provisional until an automatic rally and successful secondary test appear.",
            ))
        if ultra_volume and wide and bool(row["bar_up"]) and prior_trend >= 5 and close_location <= 0.58:
            events.append(_event(
                index, "Possible buying climax", "bearish", "strong",
                "Exceptional volume and range followed an established advance, but the bar did not close firmly at its high.",
                "A climax is provisional until price fails to progress and supply follows through.",
            ))
        if high_volume and narrow:
            bias = "bullish" if close_location >= 0.62 else "bearish" if close_location <= 0.38 else "neutral"
            events.append(_event(
                index, "Effort–result divergence", bias, "moderate",
                "Volume was high while price spread stayed narrow: substantial effort produced limited movement.",
                "Use the next two to three bars to identify whether demand or supply performed the absorption.",
            ))
    return events[-16:]


def _trap_events(data: pd.DataFrame) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    traps: list[dict[str, Any]] = []
    bull_risk = 0.0
    bear_risk = 0.0
    start = max(20, len(data) - 20)
    for position in range(start, len(data)):
        row = data.iloc[position]
        index = data.index[position]
        prior_high = _finite(row["range_high20"])
        prior_low = _finite(row["range_low20"])
        if prior_high is None or prior_low is None:
            continue
        volume_ratio = _finite(row["volume_ratio"]) or 0.0
        close_location = _finite(row["close_location"]) or 0.5
        age = len(data) - 1 - position
        recency = max(0.25, 1.0 - age / 10.0)

        if row["High"] > prior_high and row["Close"] < prior_high and close_location <= 0.52:
            score = min(92.0, (46.0 + max(0.0, volume_ratio - 1.0) * 24.0) * recency)
            bull_risk = max(bull_risk, score)
            traps.append({
                **_event(
                    index, "Bull-trap risk", "bearish", "strong" if volume_ratio >= 1.5 else "moderate",
                    "Price traded above 20-session resistance but closed back below it.",
                    "Do not chase the breakout; require a close back above resistance and a successful retest.",
                ),
                "level": prior_high,
                "score": round(score, 1),
            })
        elif row["Close"] > prior_high and volume_ratio < 0.85:
            score = min(64.0, 36.0 * recency)
            bull_risk = max(bull_risk, score)
            traps.append({
                **_event(
                    index, "Low-volume breakout warning", "bearish", "moderate",
                    "Price closed above resistance without normal participation.",
                    "Require expanding volume or a retest that holds above the breakout level.",
                ),
                "level": prior_high,
                "score": round(score, 1),
            })

        if row["Low"] < prior_low and row["Close"] > prior_low and close_location >= 0.48:
            score = min(92.0, (46.0 + max(0.0, volume_ratio - 1.0) * 24.0) * recency)
            bear_risk = max(bear_risk, score)
            traps.append({
                **_event(
                    index, "Bear-trap risk", "bullish", "strong" if volume_ratio >= 1.5 else "moderate",
                    "Price traded below 20-session support but closed back above it.",
                    "Require follow-through above the reclaim bar before treating the breakdown as failed.",
                ),
                "level": prior_low,
                "score": round(score, 1),
            })
        elif row["Close"] < prior_low and volume_ratio < 0.85:
            score = min(64.0, 36.0 * recency)
            bear_risk = max(bear_risk, score)
            traps.append({
                **_event(
                    index, "Low-volume breakdown warning", "bullish", "moderate",
                    "Price closed below support without normal participation.",
                    "Require expanding supply or a failed retest before accepting the breakdown.",
                ),
                "level": prior_low,
                "score": round(score, 1),
            })

    current = data.iloc[-1]
    return traps[-10:], {
        "bull_trap_risk": round(bull_risk, 1),
        "bear_trap_risk": round(bear_risk, 1),
        "breakout_level": _finite(current["range_high20"], 6),
        "breakdown_level": _finite(current["range_low20"], 6),
        "method": "Recent 20-session breakouts and breakdowns are checked for close-back-inside rejection and participation.",
    }


def _wyckoff_phase(data: pd.DataFrame, vsa_events: Iterable[dict[str, Any]]) -> dict[str, Any]:
    latest = data.iloc[-1]
    close = _finite(latest["Close"]) or 0.0
    sma20 = _finite(latest["sma20"])
    sma50 = _finite(latest["sma50"])
    sma200 = _finite(latest["sma200"])
    return60 = _finite(latest["return60"]) or 0.0
    cmf = _finite(latest["cmf20"]) or 0.0
    high60 = _finite(latest["range_high60"])
    low60 = _finite(latest["range_low60"])
    range_position = (
        (close - low60) / (high60 - low60)
        if high60 is not None and low60 is not None and high60 > low60
        else 0.5
    )
    event_names = {event["name"] for event in vsa_events[-6:]}
    scores = {"markup": 0.0, "distribution": 0.0, "markdown": 0.0, "accumulation": 0.0, "trading_range": 0.0}

    if sma20 is not None and sma50 is not None:
        scores["markup"] += 2 if close > sma20 > sma50 else 0
        scores["markdown"] += 2 if close < sma20 < sma50 else 0
    if sma200 is not None and sma50 is not None:
        scores["markup"] += 2 if close > sma50 > sma200 else 0
        scores["markdown"] += 2 if close < sma50 < sma200 else 0
    scores["markup"] += 1 if return60 > 8 else 0
    scores["markdown"] += 1 if return60 < -8 else 0
    scores["markup"] += 1 if cmf > 0.05 else 0
    scores["markdown"] += 1 if cmf < -0.05 else 0

    range_like = abs(return60) < 12 or (0.20 <= range_position <= 0.80)
    if range_like:
        scores["trading_range"] += 2
        scores["accumulation"] += 1 if cmf > 0.03 else 0
        scores["distribution"] += 1 if cmf < -0.03 else 0
        scores["accumulation"] += 1 if range_position < 0.58 else 0
        scores["distribution"] += 1 if range_position > 0.42 else 0
    if {"Stopping volume", "Possible selling climax", "No supply"} & event_names:
        scores["accumulation"] += 2
    if {"Supply entering", "Possible buying climax", "No demand"} & event_names:
        scores["distribution"] += 2
    if return60 < -5:
        scores["accumulation"] += 0.5
    if return60 > 5:
        scores["distribution"] += 0.5

    ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    key, top = ordered[0]
    second = ordered[1][1]
    confidence = min(88.0, 38.0 + max(0.0, top - second) * 12.0)
    label = key.replace("_", " ").title()
    descriptions = {
        "markup": "Trend structure favors demand, with price holding above rising reference averages.",
        "markdown": "Trend structure favors supply, with price below important reference averages.",
        "accumulation": "Range behavior and volume clues are consistent with possible absorption after weakness.",
        "distribution": "Range behavior and volume clues are consistent with possible supply after strength.",
        "trading_range": "Price and volume do not yet resolve a reliable directional phase.",
    }
    return {
        "key": key,
        "label": label,
        "confidence": round(confidence, 1),
        "description": descriptions[key],
        "range_position_pct": round(range_position * 100, 1),
        "scores": {name: round(value, 1) for name, value in scores.items()},
        "warning": "Wyckoff phases are heuristic classifications, not confirmed institutional positions.",
    }


def _indicator_payload(data: pd.DataFrame) -> dict[str, Any]:
    latest = data.iloc[-1]
    close = _finite(latest["Close"]) or 0.0
    indicators = {
        "rsi14": {
            "label": "RSI (14)", "value": _finite(latest["rsi14"], 2),
            "state": "overbought" if (_finite(latest["rsi14"]) or 50) >= 70 else "oversold" if (_finite(latest["rsi14"]) or 50) <= 30 else "neutral",
        },
        "macd": {
            "label": "MACD", "value": _finite(latest["macd"], 4),
            "signal": _finite(latest["macd_signal"], 4),
            "state": "bullish" if (_finite(latest["macd"]) or 0) > (_finite(latest["macd_signal"]) or 0) else "bearish",
        },
        "adx14": {
            "label": "ADX (14)", "value": _finite(latest["adx14"], 2),
            "state": "strong trend" if (_finite(latest["adx14"]) or 0) >= 25 else "weak/ranging",
        },
        "mfi14": {
            "label": "Money Flow Index", "value": _finite(latest["mfi14"], 2),
            "state": "overbought" if (_finite(latest["mfi14"]) or 50) >= 80 else "oversold" if (_finite(latest["mfi14"]) or 50) <= 20 else "neutral",
        },
        "cmf20": {
            "label": "Chaikin Money Flow", "value": _finite(latest["cmf20"], 4),
            "state": "demand" if (_finite(latest["cmf20"]) or 0) > 0.05 else "supply" if (_finite(latest["cmf20"]) or 0) < -0.05 else "balanced",
        },
        "relative_volume": {
            "label": "Relative volume", "value": _finite(latest["volume_ratio"], 2),
            "state": "high" if (_finite(latest["volume_ratio"]) or 0) >= 1.5 else "low" if (_finite(latest["volume_ratio"]) or 1) <= 0.72 else "normal",
        },
        "atr14": {
            "label": "ATR (14)", "value": _finite(latest["atr14"], 6),
            "percent_of_price": _finite(((_finite(latest["atr14"]) or 0) / close * 100) if close else None, 2),
            "state": "volatility range",
        },
        "bollinger": {
            "label": "Bollinger Bands", "lower": _finite(latest["bb_lower"], 6),
            "middle": _finite(latest["bb_mid"], 6), "upper": _finite(latest["bb_upper"], 6),
            "state": "above upper band" if _finite(latest["bb_upper"]) is not None and close > latest["bb_upper"] else "below lower band" if _finite(latest["bb_lower"]) is not None and close < latest["bb_lower"] else "inside bands",
        },
        "moving_averages": {
            "label": "Moving averages", "sma20": _finite(latest["sma20"], 6),
            "sma50": _finite(latest["sma50"], 6), "sma200": _finite(latest["sma200"], 6),
            "state": "bullish stack" if all(_finite(latest[x]) is not None for x in ("sma20", "sma50", "sma200")) and close > latest["sma20"] > latest["sma50"] > latest["sma200"] else "bearish stack" if all(_finite(latest[x]) is not None for x in ("sma20", "sma50", "sma200")) and close < latest["sma20"] < latest["sma50"] < latest["sma200"] else "mixed",
        },
    }
    return indicators


def _research_score(
    data: pd.DataFrame,
    phase: dict[str, Any],
    events: list[dict[str, Any]],
    trap_summary: dict[str, Any],
    fundamental_context: dict[str, Any] | None,
) -> tuple[float, list[dict[str, Any]]]:
    latest = data.iloc[-1]
    close = _finite(latest["Close"]) or 0.0
    trend = 0.0
    if _finite(latest["sma20"]) is not None and close > latest["sma20"]:
        trend += 6
    if _finite(latest["sma50"]) is not None and close > latest["sma50"]:
        trend += 6
    if _finite(latest["sma200"]) is not None and close > latest["sma200"]:
        trend += 5
    if (_finite(latest["macd"]) or 0) > (_finite(latest["macd_signal"]) or 0):
        trend += 5
    if (_finite(latest["plus_di"]) or 0) > (_finite(latest["minus_di"]) or 0):
        trend += 3

    rsi = _finite(latest["rsi14"]) or 50.0
    mfi = _finite(latest["mfi14"]) or 50.0
    momentum = 0.0
    momentum += 8 if 45 <= rsi <= 68 else 4 if 35 <= rsi < 45 else 2 if 68 < rsi <= 75 else 0
    momentum += 6 if 40 <= mfi <= 72 else 3 if 25 <= mfi < 40 else 1
    momentum += 6 if (_finite(latest["return20"]) or 0) > 0 else 1

    recent = events[-6:]
    bullish = sum(2 if event["strength"] == "strong" else 1 for event in recent if event["bias"] == "bullish")
    bearish = sum(2 if event["strength"] == "strong" else 1 for event in recent if event["bias"] == "bearish")
    volume = 8.0 + min(7.0, max(-7.0, (bullish - bearish) * 2.0))
    volume += 4 if (_finite(latest["cmf20"]) or 0) > 0.03 else 0
    volume += 3 if (_finite(latest["obv_slope20"]) or 0) > 0 else 0
    volume = max(0.0, min(20.0, volume))

    trap_safety = max(0.0, 15.0 - float(trap_summary.get("bull_trap_risk") or 0) * 0.15)
    fundamental = 7.5
    context = fundamental_context or {}
    if context.get("available"):
        health = _bounded(context.get("health_score"), 0, 100, 50)
        coverage = _bounded(context.get("coverage_pct"), 0, 100, 50)
        flags = max(0, int(context.get("risk_flag_count") or 0))
        fundamental = min(20.0, health * 0.12 + coverage * 0.08) - min(8.0, flags * 2.0)
        fundamental = max(0.0, fundamental)

    components = [
        {"key": "trend", "label": "Trend structure", "score": round(trend, 1), "maximum": 25.0},
        {"key": "momentum", "label": "Momentum balance", "score": round(momentum, 1), "maximum": 20.0},
        {"key": "volume", "label": "Volume evidence", "score": round(volume, 1), "maximum": 20.0},
        {"key": "trap", "label": "Trap safety", "score": round(trap_safety, 1), "maximum": 15.0},
        {"key": "fundamental", "label": "Statement evidence", "score": round(fundamental, 1), "maximum": 20.0, "available": bool(context.get("available"))},
    ]
    score = sum(item["score"] for item in components)
    if phase["key"] == "markdown":
        score = min(score, 48.0)
    return round(max(0.0, min(100.0, score)), 1), components


def _trade_plan(
    data: pd.DataFrame,
    score: float,
    profile: ResearchProfile,
    phase: dict[str, Any],
    events: list[dict[str, Any]],
    traps: dict[str, Any],
    account_value: float | None,
    requested_risk_pct: float,
    position_status: str,
    entry_price: float | None,
    sector_exposure_pct: float,
) -> dict[str, Any]:
    latest = data.iloc[-1]
    current = _finite(latest["Close"]) or 0.0
    atr = _finite(latest["atr14"]) or current * 0.025
    support = _finite(latest["range_low20"]) or float(data["Low"].tail(20).min())
    resistance = _finite(latest["range_high20"]) or float(data["High"].tail(20).max())
    sma20 = _finite(latest["sma20"]) or current
    breakout = resistance + atr * 0.12
    anchor = resistance if current > resistance else min(current, sma20)
    entry_low = max(0.0, anchor - atr * 0.35)
    entry_high = max(entry_low, anchor + atr * 0.25)
    entry_mid = (entry_low + entry_high) / 2
    invalidation = max(0.0, max(support - atr * 0.25, anchor - atr * 2.0))
    unit_risk = max(atr * 0.8, entry_mid - invalidation)
    target1 = max(resistance, entry_mid + unit_risk * profile.risk_reward)
    target2 = entry_mid + unit_risk * (profile.risk_reward + 1.0)

    rsi = _finite(latest["rsi14"]) or 50.0
    bb_upper = _finite(latest["bb_upper"])
    overextended = rsi >= 72 or (bb_upper is not None and current > bb_upper)
    bull_trap_risk = float(traps.get("bull_trap_risk") or 0)
    recent_bullish = any(event["bias"] == "bullish" for event in events[-4:])
    demand_confirmation = recent_bullish or (
        (_finite(latest["cmf20"]) or 0) > 0.03
        and (_finite(latest["macd"]) or 0) > (_finite(latest["macd_signal"]) or 0)
    )

    holding = position_status == "holding"
    if holding and entry_price is not None and current <= invalidation:
        action = "REVIEW_EXIT"
        headline = "The technical invalidation level has been reached"
    elif holding and (bull_trap_risk >= 45 or phase["key"] in {"distribution", "markdown"}):
        action = "TIGHTEN_RISK"
        headline = "Protect the existing position while supply risk is elevated"
    elif holding:
        action = "HOLD_WITH_RULES"
        headline = "The position can be monitored with a defined trailing invalidation"
    elif bull_trap_risk >= 45:
        action = "WAIT_TRAP_RESOLUTION"
        headline = "Wait for the failed-breakout risk to resolve"
    elif phase["key"] == "markdown":
        action = "AVOID_NEW_ENTRY"
        headline = "Avoid a new long entry while markdown conditions dominate"
    elif overextended:
        action = "WAIT_FOR_PULLBACK"
        headline = "Do not chase price; wait for a controlled pullback or retest"
    elif score >= profile.score_floor and demand_confirmation:
        action = "CONSIDER_ON_CONFIRMATION"
        headline = "Research candidate—act only after the stated confirmation"
    else:
        action = "WAIT_FOR_CONFIRMATION"
        headline = "Evidence is incomplete; wait for price and volume confirmation"

    effective_risk_pct = min(profile.max_risk_pct, max(0.05, requested_risk_pct))
    sizing: dict[str, Any] = {
        "requested_risk_pct": round(requested_risk_pct, 2),
        "effective_risk_pct": round(effective_risk_pct, 2),
        "profile_cap_pct": profile.max_risk_pct,
        "max_position_pct": profile.max_position_pct,
        "max_sector_pct": profile.max_sector_pct,
        "same_industry_exposure_pct": round(sector_exposure_pct, 2),
        "staged_entries": 3,
        "method": "Canonical Fixed Fractional sizing, capped by the profile and remaining same-industry room.",
    }
    if account_value is not None and account_value > 0 and unit_risk > 0 and entry_mid > 0:
        sector_room_pct = max(0.0, profile.max_sector_pct - sector_exposure_pct)
        canonical = calculate_position_size(
            "fixed-fractional",
            account_equity=account_value,
            entry_price=entry_mid,
            stop_price=invalidation,
            requested_risk_pct=effective_risk_pct,
            target_r_multiple=profile.risk_reward,
            max_cash_allocation_pct=min(profile.max_position_pct, sector_room_pct),
        )
        shares = int(canonical.get("position_units") or 0)
        risk_budget = account_value * effective_risk_pct / 100
        sizing.update({
            "account_value": round(account_value, 2),
            "risk_budget": round(risk_budget, 2),
            "maximum_position_value": round(shares * entry_mid, 2),
            "maximum_units": shares,
            "per_stage_units": math.floor(shares / 3),
            "sector_room_pct": round(sector_room_pct, 2),
            "canonical_result": canonical,
        })

    sell_rules = [
        f"Review or exit after a decisive daily close below {_finite(invalidation, 6)}.",
        "Reduce risk if a high-volume up bar closes poorly and the next session confirms weakness.",
        f"At {_finite(target1, 6)}, consider protecting part of the gain rather than assuming the trend must continue.",
        "Recalculate after new financial statements, a major corporate event, or an abnormal volume shock.",
    ]
    return {
        "action": action,
        "headline": headline,
        "profile": profile.key,
        "profile_label": profile.label,
        "current_price": _finite(current, 6),
        "conditional_entry_zone": {"low": _finite(entry_low, 6), "high": _finite(entry_high, 6)},
        "breakout_confirmation": _finite(breakout, 6),
        "invalidation": _finite(invalidation, 6),
        "target_1": _finite(target1, 6),
        "target_2": _finite(target2, 6),
        "minimum_reward_risk": profile.risk_reward,
        "wait_window": {
            "min_sessions": profile.wait_sessions[0],
            "max_sessions": profile.wait_sessions[1],
            "condition": "Recheck sooner if price enters the conditional zone, reclaims breakout resistance on normal/high volume, or invalidates the setup.",
        },
        "holding_window": {
            "min_sessions": profile.hold_sessions[0],
            "max_sessions": profile.hold_sessions[1],
            "condition": "The window remains valid only while price holds above invalidation and volume/phase evidence does not deteriorate.",
        },
        "confirmation_checklist": [
            "A daily close above the trigger or a successful low-volume retest of support.",
            "Relative volume is normal or expanding on the confirming advance.",
            "No fresh bull-trap warning appears during the confirmation window.",
        ],
        "sell_rules": sell_rules,
        "position_sizing": sizing,
        "disclaimer": "Conditional research plan only—not an order, guarantee, or assessment of personal suitability.",
    }


def analyze_frame(
    frame: pd.DataFrame | None,
    *,
    company: str = "",
    ticker: str = "",
    profile: str = "balanced",
    account_value: float | None = None,
    risk_pct: float = 1.0,
    position_status: str = "watching",
    entry_price: float | None = None,
    sector_exposure_pct: float = 0.0,
    fundamental_context: dict[str, Any] | None = None,
    provider: str = "supplied OHLCV",
) -> dict[str, Any]:
    clean = _standardize_frame(frame)
    if clean.empty:
        return {
            "success": False,
            "status": "unavailable",
            "company": company,
            "ticker": ticker,
            "reason": "Open, high, low, close, and volume history is required.",
        }
    if len(clean) < MINIMUM_ROWS:
        return {
            "success": False,
            "status": "insufficient_history",
            "company": company,
            "ticker": ticker,
            "data_points": len(clean),
            "reason": f"At least {MINIMUM_ROWS} complete OHLCV sessions are required; {len(clean)} were available.",
        }

    settings = _profile(profile)
    account = _finite(account_value)
    entry = _finite(entry_price)
    requested_risk = _bounded(risk_pct, 0.05, 5.0, settings.max_risk_pct)
    exposure = _bounded(sector_exposure_pct, 0.0, 100.0, 0.0)
    status = "holding" if str(position_status).strip().lower() == "holding" else "watching"
    data = _indicator_frame(clean)
    events = _vsa_events(data)
    trap_events, trap_summary = _trap_events(data)
    phase = _wyckoff_phase(data, events)
    score, components = _research_score(data, phase, events, trap_summary, fundamental_context)
    plan = _trade_plan(
        data, score, settings, phase, events, trap_summary, account,
        requested_risk, status, entry, exposure,
    )
    latest = data.iloc[-1]
    coverage = sum(_finite(latest[column]) is not None for column in (
        "rsi14", "macd", "adx14", "mfi14", "cmf20", "atr14", "sma20", "sma50", "sma200"
    ))
    confidence = min(92.0, 48.0 + coverage / 9 * 28.0 + min(len(clean), 500) / 500 * 16.0)
    if not (fundamental_context or {}).get("available"):
        confidence -= 8.0

    recent_cutoff = {_date_label(index) for index in data.index[-RECENT_EVENT_BARS:]}
    recent_events = [event for event in events if event["date"] in recent_cutoff]
    recent_traps = [event for event in trap_events if event["date"] in recent_cutoff]
    return {
        "success": True,
        "status": "ok",
        "company": company or ticker,
        "ticker": ticker,
        "as_of": _date_label(data.index[-1]),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "provider": provider,
        "data_points": len(clean),
        "research_score": score,
        "score_floor": settings.score_floor,
        "score_components": components,
        "confidence_pct": round(max(0.0, confidence), 1),
        "indicators": _indicator_payload(data),
        "vsa": {
            "latest_spread_ratio": _finite(latest["spread_ratio"], 2),
            "latest_volume_ratio": _finite(latest["volume_ratio"], 2),
            "latest_close_location_pct": _finite((_finite(latest["close_location"]) or 0.5) * 100, 1),
            "recent_events": recent_events,
            "method": "Volume is read against the high–low spread, close location, prior trend, and following confirmation.",
        },
        "traps": {**trap_summary, "recent_events": recent_traps},
        "wyckoff": phase,
        "financial_statements": fundamental_context or {
            "available": False,
            "note": "No indexed statement evidence was available; the score uses a neutral placeholder and lower confidence.",
        },
        "plan": plan,
        "limitations": [
            "High volume is not automatically bullish or bearish; the close, spread, background, and next bars matter.",
            "Reported volume quality varies by exchange and instrument. Spot-FX tick volume is not centralized market volume.",
            "Levels are historical reference zones and may gap or fail during news, illiquidity, or regime changes.",
            "A newly indexed statement changes the fundamental evidence only after the report scan completes and this analysis is rerun.",
        ],
    }


def _download_frame(ticker: str) -> pd.DataFrame:
    return market_history(ticker, period=STOCK_PERIOD, interval="1d", auto_adjust=False)


def _download_frames(tickers: Iterable[str]) -> dict[str, pd.DataFrame]:
    """Fetch a screening universe in one provider request to limit latency."""
    symbols = list(dict.fromkeys(str(ticker).strip().upper() for ticker in tickers if ticker))
    return market_batch_history(symbols, period=STOCK_PERIOD, interval="1d", auto_adjust=False)


def analyze_company(
    company: str,
    *,
    market_symbol: str | None = None,
    fundamental_context: dict[str, Any] | None = None,
    **settings: Any,
) -> dict[str, Any]:
    normalized = str(company or "").strip().upper()[:80]
    if not normalized:
        return {"success": False, "status": "invalid_request", "reason": "Enter a company or market symbol."}
    ticker = ticker_for(market_symbol or normalized)
    try:
        frame = _download_frame(ticker)
        return analyze_frame(
            frame,
            company=normalized,
            ticker=ticker,
            fundamental_context=fundamental_context,
            provider="Yahoo Finance OHLCV",
            **settings,
        )
    except Exception:
        return {
            "success": False,
            "status": "provider_unavailable",
            "company": normalized,
            "ticker": ticker,
            "reason": "Market history could not be retrieved. Check the symbol, connection, and provider status, then retry.",
        }


def screen_companies(
    companies: Iterable[dict[str, Any]],
    *,
    profile: str = "balanced",
    account_value: float | None = None,
    risk_pct: float = 1.0,
    sector_exposure_pct: float = 0.0,
) -> dict[str, Any]:
    rows = []
    for item in list(companies)[:SCREEN_LIMIT]:
        company = str(item.get("company") or "").strip().upper()
        if not company:
            continue
        rows.append({**item, "company": company, "ticker": ticker_for(item.get("market_symbol") or company)})
    try:
        frames = _download_frames(item["ticker"] for item in rows)
        provider_error = None
    except Exception:
        frames = {}
        provider_error = "The batch market-history request was unavailable."
    results = []
    for item in rows:
        company = item["company"]
        ticker = item["ticker"]
        frame = frames.get(ticker)
        if frame is None or frame.empty:
            results.append({
                "success": False,
                "status": "provider_unavailable",
                "company": company,
                "ticker": ticker,
                "reason": provider_error or "No usable market history was returned for this symbol.",
            })
            continue
        results.append(analyze_frame(
            frame,
            company=company,
            ticker=ticker,
            fundamental_context=item.get("fundamental_context"),
            provider="Yahoo Finance OHLCV · batch screen",
            profile=profile,
            account_value=account_value,
            risk_pct=risk_pct,
            sector_exposure_pct=sector_exposure_pct,
        ))
    available = [result for result in results if result.get("status") == "ok"]
    available.sort(key=lambda result: (result.get("research_score") or 0), reverse=True)
    unavailable = [result for result in results if result.get("status") != "ok"]
    return {
        "success": True,
        "status": "ok" if available else "unavailable",
        "profile": _profile(profile).key,
        "analyzed": len(available),
        "requested": len(rows),
        "candidates": available,
        "unavailable": unavailable,
        "ranking_note": "Ranking prioritizes research follow-up; it is not a command to buy the highest-scoring security.",
        "update_note": "Upload and re-index new statements, then rerun the screen to refresh statement evidence for every discovered company.",
    }
