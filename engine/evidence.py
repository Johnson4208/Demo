from __future__ import annotations

from . import db
from .analysis import latest, yoy_growth

FORMULAS = {
    "gross_revenue": "Reported gross sales and service revenue from the consolidated income statement.",
    "revenue_reductions": "Reported revenue deductions from the consolidated income statement.",
    "revenue": "Reported net revenue from the consolidated income statement.",
    "cost_of_goods_sold": "Reported cost of goods sold from the consolidated income statement.",
    "gross_profit": "Reported or accounting-identity-reconciled gross profit from the consolidated income statement.",
    "operating_profit": "Reported operating profit from the consolidated income statement.",
    "net_income": "Profit attributable to owners of the parent where the consolidated report provides it.",
    "net_income_total": "Total consolidated profit after tax, including non-controlling interests where reported.",
    "net_income_parent": "Reported profit attributable to owners of the parent.",
    "nci_profit": "Reported profit attributable to non-controlling interests.",
    "selling_expense": "Reported selling expense from the consolidated income statement.",
    "admin_expense": "Reported general and administrative expense from the consolidated income statement.",
    "sga": "Selling plus general and administrative expense from verified report observations.",
    "depreciation": "Reported depreciation from the cash-flow statement or report notes.",
    "assets": "Reported or balance-sheet-reconciled total assets.",
    "total_liabilities": "Reported or balance-sheet-reconciled total liabilities.",
    "equity": "Reported or balance-sheet-reconciled shareholders’ equity.",
    "total_sources": "Reported total liabilities and equity from the balance sheet.",
    "current_assets": "Reported current assets from the balance sheet.",
    "current_liabilities": "Reported current liabilities from the balance sheet.",
    "receivables": "Reported trade or short-term receivables from the balance sheet.",
    "ppe": "Reported property, plant and equipment from the balance sheet.",
    "short_term_debt": "Reported short-term borrowings and finance-lease debt.",
    "long_term_debt": "Reported long-term borrowings and finance-lease debt.",
    "debt": "Short-term plus long-term interest-bearing debt from verified observations.",
    "cash_flow": "Reported net cash flow from operating activities.",
    "revenue_growth": "Same-period YoY = (current-period net revenue / prior-year same-period net revenue) − 1.",
    "net_margin": "Net margin = parent-attributable net income / net revenue.",
    "ebitda": "EBITDA = operating profit plus period-compatible depreciation from verified report observations.",
    "ebitda_margin": "EBITDA margin = EBITDA / net revenue; quarterly EBITDA uses period-compatible depreciation.",
    "cash_flow_margin": "Cash-flow margin = reported operating cash flow / net revenue for the same period.",
    "roa": "ROA = parent-attributable net income / average total assets for the period.",
    "roe": "ROE = parent-attributable net income / average equity for the period.",
    "debt_to_ebitda": "Debt / EBITDA uses interest-bearing debt divided by EBITDA on a compatible period basis.",
}


def get_evidence(company: str, metric: str, basis: str = "latest") -> dict:
    company = (company or "").strip().upper()
    metric = (metric or "").strip().lower()
    basis = (basis or "latest").strip().lower()
    docs = db.company_documents(company)
    if not docs:
        return {"success": False, "error": "Company not found in the report library."}

    if basis == "latest":
        obs = latest(company, metric.replace("_growth", "revenue") if metric == "revenue_growth" else metric)
        if metric == "revenue_growth":
            value = yoy_growth(company, "revenue")
            comparison = obs.get("comparison_value") if obs else None
            return _payload(company, metric, value, obs, comparison, basis)
        return _payload(company, metric, obs.get("value") if obs else None, obs, obs.get("comparison_value") if obs else None, basis)

    # Market/TTM/annual ratio evidence comes from overview ratio views.
    if basis in {"ttm", "annual", "market"}:
        from .analysis import overview
        o = overview(company)
        key = metric if metric.endswith("_ttm") or metric.endswith("_annual") else metric
        if basis == "ttm": key = f"{metric}_ttm"
        if basis == "annual": key = f"{metric}_annual"
        item = o.get("market_ratios", {}).get(key)
        return {
            "success": True,
            "company": company,
            "metric": metric,
            "basis": basis,
            "value": item.get("value") if isinstance(item, dict) else item,
            "period_end": item.get("period_end") if isinstance(item, dict) else None,
            "source": item.get("source") if isinstance(item, dict) else None,
            "formula": FORMULAS.get(metric, "Derived from the stored verified observations."),
        }

    return {"success": False, "error": f"Unsupported evidence basis: {basis}"}


def _payload(company, metric, value, obs, comparison, basis):
    source_path = obs.get("source_path") if obs else None
    doc = None
    for d in db.company_documents(company):
        if source_path and d.get("path") == source_path:
            doc = d
            break
    return {
        "success": True,
        "company": company,
        "metric": metric,
        "basis": basis,
        "value": value,
        "comparison_value": comparison,
        "period_end": obs.get("period_end") if obs else None,
        "year": obs.get("year") if obs else None,
        "unit": obs.get("unit") if obs else None,
        "confidence": obs.get("confidence") if obs else None,
        "source_type": obs.get("source_type") if obs else None,
        "source_path": source_path,
        "document_scope": doc.get("scope") if doc else None,
        "document_status": doc.get("status") if doc else None,
        "document_quality": doc.get("quality_score") if doc else None,
        "formula": FORMULAS.get(metric, "Derived from the stored verified observations."),
    }
