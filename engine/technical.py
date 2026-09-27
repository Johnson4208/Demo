"""Canonical technical definitions shared by analytics, VSA, and trade risk."""
from __future__ import annotations

import numpy as np
import pandas as pd


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    values = close.astype(float)
    delta = values.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    average_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    average_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    relative = average_gain / average_loss.replace(0.0, np.nan)
    result = 100.0 - 100.0 / (1.0 + relative)
    return result.where(average_loss.ne(0.0), 100.0)


def atr(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    high = frame["High"].astype(float)
    low = frame["Low"].astype(float)
    close = frame["Close"].astype(float)
    previous = close.shift(1)
    true_range = pd.concat(
        [high - low, (high - previous).abs(), (low - previous).abs()], axis=1
    ).max(axis=1)
    return true_range.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()


def realized_volatility(close: pd.Series, windows: tuple[int, int] = (20, 60)) -> dict[str, float | None]:
    returns = close.astype(float).pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan).dropna()

    def annualized(window: int) -> float | None:
        values = returns.tail(window)
        if len(values) < max(15, window // 2):
            return None
        value = float(values.std(ddof=1) * np.sqrt(252.0))
        return value if np.isfinite(value) and value > 0 else None

    short = annualized(windows[0])
    long = annualized(windows[1])
    blended = 0.60 * short + 0.40 * long if short is not None and long is not None else short if short is not None else long
    return {"annualized": blended, f"vol{windows[0]}": short, f"vol{windows[1]}": long}


def price_zones(close: pd.Series, windows: tuple[int, ...] = (20, 60)) -> dict[str, float | None]:
    values = close.astype(float).dropna()
    result: dict[str, float | None] = {}
    for window in windows:
        sample = values.tail(window)
        result[f"support{window}"] = float(sample.min()) if not sample.empty else None
        result[f"resistance{window}"] = float(sample.max()) if not sample.empty else None
    return result

