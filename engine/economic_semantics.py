"""Human-facing contracts for economic and model outputs."""
from __future__ import annotations


CONTRACTS = {
    "beneish_m_score": {
        "label": "Accounting-quality screen",
        "stage": "investment_research",
        "kind": "screen",
        "may_be_called_probability": False,
        "note": "A forensic warning screen; not an audit conclusion, fraud probability, or general downside score.",
    },
    "valuation_scenario_weight": {
        "label": "Research weight",
        "stage": "investment_research",
        "kind": "heuristic_weight",
        "may_be_called_probability": False,
        "note": "A transparent assumption weight, not a calibrated outcome probability.",
    },
    "macro_scenario_fit": {
        "label": "Scenario fit",
        "stage": "macro_context",
        "kind": "rule_score",
        "may_be_called_probability": False,
        "note": "Ranks compatibility with published observations; it is not a forecast.",
    },
    "event_scenario_share": {
        "label": "Evidence-weighted share",
        "stage": "event_research",
        "kind": "uncalibrated_scenario_share",
        "may_be_called_probability": False,
        "note": "Use probability language only after resolved forecasts demonstrate calibration against the baseline.",
    },
    "stock_direction_probability": {
        "label": "Validated directional probability",
        "stage": "quant_research",
        "kind": "calibrated_probability",
        "may_be_called_probability": True,
        "note": "Shown only when walk-forward quality gates are satisfied.",
    },
}


def contract(key: str) -> dict:
    return dict(CONTRACTS.get(key) or {})

