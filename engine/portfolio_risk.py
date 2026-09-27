from __future__ import annotations

from typing import Any
import numpy as np
import pandas as pd
from .stock import ticker_for
from .market_data import batch_history
from config import STOCK_PERIOD


def _risk_parity_weights(cov: np.ndarray, iterations: int = 500) -> np.ndarray:
    """Return long-only approximate equal-risk-contribution weights."""
    count = int(cov.shape[0])
    weights = np.full(count, 1.0 / count, dtype=float)
    target = 1.0 / count
    for _ in range(iterations):
        portfolio_variance = float(weights @ cov @ weights)
        if portfolio_variance <= 0:
            break
        marginal = cov @ weights
        contributions = weights * marginal / portfolio_variance
        adjustment = np.clip(target / np.maximum(contributions, 1e-8), 0.5, 2.0)
        updated = weights * np.sqrt(adjustment)
        updated = np.clip(updated, 0.005, 1.0)
        updated /= updated.sum()
        if float(np.max(np.abs(updated - weights))) < 1e-7:
            weights = updated
            break
        weights = updated
    return weights


def analyze_portfolio(holdings: list[dict[str, Any]]) -> dict[str, Any]:
    cleaned = []
    for item in holdings or []:
        company = str(item.get("company") or "").strip().upper()
        if not company:
            continue
        try:
            weight = float(item.get("weight", 0))
        except Exception:
            continue
        if weight > 0:
            cleaned.append((company, weight))
    if len(cleaned) < 2:
        return {"status": "At least two holdings are required.", "holdings": []}
    total = sum(w for _, w in cleaned)
    weights = {c: w / total for c, w in cleaned}

    try:
        tickers = [ticker_for(c) for c, _ in cleaned]
        frames = batch_history(tickers, period=STOCK_PERIOD, interval="1d", auto_adjust=False)
        close_series = {
            company: pd.to_numeric(frames[ticker]["Close"], errors="coerce")
            for (company, _), ticker in zip(cleaned, tickers)
            if ticker in frames and "Close" in frames[ticker]
        }
        if not close_series:
            return {"status": "No market data available for the portfolio."}
        close = pd.concat(close_series, axis=1)
        if close.empty:
            return {"status": "No market data available for the portfolio."}
        close = close.sort_index().dropna(how="all")
        returns = close.pct_change(fill_method=None)
        present = [c for c in weights if c in returns.columns]
        returns = returns[present].dropna(how="any")
        if len(present) < 2 or len(returns) < 60:
            return {"status": "Not enough overlapping market history for portfolio risk.", "data_points": len(returns)}
        w = np.array([weights[c] for c in present], dtype=float)
        w = w / w.sum()
        r = returns[present]
        cov = r.cov().to_numpy(dtype=float) * 252.0
        port_var = float(w @ cov @ w)
        port_vol = float(np.sqrt(max(port_var, 0)))
        daily_port = r.to_numpy() @ w
        wealth = pd.Series((1 + daily_port).cumprod(), index=r.index)
        running = wealth.cummax()
        drawdown = wealth / running - 1.0
        max_dd = float(drawdown.min())
        corr = r.corr().round(3).to_dict()
        marginal = cov @ w
        contribution = w * marginal
        contribution = contribution / port_var if port_var > 0 else np.zeros_like(w)
        positions = []
        for c, wt, contrib in zip(present, w, contribution):
            positions.append({"company": c, "weight": round(float(wt * 100), 2), "risk_contribution": round(float(contrib * 100), 2), "volatility": round(float(r[c].std() * np.sqrt(252) * 100), 2)})
        concentration = float(np.sum(w ** 2))
        losses = -pd.Series(daily_port).dropna()
        var95 = float(losses.quantile(0.95)) if not losses.empty else None
        expected_shortfall95 = float(losses[losses >= var95].mean()) if var95 is not None and bool((losses >= var95).any()) else None
        parity = _risk_parity_weights(cov)
        risk_parity = [
            {"company": company, "weight": round(float(weight * 100.0), 2)}
            for company, weight in zip(present, parity)
        ]
        return {
            "status": "ok",
            "data_points": int(len(r)),
            "portfolio_volatility_pct": round(port_vol * 100, 2),
            "max_drawdown_pct": round(max_dd * 100, 2),
            "concentration_hhi_pct": round(concentration * 100, 2),
            "historical_var_95_daily_pct": round(var95 * 100.0, 2) if var95 is not None else None,
            "historical_expected_shortfall_95_daily_pct": round(expected_shortfall95 * 100.0, 2) if expected_shortfall95 is not None else None,
            "holdings": positions,
            "correlation": corr,
            "risk_parity_reference": risk_parity,
            "calendar_policy": "Only overlapping return observations are used; missing market sessions are not converted into zero returns.",
            "warning": "Portfolio statistics and risk-parity weights are historical references. Correlations, volatility, and liquidity can change materially in stressed markets.",
        }
    except Exception as exc:
        return {"status": "Portfolio risk analysis unavailable.", "error": str(exc)}
