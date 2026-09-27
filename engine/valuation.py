"""Transparent, assumption-driven equity valuation research.

The module deliberately keeps calculation logic separate from Flask and the
browser.  It never fabricates a missing input: unavailable methods are returned
with a reason and excluded from the blended value.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import math
from statistics import median

from .analysis import growth, latest, series
from .scenario_weighting import build_forward_driver_model, weight_scenarios
from .stock import market_snapshot, ticker_for


DEFAULT_ASSUMPTIONS = {
    "required_return_pct": 12.0,
    "near_growth_pct": None,
    "terminal_growth_pct": 4.0,
    "forecast_years": 5,
    "normalized_pe": 12.0,
    "margin_of_safety_pct": 20.0,
}

METHOD_WEIGHTS = {
    "dcf": 0.40,
    "pe": 0.30,
    "ddm": 0.15,
    "gordon": 0.05,
    "asset": 0.10,
}


def _finite(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _clamp(value, low, high):
    return max(low, min(high, value))


def _round(value, digits=2):
    value = _finite(value)
    return round(value, digits) if value is not None else None


def _unavailable(name, reason, weight, inputs=None, limitation=None):
    return {
        "name": name,
        "status": "unavailable",
        "value_per_share": None,
        "low": None,
        "high": None,
        "weight": weight,
        "inputs": inputs or [],
        "formula": None,
        "interpretation": reason,
        "limitations": [limitation or reason],
    }


def _available(name, value, low, high, weight, inputs, formula, interpretation, limitations):
    values = [x for x in (_finite(value), _finite(low), _finite(high)) if x is not None]
    if not values or value is None or value <= 0:
        return _unavailable(name, "The calculation did not produce a positive finite value.", weight, inputs)
    return {
        "name": name,
        "status": "available",
        "value_per_share": _round(value),
        "low": _round(min(values)),
        "high": _round(max(values)),
        "weight": weight,
        "inputs": inputs,
        "formula": formula,
        "interpretation": interpretation,
        "limitations": limitations,
    }


def _automatic_assumption_defaults(market):
    """Build conservative, visible defaults from provider metadata.

    This is deliberately not a hidden cost-of-capital model: without a verified
    risk-free curve and equity-risk premium, the currency anchor and bounded beta
    adjustment remain explicit research heuristics.
    """
    market = market if isinstance(market, dict) else {}
    currency = str(market.get("currency") or "VND").upper()
    beta = _finite(market.get("beta"))
    base_return = 12.0 if currency == "VND" else 9.0 if currency in {"USD", "EUR", "GBP"} else 10.0
    beta_adjustment = _clamp((beta - 1.0) * 1.5, -1.5, 3.0) if beta is not None else 0.0
    required_return = _clamp(base_return + beta_adjustment, 6.0, 20.0)
    terminal_growth = 4.0 if currency == "VND" else 2.5 if currency in {"USD", "EUR", "GBP"} else 3.0
    observed_multiples = [
        value for value in (_finite(market.get("pe")), _finite(market.get("forward_pe")))
        if value is not None and 3.0 <= value <= 40.0
    ]
    normalized_pe = _clamp(median(observed_multiples) * 0.90, 6.0, 25.0) if observed_multiples else 12.0
    return {
        "required_return_pct": required_return,
        "terminal_growth_pct": terminal_growth,
        "normalized_pe": normalized_pe,
        "sources": {
            "required_return_pct": f"Automatic {currency} research anchor" + (f" with bounded beta adjustment ({beta:.2f})" if beta is not None else ""),
            "terminal_growth_pct": f"Automatic conservative long-run {currency} growth anchor",
            "normalized_pe": "90% of the bounded provider trailing/forward P/E median" if observed_multiples else "Conservative fallback; no usable provider multiple",
        },
    }


def _parse_assumptions(raw, auto_growth_pct, market=None):
    raw = raw if isinstance(raw, dict) else {}
    automatic = _automatic_assumption_defaults(market)

    def number(name, default, low, high):
        supplied = raw.get(name, default)
        value = _finite(supplied)
        if value is None:
            value = default
        if value is None:
            return None
        return _clamp(value, low, high)

    required_return = number("required_return_pct", automatic["required_return_pct"], 5.0, 35.0)
    terminal_growth = number("terminal_growth_pct", automatic["terminal_growth_pct"], -5.0, 10.0)
    if terminal_growth >= required_return - 1.0:
        terminal_growth = required_return - 1.0

    near_raw = raw.get("near_growth_pct")
    near_growth = _finite(near_raw)
    growth_source = "User assumption"
    if near_growth is None:
        near_growth = _finite(auto_growth_pct)
        growth_source = "Auto-estimate from available earnings or verified revenue growth"
    if near_growth is None:
        near_growth = terminal_growth
        growth_source = "Terminal-growth fallback because no verified growth input was available"

    years = int(round(number("forecast_years", DEFAULT_ASSUMPTIONS["forecast_years"], 3, 10)))
    assumptions = {
        "required_return_pct": _round(required_return),
        "near_growth_pct": _round(_clamp(near_growth, -20.0, 30.0)),
        "terminal_growth_pct": _round(terminal_growth),
        "forecast_years": years,
        "normalized_pe": _round(number("normalized_pe", automatic["normalized_pe"], 3.0, 40.0)),
        "margin_of_safety_pct": _round(number("margin_of_safety_pct", DEFAULT_ASSUMPTIONS["margin_of_safety_pct"], 0.0, 50.0)),
        "growth_source": growth_source,
        "assumption_sources": {
            "required_return_pct": "User assumption" if _finite(raw.get("required_return_pct")) is not None else automatic["sources"]["required_return_pct"],
            "terminal_growth_pct": "User assumption" if _finite(raw.get("terminal_growth_pct")) is not None else automatic["sources"]["terminal_growth_pct"],
            "normalized_pe": "User assumption" if _finite(raw.get("normalized_pe")) is not None else automatic["sources"]["normalized_pe"],
        },
    }
    return assumptions


def _discounted_cashflow(cashflow_per_share, near_growth_pct, terminal_growth_pct, required_return_pct, years):
    cashflow_per_share = _finite(cashflow_per_share)
    if cashflow_per_share is None or cashflow_per_share <= 0:
        return None
    terminal = terminal_growth_pct / 100.0
    discount = required_return_pct / 100.0
    if discount <= terminal:
        return None
    present = 0.0
    projected = cashflow_per_share
    for year in range(1, int(years) + 1):
        # Growth fades toward the stable rate instead of remaining unrealistically
        # constant through the explicit forecast period.
        progress = year / (int(years) + 1.0)
        faded_growth = near_growth_pct + (terminal_growth_pct - near_growth_pct) * progress
        projected *= 1.0 + faded_growth / 100.0
        present += projected / ((1.0 + discount) ** year)
    terminal_value = projected * (1.0 + terminal) / (discount - terminal)
    return present + terminal_value / ((1.0 + discount) ** int(years))


def _gordon(dividend_per_share, growth_pct, required_return_pct):
    dividend = _finite(dividend_per_share)
    growth = growth_pct / 100.0
    discount = required_return_pct / 100.0
    if dividend is None or dividend <= 0 or discount <= growth:
        return None
    return dividend * (1.0 + growth) / (discount - growth)


def _input(label, value, unit="", source="", as_of=None):
    return {
        "label": label,
        "value": _round(value, 4),
        "unit": unit,
        "source": source,
        "as_of": str(as_of) if as_of else None,
    }


def _parse_timestamp(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _scenario_blend(label, description, inputs, adjustments):
    """Recalculate every usable method under one coherent scenario."""
    required = _clamp(inputs["required_return_pct"] + adjustments["return_delta"], 5.0, 35.0)
    near = _clamp(inputs["near_growth_pct"] + adjustments["near_delta"], -20.0, 30.0)
    terminal = _clamp(inputs["terminal_growth_pct"] + adjustments["terminal_delta"], -5.0, 10.0)
    terminal = min(terminal, required - 1.0)
    normalized_pe = _clamp(inputs["normalized_pe"] + adjustments["pe_delta"], 3.0, 40.0)
    years = inputs["forecast_years"]

    values = []
    if inputs["free_cash_flow"] is not None and inputs["free_cash_flow"] > 0 and inputs["shares"] is not None and inputs["shares"] > 0:
        dcf = _discounted_cashflow(inputs["free_cash_flow"] / inputs["shares"], near, terminal, required, years)
        if dcf is not None:
            values.append(("Equity DCF", dcf, METHOD_WEIGHTS["dcf"]))
    if inputs["eps"] is not None and inputs["eps"] > 0:
        values.append(("P/E earnings value", inputs["eps"] * normalized_pe, METHOD_WEIGHTS["pe"]))
    if inputs["dividend"] is not None and inputs["dividend"] > 0:
        ddm = _discounted_cashflow(inputs["dividend"], near, terminal, required, years)
        gordon = _gordon(inputs["dividend"], terminal, required)
        if ddm is not None:
            values.append(("Two-stage DDM", ddm, METHOD_WEIGHTS["ddm"]))
        if gordon is not None:
            values.append(("Gordon growth value", gordon, METHOD_WEIGHTS["gordon"]))
    if inputs["book_value_per_share"] is not None and inputs["book_value_per_share"] > 0:
        asset_value = inputs["book_value_per_share"] * adjustments["asset_multiple"]
        values.append(("Asset-based reference", asset_value, METHOD_WEIGHTS["asset"]))

    weight = sum(row[2] for row in values)
    fair = sum(value * method_weight for _, value, method_weight in values) / weight if weight else None
    fair = _round(fair)
    entry = _round(fair * (1.0 - inputs["margin_of_safety_pct"] / 100.0)) if fair else None
    price = inputs["price"]
    price_gap = _round((fair / price - 1.0) * 100.0) if fair and price and price > 0 else None
    return {
        "key": label.lower(),
        "label": label,
        "description": description,
        "fair_value": fair,
        "research_entry_price": entry,
        "upside_downside_pct": price_gap,
        "method_coverage": len(values),
        "assumptions": {
            "required_return_pct": _round(required),
            "near_growth_pct": _round(near),
            "terminal_growth_pct": _round(terminal),
            "normalized_pe": _round(normalized_pe),
            "asset_value_multiple": _round(adjustments["asset_multiple"]),
        },
        "method_values": [
            {"name": name, "value_per_share": _round(value)} for name, value, _ in values
        ],
    }


def _build_scenarios(parsed, price, shares, fcf, eps, dividend, book_share):
    scenario_inputs = {
        **parsed,
        "price": price,
        "shares": shares,
        "free_cash_flow": fcf,
        "eps": eps,
        "dividend": dividend,
        "book_value_per_share": book_share,
    }
    return [
        _scenario_blend(
            "Bear",
            "Slower growth, a higher required return, a lower earnings multiple, and an asset-value haircut.",
            scenario_inputs,
            {"near_delta": -3.0, "terminal_delta": -1.0, "return_delta": 2.0, "pe_delta": -2.0, "asset_multiple": 0.80},
        ),
        _scenario_blend(
            "Base",
            "The visible assumptions selected for this valuation run.",
            scenario_inputs,
            {"near_delta": 0.0, "terminal_delta": 0.0, "return_delta": 0.0, "pe_delta": 0.0, "asset_multiple": 1.00},
        ),
        _scenario_blend(
            "Bull",
            "Stronger growth, a lower required return, a higher earnings multiple, and modest asset-value recognition.",
            scenario_inputs,
            {"near_delta": 3.0, "terminal_delta": 1.0, "return_delta": -1.5, "pe_delta": 2.0, "asset_multiple": 1.10},
        ),
    ]


def _dcf_sensitivity(fcf, shares, parsed):
    if fcf is None or fcf <= 0 or shares is None or shares <= 0:
        return {
            "status": "unavailable",
            "metric": "Equity DCF per share",
            "reason": "Positive free cash flow and shares outstanding are required.",
            "columns": [],
            "rows": [],
        }
    return_deltas = (2.0, 0.0, -2.0)
    growth_deltas = (-2.0, 0.0, 2.0)
    columns = [_round(_clamp(parsed["required_return_pct"] + delta, 5.0, 35.0)) for delta in return_deltas]
    rows = []
    for growth_delta in growth_deltas:
        near = _clamp(parsed["near_growth_pct"] + growth_delta, -20.0, 30.0)
        values = []
        for required in columns:
            terminal = min(parsed["terminal_growth_pct"], required - 1.0)
            values.append(_round(_discounted_cashflow(fcf / shares, near, terminal, required, parsed["forecast_years"])))
        rows.append({"near_growth_pct": _round(near), "values": values})
    return {
        "status": "available",
        "metric": "Equity DCF per share",
        "columns": columns,
        "rows": rows,
        "note": "Rows change near-term growth; columns change required return. Stable growth and forecast years remain at the visible base assumptions.",
    }


def _quality_assessment(coverage, dispersion_pct, market_updated_at, manual_fields):
    coverage_pct = coverage / 5.0 * 100.0
    agreement_pct = 25.0 if coverage < 2 or dispersion_pct is None else _clamp(100.0 - dispersion_pct, 0.0, 100.0)
    timestamp = _parse_timestamp(market_updated_at)
    age_days = None
    if timestamp is not None:
        age_days = max(0.0, (datetime.now(timezone.utc) - timestamp).total_seconds() / 86400.0)
        freshness_pct = 100.0 if age_days <= 1 else 85.0 if age_days <= 7 else 65.0 if age_days <= 30 else 40.0 if age_days <= 90 else 20.0
    else:
        freshness_pct = 25.0
    traceability_pct = 70.0 if manual_fields else 100.0
    score = round(coverage_pct * 0.40 + agreement_pct * 0.30 + freshness_pct * 0.20 + traceability_pct * 0.10)
    label = "High" if score >= 80 else "Moderate" if score >= 55 else "Low"
    warnings = []
    if coverage < 3:
        warnings.append("Fewer than three methods are available, so triangulation is limited.")
    if dispersion_pct is not None and dispersion_pct >= 60:
        warnings.append("The valuation methods disagree widely; use the scenario range instead of a single midpoint.")
    if timestamp is None:
        warnings.append("The market provider did not return a usable update timestamp.")
    elif age_days is not None and age_days > 7:
        warnings.append(f"Market information is approximately {age_days:.0f} days old.")
    if manual_fields:
        warnings.append("Manual values are labelled but cannot be independently verified by SolvAI.")
    return {
        "score": score,
        "label": label,
        "components": {
            "method_coverage_pct": _round(coverage_pct),
            "method_agreement_pct": _round(agreement_pct),
            "market_freshness_pct": _round(freshness_pct),
            "input_traceability_pct": _round(traceability_pct),
        },
        "market_age_days": _round(age_days, 1),
        "warnings": warnings,
        "explanation": "Confidence combines method coverage (40%), agreement (30%), market freshness (20%), and input traceability (10%). It measures evidence quality, not the probability of an investment gain.",
    }


def _historical_yoy_rates(rows, limit=4):
    """Return recent like-for-like yearly growth rates from verified observations."""
    clean = []
    for row in rows or []:
        try:
            period = date.fromisoformat(str(row.get("period_end") or "")[:10])
            value = float(row.get("value"))
        except (TypeError, ValueError):
            continue
        if math.isfinite(value) and value > 0:
            clean.append((period, value))
    by_period = {(period.year, period.month, period.day): value for period, value in clean}
    rates = []
    for period, value in sorted(clean):
        prior = by_period.get((period.year - 1, period.month, period.day))
        if prior and prior > 0:
            rates.append((period, (value / prior - 1.0) * 100.0))
    return [rate for _, rate in rates[-limit:]]


def _parse_holding_inputs(raw):
    raw = raw if isinstance(raw, dict) else {}
    shares_held = _finite(raw.get("shares_held"))
    average_cost = _finite(raw.get("average_cost_per_share"))
    horizon = _finite(raw.get("horizon_years"))
    horizon = int(round(horizon)) if horizon is not None else 5
    reinvest = raw.get("reinvest_dividends", False)
    if isinstance(reinvest, str):
        reinvest = reinvest.strip().lower() in {"1", "true", "yes", "on"}
    return {
        "shares_held": _round(_clamp(shares_held, 0.0, 1_000_000_000.0), 4) if shares_held is not None and shares_held >= 0 else None,
        "average_cost_per_share": _round(average_cost, 4) if average_cost is not None and average_cost > 0 else None,
        "horizon_years": int(_clamp(horizon, 3, 10)),
        "reinvest_dividends": bool(reinvest),
    }


def _normalized_holding_growth(market, parsed, local_growth, revenue_history, data_quality):
    """Blend independent growth evidence, cap outliers, then shrink toward stable growth."""
    evidence = []

    def add(label, value, weight, source, low=-10.0, high=20.0):
        number = _finite(value)
        if number is None:
            return
        evidence.append({
            "label": label,
            "value_pct": _round(number),
            "normalized_pct": _round(_clamp(number, low, high)),
            "weight": weight,
            "source": source,
        })

    provider = market.get("source") or "Market provider"
    add("Earnings growth", market.get("earnings_growth_pct"), 0.30, provider, -15.0, 25.0)
    add("Revenue growth", market.get("revenue_growth_pct"), 0.20, provider)
    add("Verified report growth", local_growth, 0.20, "Latest comparable local report")
    historical_rates = _historical_yoy_rates(revenue_history)
    if historical_rates:
        add(
            "Multi-period revenue growth",
            median(historical_rates),
            0.15,
            f"Median of {len(historical_rates)} verified like-for-like periods",
        )
    roe = _finite(market.get("return_on_equity_pct"))
    payout = _finite(market.get("payout_ratio_pct"))
    if roe is not None and roe > 0 and payout is not None and 0 <= payout <= 100:
        add("Sustainable growth", roe * (1.0 - payout / 100.0), 0.15, "ROE × earnings retention", 0.0, 20.0)

    if evidence:
        total_weight = sum(row["weight"] for row in evidence)
        raw_growth = sum(row["normalized_pct"] * row["weight"] for row in evidence) / total_weight
    else:
        raw_growth = parsed["near_growth_pct"]
        evidence.append({
            "label": "Valuation growth assumption",
            "value_pct": _round(raw_growth),
            "normalized_pct": _round(raw_growth),
            "weight": 1.0,
            "source": parsed["growth_source"],
        })
    quality = _clamp((_finite((data_quality or {}).get("score")) or 0.0) / 100.0, 0.0, 1.0)
    shrinkage_strength = _clamp(0.40 + quality * 0.35 + min(0.10, max(0, len(evidence) - 1) * 0.025), 0.40, 0.85)
    stable = parsed["terminal_growth_pct"]
    normalized = stable + (raw_growth - stable) * shrinkage_strength
    normalized = _clamp(normalized, -8.0, 18.0)
    return {
        "base_growth_pct": _round(normalized),
        "raw_blended_growth_pct": _round(raw_growth),
        "stable_growth_pct": _round(stable),
        "evidence_strength_pct": _round(shrinkage_strength * 100.0),
        "evidence": evidence,
        "method": "Available growth evidence is capped, weighted, and shrunk toward stable growth. Each scenario then fades annually toward its stable rate.",
    }


def _long_holding_outlook(
    market, parsed, scenarios, data_quality, local_growth, revenue_history,
    fcf, shares_outstanding, eps, dividend, currency, holding_inputs,
):
    holding = _parse_holding_inputs(holding_inputs)
    horizon = holding["horizon_years"]
    price = _finite(market.get("price"))
    if price is None or price <= 0:
        return {
            "status": "unavailable",
            "reason": "A current market price is required to calculate a holding-period return.",
            "user_inputs": holding,
            "scenarios": [],
        }

    growth_model = _normalized_holding_growth(
        market, parsed, local_growth, revenue_history, data_quality
    )
    base_growth = growth_model["base_growth_pct"]
    fcf_per_share = fcf / shares_outstanding if fcf is not None and fcf > 0 and shares_outstanding is not None and shares_outstanding > 0 else None
    scenario_growth_delta = {"bear": -4.0, "base": 0.0, "bull": 3.0}
    rows = []
    for scenario in scenarios or []:
        key = str(scenario.get("key") or "").lower()
        assumptions = scenario.get("assumptions") or {}
        start_growth = _clamp(base_growth + scenario_growth_delta.get(key, 0.0), -12.0, 22.0)
        stable_growth = _finite(assumptions.get("terminal_growth_pct"))
        stable_growth = parsed["terminal_growth_pct"] if stable_growth is None else stable_growth
        required_return = _finite(assumptions.get("required_return_pct")) or parsed["required_return_pct"]
        terminal_pe = _finite(assumptions.get("normalized_pe")) or parsed["normalized_pe"]
        projected_eps = eps
        projected_fcf = fcf_per_share
        projected_dividend = max(0.0, dividend or 0.0)
        cash_dividends = 0.0
        share_units = 1.0
        growth_path = []
        annual_rows = []

        for year in range(1, horizon + 1):
            progress = year / horizon
            annual_growth = start_growth + (stable_growth - start_growth) * progress
            annual_growth = _clamp(annual_growth, -15.0, 25.0)
            if projected_eps is not None and projected_eps > 0:
                projected_eps *= 1.0 + annual_growth / 100.0
            if projected_fcf is not None and projected_fcf > 0:
                projected_fcf *= 1.0 + annual_growth / 100.0
            dividend_growth = _clamp(annual_growth, -10.0, 8.0)
            projected_dividend *= 1.0 + dividend_growth / 100.0
            growth_path.append(_round(annual_growth))
            annual_rows.append({
                "year": year,
                "growth_pct": _round(annual_growth),
                "dividend_per_share": _round(projected_dividend, 4),
            })

        value_components = []
        if projected_eps is not None and projected_eps > 0:
            value_components.append(("Projected EPS × terminal P/E", projected_eps * terminal_pe, 0.45))
        terminal_rate = stable_growth / 100.0
        discount_rate = required_return / 100.0
        if projected_fcf is not None and projected_fcf > 0 and discount_rate > terminal_rate:
            terminal_fcf_value = projected_fcf * (1.0 + terminal_rate) / (discount_rate - terminal_rate)
            value_components.append(("Terminal FCF capitalization", terminal_fcf_value, 0.55))
        if value_components:
            component_weight = sum(component[2] for component in value_components)
            terminal_price = sum(value * weight for _, value, weight in value_components) / component_weight
            terminal_basis = " + ".join(name for name, _, _ in value_components)
        else:
            scenario_value = _finite(scenario.get("fair_value"))
            if scenario_value is None or scenario_value <= 0:
                continue
            terminal_price = scenario_value * ((1.0 + stable_growth / 100.0) ** horizon)
            terminal_basis = "Scenario fair value grown at the stable rate because EPS and FCF/share were unavailable"

        for annual in annual_rows:
            year = annual["year"]
            if terminal_price > 0:
                reference_price = price * ((terminal_price / price) ** (year / horizon))
            else:
                reference_price = price
            paid = annual["dividend_per_share"] * share_units
            if holding["reinvest_dividends"] and reference_price > 0:
                share_units += paid / reference_price
            else:
                cash_dividends += paid
            annual["modeled_price"] = _round(reference_price)
            annual["share_units_per_starting_share"] = _round(share_units, 6)

        terminal_wealth = terminal_price * share_units + cash_dividends
        total_return = (terminal_wealth / price - 1.0) * 100.0
        annualized = ((terminal_wealth / price) ** (1.0 / horizon) - 1.0) * 100.0 if terminal_wealth > 0 else None
        shares_held = holding["shares_held"]
        average_cost = holding["average_cost_per_share"]
        portfolio_value = terminal_wealth * shares_held if shares_held is not None else None
        starting_cost = average_cost * shares_held if average_cost is not None and shares_held is not None else None
        gain_on_cost = (portfolio_value / starting_cost - 1.0) * 100.0 if portfolio_value is not None and starting_cost and starting_cost > 0 else None
        rows.append({
            "key": key,
            "label": scenario.get("label") or key.title(),
            "research_weight_pct": _round(scenario.get("research_weight_pct")),
            "starting_growth_pct": _round(start_growth),
            "stable_growth_pct": _round(stable_growth),
            "terminal_price_per_share": _round(terminal_price),
            "cash_dividends_per_share": _round(cash_dividends, 4),
            "ending_shares_per_starting_share": _round(share_units, 6),
            "terminal_wealth_per_starting_share": _round(terminal_wealth),
            "total_return_pct": _round(total_return),
            "annualized_return_pct": _round(annualized),
            "portfolio_value": _round(portfolio_value),
            "gain_on_cost_pct": _round(gain_on_cost),
            "terminal_basis": terminal_basis,
            "growth_path_pct": growth_path,
            "path": annual_rows,
        })

    valid_weight = sum((_finite(row.get("research_weight_pct")) or 0.0) for row in rows)
    weighted_wealth = (
        sum(row["terminal_wealth_per_starting_share"] * row["research_weight_pct"] for row in rows) / valid_weight
        if rows and valid_weight else None
    )
    weighted_return = (weighted_wealth / price - 1.0) * 100.0 if weighted_wealth is not None else None
    weighted_annualized = ((weighted_wealth / price) ** (1.0 / horizon) - 1.0) * 100.0 if weighted_wealth and weighted_wealth > 0 else None
    shares_held = holding["shares_held"]
    return {
        "status": "available" if rows else "unavailable",
        "horizon_years": horizon,
        "currency": currency,
        "current_price": _round(price),
        "user_inputs": holding,
        "growth_model": growth_model,
        "scenarios": rows,
        "weighted": {
            "terminal_wealth_per_starting_share": _round(weighted_wealth),
            "total_return_pct": _round(weighted_return),
            "annualized_return_pct": _round(weighted_annualized),
            "portfolio_value": _round(weighted_wealth * shares_held) if weighted_wealth is not None and shares_held is not None else None,
        },
        "method": "Projects EPS and FCF/share through an annually fading growth path, estimates terminal value from normalized P/E and FCF capitalization, then adds or reinvests modeled dividends.",
        "warning": "This is a scenario model, not a price forecast or calibrated probability. Taxes, fees, dilution, liquidity, and unexpected business changes are excluded.",
    }


def _investment_plan(price, fair_value, fair_low, fair_high, entry_price, entry_low, dividend, currency, zone):
    overvaluation = _round(fair_high * 1.10) if fair_high else None
    horizon_years = 3
    total_return = None
    annualized = None
    if price and price > 0 and fair_value:
        terminal_value = fair_value + max(0.0, dividend or 0.0) * horizon_years
        total_return = _round((terminal_value / price - 1.0) * 100.0)
        if terminal_value > 0:
            annualized = _round(((terminal_value / price) ** (1.0 / horizon_years) - 1.0) * 100.0)
    return {
        "currency": currency,
        "current_price": _round(price),
        "deep_value_threshold": entry_low,
        "preferred_entry_threshold": entry_price,
        "fair_range_low": fair_low,
        "fair_value": fair_value,
        "fair_range_high": fair_high,
        "overvaluation_threshold": overvaluation,
        "zone": zone,
        "three_year_total_return_pct": total_return,
        "three_year_annualized_return_pct": annualized,
        "return_basis": "Illustrative return to the base fair value plus three years of the current annual dividend; taxes, reinvestment, trading costs, and dividend changes are excluded.",
        "outlooks": [
            {"period": "0–12 months", "title": "Price discovery", "comment": "Use the scenario range and upcoming reports; short-term price movement is not forecast by the valuation model."},
            {"period": "1–3 years", "title": "Fundamental delivery", "comment": "Track whether earnings, free cash flow, and dividends remain consistent with the base assumptions."},
            {"period": "3–5 years", "title": "Long-horizon review", "comment": "Retain the research thesis only while business quality and capital allocation support the modeled value."},
        ],
        "review_triggers": [
            "Material earnings or free-cash-flow revision",
            "Share issuance, buyback, or capital-structure change",
            "Dividend policy or payment-schedule change",
            "Required-return or long-run growth assumption change",
        ],
    }


def infer_dividend_schedule(payments):
    """Infer cadence and a broad next window; never call it a declared date."""
    clean = []
    for item in payments or []:
        raw_date = item.get("date") if isinstance(item, dict) else None
        amount = _finite(item.get("amount")) if isinstance(item, dict) else None
        try:
            paid = date.fromisoformat(str(raw_date)[:10])
        except (TypeError, ValueError):
            continue
        if amount is not None and amount > 0:
            clean.append((paid, amount))
    clean.sort(key=lambda row: row[0])
    if len(clean) < 2:
        return {
            "status": "unavailable",
            "cadence": "Insufficient payment history",
            "last_payment_date": clean[-1][0].isoformat() if clean else None,
            "next_estimated_window": None,
            "note": "At least two historical payments are required to infer a cadence.",
        }

    intervals = [(b[0] - a[0]).days for a, b in zip(clean, clean[1:]) if 14 <= (b[0] - a[0]).days <= 500]
    if not intervals:
        return {
            "status": "unavailable",
            "cadence": "Irregular",
            "last_payment_date": clean[-1][0].isoformat(),
            "next_estimated_window": None,
            "note": "Historical payments are too irregular to estimate a useful window.",
        }
    days = float(median(intervals[-8:]))
    if days <= 45:
        cadence = "Monthly"
    elif days <= 125:
        cadence = "Quarterly"
    elif days <= 230:
        cadence = "Semiannual"
    elif days <= 410:
        cadence = "Annual"
    else:
        cadence = "Irregular"
    last_date = clean[-1][0]
    center = last_date + timedelta(days=round(days))
    buffer_days = max(14, min(45, round(days * 0.15)))
    return {
        "status": "estimated" if cadence != "Irregular" else "unavailable",
        "payment_count": len(clean),
        "cadence": cadence,
        "median_interval_days": round(days),
        "last_payment_date": last_date.isoformat(),
        "last_payment_per_share": _round(clean[-1][1], 4),
        "next_estimated_window": {
            "from": (center - timedelta(days=buffer_days)).isoformat(),
            "to": (center + timedelta(days=buffer_days)).isoformat(),
        } if cadence != "Irregular" else None,
        "note": "This window is inferred from historical payments; it is not a board-declared dividend date.",
    }


def _dividend_outlook(market, schedule, price):
    dividend = _finite(market.get("dividend_rate"))
    yield_pct = _finite(market.get("dividend_yield_pct"))
    if yield_pct is None and dividend is not None and price not in (None, 0):
        yield_pct = dividend / price * 100.0
    return {
        "annual_dividend_per_share": _round(dividend, 4),
        "trailing_yield_pct": _round(yield_pct),
        "payout_ratio_pct": _round(_finite(market.get("payout_ratio_pct"))),
        "ex_dividend_date": market.get("ex_dividend_date"),
        "schedule": schedule,
        "source": market.get("source") or "Market provider",
        "warning": "Dividend amounts and timing can change or be cancelled. Verify any declared event with the issuer or exchange.",
    }


def value_company(
    company,
    assumptions=None,
    market_data=None,
    manual_inputs=None,
    forward_drivers=None,
    holding_inputs=None,
):
    """Return per-share estimates from independent valuation lenses."""
    company = str(company or "").strip().upper()
    market = dict(market_data or market_snapshot(company, include_dividends=True))
    generated = datetime.now(timezone.utc).isoformat()
    market_as_of = market.get("updated_at")
    manual_inputs = manual_inputs if isinstance(manual_inputs, dict) else {}
    manual_fields = []
    for field in (
        "price", "shares_outstanding", "free_cash_flow", "eps",
        "dividend_rate", "book_value_per_share",
    ):
        supplied = _finite(manual_inputs.get(field))
        if supplied is not None and supplied > 0:
            market[field] = supplied
            manual_fields.append(field)
    currency_override = str(manual_inputs.get("currency") or "").strip().upper()
    if currency_override.isalpha() and 3 <= len(currency_override) <= 5:
        market["currency"] = currency_override
        manual_fields.append("currency")
    if manual_fields:
        market["source"] = "User-provided override (not saved) + " + (market.get("source") or "market provider")

    def input_source(field, fallback):
        return "User-provided override (not saved)" if field in manual_fields else fallback

    def input_as_of(field, fallback):
        return generated if field in manual_fields else fallback

    price = _finite(market.get("price"))
    shares = _finite(market.get("shares_outstanding"))

    local_revenue_growth = growth(company, "revenue")
    try:
        revenue_history = series(company, "revenue")
    except Exception:
        # Valuation can still use provider evidence when a local report database
        # has not been initialized yet (for example, a fresh normal-test install).
        revenue_history = []
    local_growth_row = latest(company, "revenue")
    earnings_growth_pct = _finite(market.get("earnings_growth_pct"))
    auto_growth = earnings_growth_pct if earnings_growth_pct is not None else local_revenue_growth
    growth_as_of = market_as_of if earnings_growth_pct is not None else (
        local_growth_row.get("period_end") if isinstance(local_growth_row, dict) else None
    )
    parsed = _parse_assumptions(assumptions, auto_growth, market)
    r = parsed["required_return_pct"]
    near = parsed["near_growth_pct"]
    terminal = parsed["terminal_growth_pct"]
    years = parsed["forecast_years"]

    currency = market.get("currency") or "VND"
    schedule = infer_dividend_schedule(market.get("dividend_history"))
    methods = []

    # 1) Equity DCF: discount cash available to equity at the required return.
    fcf = _finite(market.get("free_cash_flow"))
    fcf_source = "Provider free cash flow"
    if fcf is None:
        operating = _finite(market.get("operating_cash_flow"))
        capex = _finite(market.get("capital_expenditure"))
        if operating is not None and capex is not None:
            fcf = operating - abs(capex)
            fcf_source = "Provider operating cash flow less capital expenditure"
    dcf_inputs = [
        _input("Free cash flow", fcf, currency, input_source("free_cash_flow", fcf_source), input_as_of("free_cash_flow", market_as_of)),
        _input("Shares outstanding", shares, "shares", input_source("shares_outstanding", "Market provider"), input_as_of("shares_outstanding", market_as_of)),
        _input("Near-term growth", near, "%", parsed["growth_source"], growth_as_of),
        _input("Required return", r, "%", parsed["assumption_sources"]["required_return_pct"]),
        _input("Terminal growth", terminal, "%", parsed["assumption_sources"]["terminal_growth_pct"]),
        _input("Forecast horizon", years, "years", "Analyst assumption"),
    ]
    if fcf is not None and fcf > 0 and shares is not None and shares > 0:
        fcf_share = fcf / shares
        dcf_value = _discounted_cashflow(fcf_share, near, terminal, r, years)
        dcf_low = _discounted_cashflow(fcf_share, near - 2.0, terminal - 1.0, min(35.0, r + 2.0), years)
        dcf_high = _discounted_cashflow(fcf_share, near + 2.0, min(terminal + 1.0, r - 1.0), max(5.0, r - 2.0), years)
        methods.append(_available(
            "Equity DCF", dcf_value, dcf_low, dcf_high, METHOD_WEIGHTS["dcf"], dcf_inputs,
            "PV of projected FCF/share + PV of terminal value; terminal value = FCF(n+1) ÷ (required return − stable growth).",
            "Estimates the present value of future cash flow available to shareholders.",
            ["Provider free cash flow can be volatile and may use a different fiscal basis than the local reports.", "Terminal value is highly sensitive to required return and stable growth."],
        ))
    else:
        methods.append(_unavailable(
            "Equity DCF", "Positive free cash flow and shares outstanding are required.", METHOD_WEIGHTS["dcf"], dcf_inputs,
            "SolvAI does not substitute EBITDA or accounting profit for missing free cash flow.",
        ))

    # 2) Earnings multiple.
    eps = _finite(market.get("eps"))
    target_pe = parsed["normalized_pe"]
    pe_inputs = [_input("Trailing EPS", eps, currency + "/share", input_source("eps", "Market provider"), input_as_of("eps", market_as_of)), _input("Normalized P/E", target_pe, "×", parsed["assumption_sources"]["normalized_pe"])]
    if eps is not None and eps > 0:
        methods.append(_available(
            "P/E earnings value", eps * target_pe, eps * max(3.0, target_pe - 2.0), eps * min(40.0, target_pe + 2.0), METHOD_WEIGHTS["pe"], pe_inputs,
            "Trailing EPS × normalized P/E multiple.",
            "Shows the price implied by normalized earnings and the selected valuation multiple.",
            ["The selected P/E is an assumption, not an observed peer median.", "Trailing EPS can include one-off gains or losses."],
        ))
    else:
        methods.append(_unavailable("P/E earnings value", "A positive trailing EPS is required.", METHOD_WEIGHTS["pe"], pe_inputs))

    # 3) Two-stage dividend discount model.
    dividend = _finite(market.get("dividend_rate"))
    dividend_inputs = [
        _input("Annual dividend/share", dividend, currency + "/share", input_source("dividend_rate", "Market provider"), input_as_of("dividend_rate", market_as_of)),
        _input("Near-term dividend growth", near, "%", parsed["growth_source"], growth_as_of),
        _input("Stable growth", terminal, "%", parsed["assumption_sources"]["terminal_growth_pct"]),
        _input("Required return", r, "%", parsed["assumption_sources"]["required_return_pct"]),
        _input("Stage 1", years, "years", "Analyst assumption"),
    ]
    payout_ratio = _finite(market.get("payout_ratio_pct"))
    dividend_supported = (
        "dividend_rate" in manual_fields
        or int(schedule.get("payment_count") or 0) >= 3
        or (payout_ratio is not None and 0.0 < payout_ratio <= 150.0)
    )
    stable_dividend_supported = (
        "dividend_rate" in manual_fields
        or (
            schedule.get("status") == "estimated"
            and int(schedule.get("payment_count") or 0) >= 3
            and schedule.get("cadence") in {"Quarterly", "Semiannual", "Annual"}
        )
    )
    if dividend is not None and dividend > 0 and dividend_supported:
        ddm_value = _discounted_cashflow(dividend, near, terminal, r, years)
        ddm_low = _discounted_cashflow(dividend, near - 2.0, terminal - 1.0, min(35.0, r + 2.0), years)
        ddm_high = _discounted_cashflow(dividend, near + 2.0, min(terminal + 1.0, r - 1.0), max(5.0, r - 2.0), years)
        methods.append(_available(
            "Two-stage DDM", ddm_value, ddm_low, ddm_high, METHOD_WEIGHTS["ddm"], dividend_inputs,
            "PV of forecast dividends during stage 1 + PV of a Gordon terminal value.",
            "Values the stock from dividends during a near-growth stage and a stable-growth stage.",
            ["Best suited to companies with a durable dividend policy.", "Dividend growth is assumed; future distributions are not guaranteed."],
        ))
        if stable_dividend_supported:
            gordon_value = _gordon(dividend, terminal, r)
            gordon_low = _gordon(dividend, terminal - 1.0, min(35.0, r + 2.0))
            gordon_high = _gordon(dividend, min(terminal + 1.0, r - 1.0), max(5.0, r - 2.0))
            methods.append(_available(
                "Gordon growth value", gordon_value, gordon_low, gordon_high, METHOD_WEIGHTS["gordon"], dividend_inputs,
                "Next annual dividend ÷ (required return − stable dividend growth).",
                "A stable-growth cross-check for mature dividend-paying companies.",
                ["Not appropriate when dividends are irregular or growth is not stable.", "The estimate becomes unstable when required return approaches growth."],
            ))
        else:
            methods.append(_unavailable(
                "Gordon growth value", "A repeatable dividend cadence is required for a perpetual-growth cross-check.", METHOD_WEIGHTS["gordon"], dividend_inputs,
                "A positive indicated dividend alone does not establish a durable perpetual distribution policy.",
            ))
    else:
        reason = "A positive annual dividend per share and evidence of a repeatable distribution policy are required."
        methods.append(_unavailable("Two-stage DDM", reason, METHOD_WEIGHTS["ddm"], dividend_inputs))
        methods.append(_unavailable("Gordon growth value", reason, METHOD_WEIGHTS["gordon"], dividend_inputs))

    # 4) Book-value / asset reference. Prefer verified consolidated equity.
    equity_row = latest(company, "equity")
    equity = _finite(equity_row.get("value")) if isinstance(equity_row, dict) else None
    if "book_value_per_share" in manual_fields:
        book_share = _finite(market.get("book_value_per_share"))
        book_source = input_source("book_value_per_share", "Market provider book value/share")
    elif equity is not None and equity > 0 and shares is not None and shares > 0:
        book_share = equity / shares
        book_source = "Verified consolidated equity ÷ shares outstanding"
    else:
        book_share = _finite(market.get("book_value_per_share"))
        book_source = "Market provider book value/share"
    asset_inputs = [
        _input("Consolidated equity", equity, currency, "Verified local report", equity_row.get("period_end") if isinstance(equity_row, dict) else None),
        _input("Shares outstanding", shares, "shares", input_source("shares_outstanding", "Market provider"), input_as_of("shares_outstanding", market_as_of)),
        _input("Book value/share", book_share, currency + "/share", book_source, input_as_of("book_value_per_share", equity_row.get("period_end") if isinstance(equity_row, dict) and equity is not None else market_as_of)),
    ]
    if book_share is not None and book_share > 0:
        methods.append(_available(
            "Asset-based reference", book_share, book_share * 0.70, book_share, METHOD_WEIGHTS["asset"], asset_inputs,
            "Verified equity attributable to shareholders ÷ shares outstanding.",
            "A balance-sheet reference value rather than an earnings or cash-flow forecast.",
            ["Book value is not liquidation value and may not capture intangible assets or off-balance-sheet obligations.", "Asset quality and recoverability require separate due diligence."],
        ))
    else:
        methods.append(_unavailable("Asset-based reference", "Positive book value per share is required.", METHOD_WEIGHTS["asset"], asset_inputs))

    available = [method for method in methods if method["status"] == "available"]
    raw_weight = sum(method["weight"] for method in available)
    for method in methods:
        method["applied_weight_pct"] = _round(method["weight"] / raw_weight * 100.0) if method in available and raw_weight else 0.0
    fair_value = sum(method["value_per_share"] * method["weight"] for method in available) / raw_weight if raw_weight else None
    low = sum(method["low"] * method["weight"] for method in available) / raw_weight if raw_weight else None
    high = sum(method["high"] * method["weight"] for method in available) / raw_weight if raw_weight else None
    fair_value = _round(fair_value)
    fair_low = _round(min(low, high)) if low is not None and high is not None else None
    fair_high = _round(max(low, high)) if low is not None and high is not None else None
    entry_price = _round(fair_value * (1.0 - parsed["margin_of_safety_pct"] / 100.0)) if fair_value else None
    entry_low = _round(fair_low * (1.0 - parsed["margin_of_safety_pct"] / 100.0)) if fair_low else None
    upside_pct = _round((fair_value / price - 1.0) * 100.0) if fair_value and price and price > 0 else None
    method_values = [method["value_per_share"] for method in available]
    method_dispersion_pct = _round((max(method_values) - min(method_values)) / fair_value * 100.0) if fair_value and len(method_values) >= 2 else None

    if fair_value is None:
        zone = "insufficient_data"
        headline = "Not enough verified inputs for a blended core-value estimate"
        action = "Add current cash-flow, share, earnings, dividend, or book-value evidence and recalculate."
        holding = "No holding horizon is estimated while core value is unavailable."
    elif price is None:
        zone = "no_market_price"
        headline = "Core value estimated; current market price is unavailable"
        action = f"Use the modeled entry level at or below {entry_price:,.2f} {currency} only as a research threshold."
        holding = "3–5 year research horizon; review after each quarterly/annual report and every dividend decision."
    elif price <= entry_price:
        zone = "research_entry"
        headline = "Market price is within the modeled margin-of-safety zone"
        action = f"Modeled research entry: at or below {entry_price:,.2f} {currency}; confirm liquidity, thesis, and portfolio risk first."
        holding = "3–5 year research horizon; review after each quarterly/annual report and every dividend decision."
    elif fair_high is not None and price <= fair_high:
        zone = "watch_or_hold"
        headline = "Market price is inside the modeled fair-value range"
        action = f"Watch for a margin-of-safety entry near or below {entry_price:,.2f} {currency}; do not treat fair value as a guaranteed floor."
        holding = "For an existing research position: 3–5 years only while cash flow, earnings, and dividend assumptions remain intact; review quarterly."
    else:
        zone = "above_range"
        headline = "Market price is above the modeled fair-value range"
        action = f"No new research entry is indicated by this model; reassess assumptions or wait for a price nearer {entry_price:,.2f} {currency}."
        holding = "No fixed holding period is suggested above the modeled range; review the thesis and valuation after the next report."

    coverage = len(available)
    confidence = "higher" if coverage >= 4 else "moderate" if coverage >= 2 else "low"
    sensitivity = _dcf_sensitivity(fcf, shares, parsed)
    data_quality = _quality_assessment(coverage, method_dispersion_pct, market_as_of, manual_fields)
    forward_model = build_forward_driver_model(
        market,
        supplied=forward_drivers,
        fallback_revenue_growth_pct=local_revenue_growth,
        generated_at=generated,
        currency=currency,
    )
    scenarios, scenario_analysis = weight_scenarios(
        _build_scenarios(parsed, price, shares, fcf, eps, dividend, book_share),
        forward_model,
        price=price,
        data_quality_score=data_quality["score"],
    )
    long_holding_outlook = _long_holding_outlook(
        market,
        parsed,
        scenarios,
        data_quality,
        local_revenue_growth,
        revenue_history,
        fcf,
        shares,
        eps,
        dividend,
        currency,
        holding_inputs,
    )
    investment_plan = _investment_plan(
        price, fair_value, fair_low, fair_high, entry_price, entry_low,
        dividend, currency, zone,
    )
    market_source = market.get("source") or "Market provider"
    source_evidence = [
        {"field": "Market price", "value": _round(price), "unit": currency + "/share", "source": input_source("price", market_source), "as_of": input_as_of("price", market_as_of)},
        {"field": "Shares outstanding", "value": _round(shares, 4), "unit": "shares", "source": input_source("shares_outstanding", market_source), "as_of": input_as_of("shares_outstanding", market_as_of)},
        {"field": "Free cash flow", "value": _round(fcf, 4), "unit": currency, "source": input_source("free_cash_flow", fcf_source), "as_of": input_as_of("free_cash_flow", market_as_of)},
        {"field": "Trailing EPS", "value": _round(eps, 4), "unit": currency + "/share", "source": input_source("eps", market_source), "as_of": input_as_of("eps", market_as_of)},
        {"field": "Annual dividend", "value": _round(dividend, 4), "unit": currency + "/share", "source": input_source("dividend_rate", market_source), "as_of": input_as_of("dividend_rate", market_as_of)},
        {"field": "Book value/share", "value": _round(book_share, 4), "unit": currency + "/share", "source": book_source, "as_of": input_as_of("book_value_per_share", equity_row.get("period_end") if isinstance(equity_row, dict) and equity is not None else market_as_of)},
        {"field": "Near-term growth", "value": _round(near), "unit": "%", "source": parsed["growth_source"], "as_of": growth_as_of},
    ]
    automatic_inputs = {
        "available_count": sum(row.get("value") is not None for row in source_evidence),
        "total_count": len(source_evidence),
        "manual_count": len(manual_fields),
        "rows": [
            {
                **row,
                "status": "manual" if "User-provided override" in str(row.get("source") or "") else "automatic" if row.get("value") is not None else "unavailable",
            }
            for row in source_evidence
        ],
        "message": "SolvAI automatically resolves market data and verified-report evidence. Technical overrides remain optional and are never saved as provider facts.",
    }
    limitations = [
        "This is an assumption-sensitive research estimate, not personalized investment advice or a guaranteed target price.",
        "Market and dividend fields may be delayed; verify declared distributions and current prices with the issuer or exchange.",
        "The methods are not fully independent: DDM and Gordon both depend on the same dividend stream.",
    ]
    if coverage < 3:
        limitations.append("Fewer than three valuation methods were available, so the blended range has limited triangulation.")
    comments = []
    if coverage:
        comments.append(f"{coverage} of 5 methods were available; weights were renormalized across only those calculated methods.")
    if method_dispersion_pct is not None:
        if method_dispersion_pct >= 60:
            comments.append(f"Method dispersion is high at {method_dispersion_pct:.1f}%, so the range is more decision-useful than the single blended point.")
        elif method_dispersion_pct >= 30:
            comments.append(f"Method dispersion is moderate at {method_dispersion_pct:.1f}%; review cash-flow, multiple, and dividend assumptions before relying on the midpoint.")
        else:
            comments.append(f"Available methods are relatively clustered, with {method_dispersion_pct:.1f}% dispersion around the blend.")
    if next((row for row in methods if row["name"] == "Equity DCF"), {}).get("status") != "available":
        comments.append("DCF is excluded because positive free cash flow and shares were not both available; EBITDA or profit was not used as a substitute.")
    if not any(row["status"] == "available" and "DDM" in row["name"] for row in methods):
        comments.append("Dividend-discount methods are excluded because no positive annual dividend was available; this does not predict that no future dividend will be paid.")
    trailing_yield = _finite(market.get("dividend_yield_pct"))
    if trailing_yield is not None:
        comments.append(f"The trailing indicated dividend yield is {trailing_yield:.2f}%; future yield changes with both distributions and market price.")

    return {
        "success": True,
        "company": company,
        "ticker": market.get("ticker") or ticker_for(company),
        "currency": currency,
        "generated_at": generated,
        "market": {
            "price": _round(price),
            "updated_at": market.get("updated_at"),
            "source": market.get("source") or "Market provider",
            "warning": market.get("warning"),
            "manual_fields": manual_fields,
        },
        "assumptions": parsed,
        "methods": methods,
        "scenarios": scenarios,
        "forward_driver_model": forward_model,
        "scenario_analysis": scenario_analysis,
        "sensitivity": sensitivity,
        "data_quality": data_quality,
        "source_evidence": source_evidence,
        "automatic_inputs": automatic_inputs,
        "investment_plan": investment_plan,
        "long_holding_outlook": long_holding_outlook,
        "summary": {
            "status": "available" if fair_value is not None else "unavailable",
            "fair_value": fair_value,
            "fair_range_low": fair_low,
            "fair_range_high": fair_high,
            "research_entry_price": entry_price,
            "research_entry_range_low": entry_low,
            "margin_of_safety_pct": parsed["margin_of_safety_pct"],
            "upside_downside_to_fair_pct": upside_pct,
            "zone": zone,
            "headline": headline,
            "research_action": action,
            "holding_review_horizon": holding,
            "method_coverage": coverage,
            "method_dispersion_pct": method_dispersion_pct,
            "confidence": confidence,
            "comments": comments,
        },
        "dividend_outlook": _dividend_outlook(market, schedule, price),
        "limitations": limitations,
    }
