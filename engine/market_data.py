"""Canonical market-data repository used by every feature.

It batches symbols when possible, normalizes Yahoo's changing column layouts,
and persists recent successful observations so charts can paint immediately
and survive short provider outages.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import RLock
from typing import Iterable

import pandas as pd

from .provider_cache import MARKET_CACHE


_FETCH_LOCK = RLock()


def source_ttl(interval: str) -> float:
    value = str(interval or "1d").lower()
    if value.endswith("m") or value.endswith("h"):
        return 45.0
    if value in {"1d", "5d", "1wk"}:
        return 900.0
    return 3600.0


def _key(symbol: str, period: str, interval: str, auto_adjust: bool) -> str:
    return f"{symbol.upper()}|{period}|{interval}|{int(bool(auto_adjust))}"


def _normalize(frame: pd.DataFrame | None, symbol: str) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    clean = frame.copy()
    if isinstance(clean.columns, pd.MultiIndex):
        first = set(clean.columns.get_level_values(0))
        last = set(clean.columns.get_level_values(-1))
        try:
            if symbol in first:
                clean = clean[symbol].copy()
            elif symbol in last:
                clean = clean.xs(symbol, axis=1, level=-1, drop_level=True).copy()
            else:
                clean.columns = clean.columns.get_level_values(0)
        except (KeyError, ValueError):
            clean.columns = [column[0] if isinstance(column, tuple) else column for column in clean.columns]
    clean = clean.loc[:, ~clean.columns.duplicated()].dropna(how="all")
    clean.index = pd.to_datetime(clean.index, errors="coerce")
    clean = clean[~clean.index.isna()].sort_index()
    return clean


def _payload(frame: pd.DataFrame) -> dict:
    clean = frame.copy()
    rows = []
    for index, values in clean.iterrows():
        row = {"date": pd.Timestamp(index).isoformat()}
        for column, value in values.items():
            number = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
            row[str(column)] = None if pd.isna(number) else float(number)
        rows.append(row)
    return {"columns": [str(column) for column in clean.columns], "rows": rows}


def _frame(payload: dict | None) -> pd.DataFrame:
    rows = list((payload or {}).get("rows") or [])
    if not rows:
        return pd.DataFrame()
    data = pd.DataFrame(rows)
    data.index = pd.to_datetime(data.pop("date"), errors="coerce")
    return data[~data.index.isna()].sort_index()


def history(
    symbol: str,
    *,
    period: str = "5y",
    interval: str = "1d",
    auto_adjust: bool = False,
    force: bool = False,
) -> pd.DataFrame:
    symbol = str(symbol or "").strip().upper()
    if not symbol:
        return pd.DataFrame()
    ttl = source_ttl(interval)
    cache_key = _key(symbol, period, interval, auto_adjust)
    cached = MARKET_CACHE.get(cache_key, ttl=ttl, stale_ttl=max(86400.0, ttl * 96))
    if cached and cached.fresh and not force:
        return _frame(cached.value)
    try:
        import yfinance as yf

        with _FETCH_LOCK:
            raw = yf.download(
                symbol,
                period=period,
                interval=interval,
                auto_adjust=auto_adjust,
                progress=False,
                threads=False,
            )
        clean = _normalize(raw, symbol)
        if clean.empty:
            raise RuntimeError("No market observations returned.")
        MARKET_CACHE.put(cache_key, _payload(clean))
        return clean
    except Exception:
        if cached:
            return _frame(cached.value)
        raise


def batch_history(
    symbols: Iterable[str],
    *,
    period: str = "5y",
    interval: str = "1d",
    auto_adjust: bool = False,
    force: bool = False,
) -> dict[str, pd.DataFrame]:
    ordered = list(dict.fromkeys(str(symbol or "").strip().upper() for symbol in symbols if symbol))
    if not ordered:
        return {}
    ttl = source_ttl(interval)
    results: dict[str, pd.DataFrame] = {}
    stale: dict[str, pd.DataFrame] = {}
    missing = []
    for symbol in ordered:
        cached = MARKET_CACHE.get(_key(symbol, period, interval, auto_adjust), ttl=ttl, stale_ttl=max(86400.0, ttl * 96))
        if cached:
            frame = _frame(cached.value)
            stale[symbol] = frame
            if cached.fresh and not force and not frame.empty:
                results[symbol] = frame
                continue
        missing.append(symbol)
    if missing:
        try:
            import yfinance as yf

            with _FETCH_LOCK:
                raw = yf.download(
                    missing,
                    period=period,
                    interval=interval,
                    auto_adjust=auto_adjust,
                    progress=False,
                    threads=True,
                    group_by="ticker",
                )
            for symbol in missing:
                clean = _normalize(raw, symbol)
                if not clean.empty:
                    results[symbol] = clean
                    MARKET_CACHE.put(_key(symbol, period, interval, auto_adjust), _payload(clean))
                elif symbol in stale and not stale[symbol].empty:
                    results[symbol] = stale[symbol]
        except Exception:
            for symbol in missing:
                if symbol in stale and not stale[symbol].empty:
                    results[symbol] = stale[symbol]
    return {symbol: results[symbol] for symbol in ordered if symbol in results}

