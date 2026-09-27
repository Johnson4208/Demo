"""Evidence-labelled forward drivers and scenario-weighted valuation.

The calculations in this module are deliberately deterministic and transparent.
They produce research weights, not statistically calibrated outcome probabilities.
Missing drivers remain unavailable and never receive fabricated values.
"""

from __future__ import annotations

import math


DRIVER_SPECS = (
    {
        "key": "revenue_growth_pct",
        "label": "Forward revenue growth",
        "unit": "%",
        "weight": 0.25,
        "low": -50.0,
        "high": 100.0,
    },
    {
        "key": "eps_growth_pct",
        "label": "Forward EPS growth",
        "unit": "%",
        "weight": 0.30,
        "low": -100.0,
        "high": 200.0,
    },
    {
        "key": "margin_change_pct_points",
        "label": "Operating-margin change",
        "unit": "percentage points",
        "weight": 0.15,
        "low": -30.0,
        "high": 30.0,
    },
    {
        "key": "net_debt_to_ebitda",
        "label": "Net debt / EBITDA",
        "unit": "×",
        "weight": 0.15,
        "low": -5.0,
        "high": 20.0,
    },
    {
        "key": "return_on_equity_pct",
        "label": "Return on equity",
        "unit": "%",
        "weight": 0.15,
        "low": -100.0,
        "high": 100.0,
    },
)


