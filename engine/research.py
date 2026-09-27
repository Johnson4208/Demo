from __future__ import annotations
from typing import Any
from .analysis import overview, series, yoy_growth
from .risk import assess
from .stock import analyze as stock_analyze


def anomalies(company: str) -> dict[str, Any]:
    company = company.upper().strip()
    o = overview(company)
    if o.get("error"):
        return o
    out = []
    for metric, label, threshold in [
        ("revenue", "Revenue", 15),
        ("net_income", "Net income", 20),
        ("ebitda", "EBITDA", 20),
    ]:
        vals = [x for x in series(company, metric) if x.get("value") is not None]
        if len(vals) < 2:
            continue
        prev, cur = vals[-2], vals[-1]
        if prev.get("value") in (None, 0):
            continue
        ch = (float(cur["value"]) / float(prev["value"]) - 1) * 100
        if abs(ch) >= threshold:
            out.append({"metric": label, "change_pct": round(ch, 2), "from_period": prev.get("period_end"), "to_period": cur.get("period_end"), "type": "jump" if ch > 0 else "drop"})
    # Cross-metric divergence: strong revenue growth but margin contraction.
    rg = yoy_growth(company, "revenue")
    margin_series = [x for x in series(company, "net_margin") if x.get("value") is not None]
    if rg is not None and margin_series:
        if rg > 10 and len(margin_series) >= 2 and margin_series[-1]["value"] < margin_series[-2]["value"] - 1:
            out.append({"metric": "Revenue vs net margin", "change_pct": round(float(rg), 2), "from_period": margin_series[-2].get("period_end"), "to_period": margin_series[-1].get("period_end"), "type": "divergence", "detail": "Revenue is growing while net margin is contracting."})
    return {"success": True, "company": company, "anomalies": out}


def research_brief(company: str) -> dict[str, Any]:
    company = company.upper().strip()
    o = overview(company)
    if o.get("error"):
        return o
    r = assess(company)
    try:
        s = stock_analyze(company)
    except Exception:
        s = {"status": "unavailable"}
    a = anomalies(company)
    return {
        "success": True,
        "company": company,
        "executive": o.get("health", {}),
        "metrics": o.get("metrics", {}),
        "latest_report": o.get("latest_report", {}),
        "coverage": o.get("coverage", {}),
        "risk": r,
        "market": s,
        "anomalies": a.get("anomalies", []),
    }
