"""One canonical position-sizing implementation for every SolvAI workflow."""
from __future__ import annotations

import math
from typing import Any


ACTIVE_METHODS = {"fixed-fractional", "kelly", "half-kelly"}
REFERENCE_METHODS = {"volatility-targeting", "risk-parity", "r-multiple"}


def _finite(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def calculate_position_size(
    method: str,
    *,
    account_equity: float | None,
    entry_price: float,
    stop_price: float,
    requested_risk_pct: float = 1.0,
    target_r_multiple: float = 2.0,
    win_probability: float | None = None,
    resolved_paths: int = 0,
    lot_size: int = 1,
    max_cash_allocation_pct: float = 100.0,
) -> dict[str, Any]:
    key = method if method in ACTIVE_METHODS else "fixed-fractional"
    labels = {
        "fixed-fractional": "Fixed Fractional",
        "kelly": "Kelly Criterion · experimental",
        "half-kelly": "Half-Kelly · advanced",
    }
    equity = _finite(account_equity)
    has_equity = equity is not None and equity > 0
    equity_basis = float(equity) if has_equity else 100.0
    entry = _finite(entry_price)
    stop = _finite(stop_price)
    per_unit_risk = abs(entry - stop) if entry is not None and stop is not None else 0.0
    result: dict[str, Any] = {
        "key": key,
        "label": labels[key],
        "status": "ok" if has_equity else "normalized_only",
        "normalized_only": not has_equity,
        "position_units": None,
        "position_value": None,
        "planned_loss_amount": None,
        "planned_loss_pct_equity": None,
        "allocation_pct": None,
        "raw_allocation_pct": None,
        "requested_risk_pct": float(requested_risk_pct),
        "kelly_fraction_pct": None,
        "applied_kelly_fraction_pct": None,
        "cash_cap_applied": False,
        "lot_size": max(1, int(lot_size or 1)),
        "methodology": "",
        "limitation": "Add account equity to convert the allocation into currency and units.",
    }
    if entry is None or entry <= 0 or per_unit_risk <= 0:
        result.update(status="unavailable", limitation="A positive entry-to-stop distance is required.")
        return result

    raw_position_value = 0.0
    if key == "fixed-fractional":
        requested_loss = equity_basis * max(0.05, min(float(requested_risk_pct), 10.0)) / 100.0
        raw_position_value = requested_loss / per_unit_risk * entry
        result["methodology"] = "Risk budget = equity × risk %. Units = risk budget ÷ entry-to-stop distance."
        result["limitation"] = "Gaps, fees, taxes, and slippage can make realized loss exceed the planned amount."
    else:
        probability = _finite(win_probability)
        if probability is None or int(resolved_paths or 0) < 40:
            result.update(
                status="unavailable",
                limitation="At least 40 resolved historical paths are required before a Kelly reference is calculated.",
            )
            return result
        probability = max(0.0, min(1.0, probability))
        payoff = max(0.01, float(target_r_multiple))
        raw_kelly = (payoff * probability - (1.0 - probability)) / payoff
        positive = max(0.0, raw_kelly)
        fraction = positive * (0.5 if key == "half-kelly" else 1.0)
        # Unconditional historical paths are noisy.  Keep both modes cash-only
        # and bounded even when the mathematical Kelly result is very large.
        cap = 0.125 if key == "half-kelly" else 0.25
        applied = min(fraction, cap)
        result["kelly_fraction_pct"] = raw_kelly * 100.0
        result["applied_kelly_fraction_pct"] = applied * 100.0
        if applied <= 0:
            result.update(
                status="no_positive_edge",
                position_units=0.0,
                position_value=0.0,
                planned_loss_amount=0.0,
                planned_loss_pct_equity=0.0,
                allocation_pct=0.0,
                raw_allocation_pct=0.0,
                methodology="Kelly fraction = (R × win probability − loss probability) ÷ R.",
                limitation="The evidence-adjusted Kelly fraction is not positive, so the method withholds a position.",
            )
            return result
        raw_position_value = equity_basis * applied
        result["methodology"] = (
            "Kelly fraction uses the evidence-adjusted historical win rate and payoff; "
            + ("half is applied and capped at 12.5% cash." if key == "half-kelly" else "the result is capped at 25% cash.")
        )
        result["limitation"] = "Advanced reference only: historical first-touch odds may not match the current setup or future regime."

    cash_cap = equity_basis * max(0.0, min(float(max_cash_allocation_pct), 100.0)) / 100.0
    basis_value = min(max(0.0, raw_position_value), cash_cap)
    raw_units = basis_value / entry
    lot = result["lot_size"]
    if has_equity:
        rounded_units = math.floor(raw_units / lot) * lot
        rounded_value = rounded_units * entry
        planned_loss = rounded_units * per_unit_risk
    else:
        # A normalized percentage comparison must not be rounded to an exchange
        # lot against the artificial 100-unit equity basis. Lot rounding is only
        # meaningful after the user supplies real account equity.
        rounded_units = None
        rounded_value = basis_value
        planned_loss = raw_units * per_unit_risk
    result.update(
        position_units=float(rounded_units) if rounded_units is not None else None,
        position_value=rounded_value if has_equity else None,
        planned_loss_amount=planned_loss if has_equity else None,
        planned_loss_pct_equity=planned_loss / equity_basis * 100.0,
        allocation_pct=rounded_value / equity_basis * 100.0,
        raw_allocation_pct=raw_position_value / equity_basis * 100.0,
        cash_cap_applied=raw_position_value > cash_cap + 1e-9,
    )
    if not has_equity:
        result["limitation"] += " Add account equity for currency and exchange-lot units."
    return result