def _finite(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _clamp(value, low, high):
    return max(low, min(high, value))


def _round(value, digits=2):
    number = _finite(value)
    return round(number, digits) if number is not None else None


def _score_driver(key, value):
    """Convert heterogeneous drivers to a bounded -1..1 directional score."""
    if key == "revenue_growth_pct":
        return _clamp(value / 20.0, -1.0, 1.0)
    if key == "eps_growth_pct":
        return _clamp(value / 25.0, -1.0, 1.0)
    if key == "margin_change_pct_points":
        return _clamp(value / 5.0, -1.0, 1.0)
    if key == "net_debt_to_ebitda":
        return _clamp((2.5 - value) / 3.0, -1.0, 1.0)
    if key == "return_on_equity_pct":
        return _clamp((value - 10.0) / 20.0, -1.0, 1.0)
    return 0.0


def _interpret_driver(key, value, score):
    tone = "supportive" if score >= 0.25 else "adverse" if score <= -0.25 else "neutral"
    if key == "net_debt_to_ebitda":
        detail = (
            "Lower leverage provides more balance-sheet flexibility."
            if score >= 0.25
            else "Higher leverage can amplify refinancing and earnings risk."
            if score <= -0.25
            else "Leverage is near the model's neutral reference range."
        )
    elif key == "margin_change_pct_points":
        detail = (
            "Margin expansion supports cash-flow and earnings delivery."
            if score >= 0.25
            else "Margin compression weakens earnings conversion."
            if score <= -0.25
            else "The margin change is not large enough to create a strong tilt."
        )
    elif key == "return_on_equity_pct":
        detail = (
            "Return on equity is above the model's neutral reference."
            if score >= 0.25
            else "Return on equity is below the model's neutral reference."
            if score <= -0.25
            else "Return on equity is near the model's neutral reference."
        )
    else:
        subject = "Revenue" if key == "revenue_growth_pct" else "EPS"
        detail = (
            f"{subject} growth supports the upside scenario."
            if score >= 0.25
            else f"{subject} contraction increases downside pressure."
            if score <= -0.25
            else f"{subject} growth is close to the neutral range."
        )
    return tone, detail


def build_forward_driver_model(
    market,
    supplied=None,
    fallback_revenue_growth_pct=None,
    generated_at=None,
    currency="VND",
):
    """Return traceable forward-driver rows and a bounded aggregate tilt."""
    market = market if isinstance(market, dict) else {}
    supplied = supplied if isinstance(supplied, dict) else {}
    rows = []
    available_weight = 0.0
    weighted_score = 0.0
    manual_fields = []

    for spec in DRIVER_SPECS:
        key = spec["key"]
        manual_value = _finite(supplied.get(key))
        market_key = "earnings_growth_pct" if key == "eps_growth_pct" else key
        market_value = _finite(market.get(market_key))
        fallback = _finite(fallback_revenue_growth_pct) if key == "revenue_growth_pct" else None
        if manual_value is not None:
            value = manual_value
            source = "User forward assumption (not independently verified)"
            as_of = generated_at
            origin = "manual"
            manual_fields.append(key)
        elif market_value is not None:
            value = market_value
            source = market.get("source") or "Market provider"
            as_of = market.get("updated_at")
            origin = "provider"
        elif fallback is not None:
            value = fallback
            source = "Latest comparable local-report revenue growth"
            as_of = None
            origin = "local_report"
        else:
            rows.append({
                **spec,
                "status": "unavailable",
                "value": None,
                "score": None,
                "contribution": None,
                "source": "Unavailable",
                "as_of": None,
                "origin": "unavailable",
                "tone": "unavailable",
                "interpretation": "No dated provider value or user assumption was supplied.",
            })
            continue

        value = _clamp(value, spec["low"], spec["high"])
        score = _score_driver(key, value)
        tone, interpretation = _interpret_driver(key, value, score)
        available_weight += spec["weight"]
        weighted_score += spec["weight"] * score
        rows.append({
            **spec,
            "status": "available",
            "value": _round(value),
            "score": _round(score, 4),
            "contribution": _round(spec["weight"] * score, 4),
            "source": source,
            "as_of": as_of,
            "origin": origin,
            "tone": tone,
            "interpretation": interpretation,
        })

    aggregate = weighted_score / available_weight if available_weight else 0.0
    available_count = sum(row["status"] == "available" for row in rows)
    eps_growth = next((row["value"] for row in rows if row["key"] == "eps_growth_pct" and row["status"] == "available"), None)
    revenue_growth = next((row["value"] for row in rows if row["key"] == "revenue_growth_pct" and row["status"] == "available"), None)
    eps = _finite(market.get("eps"))
    projections = []
    if revenue_growth is not None:
        projections.append({
            "key": "revenue_index",
            "label": "One-year revenue index",
            "value": _round(100.0 * (1.0 + revenue_growth / 100.0)),
            "unit": "current = 100",
            "basis": "Applies the available forward revenue-growth driver to a normalized current index of 100.",
        })
    if eps is not None and eps_growth is not None:
        projections.append({
            "key": "forward_eps",
            "label": "One-year forward EPS",
            "value": _round(eps * (1.0 + eps_growth / 100.0)),
            "unit": f"{currency}/share",
            "basis": "Trailing EPS multiplied by one plus the available forward EPS-growth driver.",
        })

    return {
        "status": "available" if available_count else "unavailable",
        "drivers": rows,
        "available_drivers": available_count,
        "total_drivers": len(rows),
        "coverage_pct": _round(available_weight * 100.0),
        "manual_fields": manual_fields,
        "manual_driver_pct": _round(len(manual_fields) / available_count * 100.0) if available_count else 0.0,
        "raw_tilt": _round(aggregate, 4),
        "projections": projections,
        "method": "Available drivers are normalized to -1..1, combined using visible weights, and later shrunk toward the neutral scenario prior according to evidence coverage and valuation-data quality.",
        "warning": "These are scenario inputs and research weights, not company guidance, analyst consensus, or calibrated outcome probabilities.",
    }


def _research_weight_triplet(tilt):
    """Start at 25/50/25 and transfer mass according to the evidence tilt."""
    tilt = _clamp(tilt, -1.0, 1.0)
    base = 50.0 - 10.0 * abs(tilt)
    bull = 25.0 + 25.0 * tilt + 5.0 * abs(tilt)
    bear = 100.0 - base - bull
    values = [round(max(5.0, bear), 1), round(max(35.0, base), 1), round(max(5.0, bull), 1)]
    total = sum(values)
    values[1] = round(values[1] + (100.0 - total), 1)
    return values


def weight_scenarios(scenarios, driver_model, price=None, data_quality_score=0.0):
    """Attach heuristic research weights and calculate a weighted value."""
    scenarios = [dict(row) for row in (scenarios or [])]
    available = [row for row in scenarios if _finite(row.get("fair_value")) is not None]
    coverage = _finite((driver_model or {}).get("coverage_pct")) or 0.0
    raw_tilt = _finite((driver_model or {}).get("raw_tilt")) or 0.0
    quality = _clamp((_finite(data_quality_score) or 0.0) / 100.0, 0.0, 1.0)
    evidence_strength = min(1.0, coverage / 70.0) * (0.35 + 0.65 * quality)
    manual_share = _clamp((_finite((driver_model or {}).get("manual_driver_pct")) or 0.0) / 100.0, 0.0, 1.0)
    evidence_strength *= 1.0 - 0.25 * manual_share
    effective_tilt = raw_tilt * evidence_strength
    weights = _research_weight_triplet(effective_tilt) if coverage > 0 else [25.0, 50.0, 25.0]
    by_key = {"bear": weights[0], "base": weights[1], "bull": weights[2]}
    for row in scenarios:
        row["research_weight_pct"] = by_key.get(str(row.get("key") or "").lower(), 0.0)

    valid_weight = sum(row["research_weight_pct"] for row in scenarios if _finite(row.get("fair_value")) is not None)
    weighted_value = (
        sum(row["fair_value"] * row["research_weight_pct"] for row in scenarios if _finite(row.get("fair_value")) is not None) / valid_weight
        if valid_weight else None
    )
    weighted_entry = (
        sum(row["research_entry_price"] * row["research_weight_pct"] for row in scenarios if _finite(row.get("research_entry_price")) is not None) / valid_weight
        if valid_weight else None
    )
    scenario_by_key = {str(row.get("key") or "").lower(): row for row in scenarios}
    bear_value = _finite((scenario_by_key.get("bear") or {}).get("fair_value"))
    bull_value = _finite((scenario_by_key.get("bull") or {}).get("fair_value"))
    market_price = _finite(price)
    expected_gap = (weighted_value / market_price - 1.0) * 100.0 if weighted_value and market_price and market_price > 0 else None
    downside = (bear_value / market_price - 1.0) * 100.0 if bear_value and market_price and market_price > 0 else None
    upside = (bull_value / market_price - 1.0) * 100.0 if bull_value and market_price and market_price > 0 else None
    reward = max(0.0, (bull_value or 0.0) - (market_price or 0.0)) if market_price else None
    risk = max(0.0, (market_price or 0.0) - (bear_value or 0.0)) if market_price else None
    ratio = reward / risk if reward is not None and risk not in (None, 0.0) else None
    dominant = max(scenarios, key=lambda row: row.get("research_weight_pct", 0.0)).get("label") if scenarios else None

    if weighted_value is None:
        headline = "Scenario-weighted value is unavailable"
    elif market_price is None:
        headline = "Scenario-weighted value calculated; market comparison unavailable"
    elif expected_gap is not None and expected_gap >= 15.0 and (ratio is None or ratio >= 1.5):
        headline = "Modeled reward currently exceeds the central downside estimate"
    elif expected_gap is not None and expected_gap <= -10.0:
        headline = "Current price is above the scenario-weighted value"
    else:
        headline = "Risk and reward are broadly balanced around current assumptions"

    evidence_label = (
        "Higher" if coverage >= 70.0 and quality >= 0.75 and manual_share == 0.0
        else "Moderate" if coverage >= 45.0 and quality >= 0.5
        else "Low"
    )
    return scenarios, {
        "status": "available" if weighted_value is not None else "unavailable",
        "headline": headline,
        "weighted_fair_value": _round(weighted_value),
        "weighted_entry_price": _round(weighted_entry),
        "expected_gap_pct": _round(expected_gap),
        "bear_return_pct": _round(downside),
        "bull_return_pct": _round(upside),
        "upside_downside_ratio": _round(ratio),
        "dominant_scenario": dominant,
        "evidence_label": evidence_label,
        "effective_tilt": _round(effective_tilt, 4),
        "research_weights": {"bear": weights[0], "base": weights[1], "bull": weights[2]},
        "semantic_contract": {
            "label": "Research weight",
            "calibrated_probability": False,
            "stage": "investment_research",
        },
        "method": "Research weights begin at Bear 25%, Base 50%, Bull 25%. Available forward drivers tilt the distribution; missing coverage and lower data quality shrink it back toward that prior.",
        "warning": "Scenario weights are transparent heuristic research weights—not options-implied, analyst-consensus, or historically calibrated probabilities.",
    }
