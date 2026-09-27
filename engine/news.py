import re
import urllib.parse

import feedparser
import requests

from config import TRUSTED_NEWS_DOMAINS
from .provider_cache import EVIDENCE_CACHE

def domain_score(link):
    match = re.search(r"https?://([^/]+)", link or "")
    host = match.group(1).lower() if match else ""

    for domain, score in TRUSTED_NEWS_DOMAINS.items():
        if host.endswith(domain):
            return score, domain

    return 0.20, host

MACRO_QUERY_GROUPS = [
    ("Global Macro", 'Federal Reserve interest rate inflation CPI jobs payrolls unemployment GDP recession Treasury yields central bank'),
    ("Vietnam", 'Vietnam SBV interest rate CPI inflation GDP exports FDI USD VND government economic policy trade'),
    ("Markets", 'S&P 500 Nasdaq Dow Jones Nikkei Hang Seng Shanghai DAX FTSE KOSPI index futures global markets'),
    ("Commodities", 'oil Brent WTI gold copper commodities energy prices supply demand OPEC'),
    ("Policy", 'tariffs trade restrictions sanctions central bank decision fiscal policy geopolitical conflict market impact'),
]

_IMPACT_RULES = [
    ("Very high", 5, ("Fed", "central bank", "tariff", "sanction", "recession", "war", "crisis", "default", "emergency")),
    ("High", 4, ("interest rate", "inflation", "CPI", "GDP", "employment", "unemployment", "yield", "SBV", "trade policy", "oil prices", "gold")),
    ("Medium", 3, ("exports", "imports", "FDI", "PMI", "currency", "USD/VND", "stocks", "index", "commodity")),
]

_EFFECT_RULES = [
    (("rate", "fed", "SBV", "yield"), ("↑ USD / funding costs", "↓ rate-sensitive assets", "watch liquidity and valuation")),
    (("inflation", "CPI"), ("↑ inflation pressure", "rates may stay higher", "watch real-income and margin pressure")),
    (("recession", "GDP", "employment", "unemployment"), ("↓ cyclical demand if weakening", "↑ defensive demand", "watch earnings expectations")),
    (("oil", "energy"), ("↑ energy-sector support", "↓ transport/input margins", "watch inflation spillovers")),
    (("gold",), ("↑ defensive/hedging demand", "signal of risk aversion when rising with yields", "watch real rates and USD")),
    (("export", "FDI", "manufacturing"), ("↑ Vietnam industrial activity", "support logistics/export sectors", "watch global demand and FX")),
    (("tariff", "trade", "sanction"), ("↑ supply-chain uncertainty", "sector dispersion may increase", "watch exports, margins and FX")),
    (("currency", "USD/VND", "VND"), ("↑ FX pressure", "import costs may rise", "watch liquidity and foreign flows")),
]

def _impact(title, summary, source_score):
    text=f"{title} {summary}".lower()
    for label, score, words in _IMPACT_RULES:
        if any(w.lower() in text for w in words):
            score += min(1.0, source_score * 0.5)
            return label, min(5.0, score)
    return "Low", 2.0 + min(0.5, source_score * 0.25)

_MACRO_DIRECT_TERMS = (
    "federal reserve", "fed", "ecb", "boj", "bank of england", "sbv",
    "interest rate", "rate cut", "rate hike", "inflation", "cpi", "ppi",
    "payroll", "employment", "unemployment", "gdp", "recession",
    "treasury", "bond yield", "yield curve", "usd/vnd", "currency",
    "tariff", "trade restriction", "sanction", "opec", "oil price",
    "brent", "wti", "gold price", "commodity", "vn-index", "vn30",
    "s&p 500", "nasdaq", "nikkei", "hang seng", "shanghai"
)

# Terms that usually indicate a company-specific story and should not dominate the macro desk.
_COMPANY_ONLY_TERMS = (
    "quarterly earnings", "company launches", "ceo", "chief executive",
    "partnership", "memorandum of understanding", "new product",
    "employee count", "revenue guidance", "company appoints", "shares soar"
)

def _macro_relevance(title, summary, category):
    text = f"{title} {summary}".lower()
    direct = sum(1 for term in _MACRO_DIRECT_TERMS if term in text)
    company = sum(1 for term in _COMPANY_ONLY_TERMS if term in text)
    category_bonus = {"Global Macro": 1.2, "Vietnam": 1.1, "Policy": 1.1, "Commodities": 1.0, "Markets": .8}.get(category, .5)
    return direct * 0.65 + category_bonus - company * 0.45

def _impact(title, summary, source_score, category="Global Macro"):
    text=f"{title} {summary}".lower()
    base=2.0
    for label, score, words in _IMPACT_RULES:
        if any(w.lower() in text for w in words):
            base=max(base, score)
            break
    relevance=_macro_relevance(title, summary, category)
    score=min(5.0, max(1.0, base + min(1.0, source_score * 0.5) + min(0.9, relevance * 0.12)))
    if score >= 4.5: label="Very high"
    elif score >= 3.6: label="High"
    elif score >= 2.7: label="Medium"
    else: label="Low"
    return label, score

def _effects(text):
    low=text.lower()
    for words, effects in _EFFECT_RULES:
        if any(w.lower() in low for w in words):
            return list(effects)
    return ["Monitor cross-market spillovers", "Check whether the move changes rates, growth or liquidity expectations", "Compare with the Macro Regime Monitor"]

def _macro_search_live(limit=12):
    items=[]
    errors=[]
    seen=set()
    for category, query_text in MACRO_QUERY_GROUPS:
        query=urllib.parse.quote(query_text)
        url=("https://news.google.com/rss/search?"
             f"q={query}&hl=en-US&gl=US&ceid=US:en")
        try:
            response=requests.get(url,timeout=8,headers={"User-Agent":"FinancialAI/1.0"})
            response.raise_for_status()
            feed=feedparser.parse(response.content)
            for entry in feed.entries[:18]:
                link=entry.get("link","")
                title=entry.get("title","").strip()
                key=(title.lower(),link)
                if not title or key in seen: continue
                seen.add(key)
                score, domain=domain_score(link)
                summary=entry.get("summary","") or ""
                relevance=_macro_relevance(title, summary, category)
                if relevance < 0.7:
                    continue
                impact, impact_score=_impact(title, summary, score, category)
                items.append({
                    "title":title, "published":entry.get("published", ""),
                    "source":entry.get("source",{}).get("title",domain), "link":link,
                    "trust_score":score, "category":category, "impact":impact,
                    "impact_score":impact_score, "potential_effect":_effects(title + " " + (entry.get("summary","") or "")),
                })
        except Exception as exc:
            errors.append(f"{category}: {exc}")
    items.sort(key=lambda x:(-x["impact_score"], -x["trust_score"], x.get("published", "")), reverse=False)
    return {
        "success": bool(items), "scope":"macro", "items":items[:limit],
        "categories":[x[0] for x in MACRO_QUERY_GROUPS],
        "updated_at":__import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "errors":errors,
        "note":"Macro-impact news is independent of the selected company. Impact labels are a research heuristic, not a guarantee of market outcome."
    }


def macro_search(limit=12):
    key = f"macro-news:{int(limit)}"
    cached = EVIDENCE_CACHE.get(key, ttl=600.0, stale_ttl=86400.0)
    if cached and cached.fresh:
        return {**cached.value, "cache_hit": True}
    payload = _macro_search_live(limit=limit)
    if payload.get("items"):
        EVIDENCE_CACHE.put(key, payload)
        return {**payload, "cache_hit": False}
    if cached:
        return {**cached.value, "cache_hit": True, "stale_fallback": True}
    return payload


def _search_live(company, limit=10):
    query = urllib.parse.quote(f'"{company}" Vietnam company')
    url = (
        "https://news.google.com/rss/search?"
        f"q={query}&hl=en-US&gl=US&ceid=US:en"
    )

    try:
        response = requests.get(
            url,
            timeout=10,
            headers={"User-Agent": "FinancialAI/1.0"},
        )
        response.raise_for_status()

        feed = feedparser.parse(response.content)
        items = []

        for entry in feed.entries[:40]:
            score, domain = domain_score(entry.get("link", ""))

            items.append(
                {
                    "title": entry.get("title", ""),
                    "published": entry.get("published", ""),
                    "source": entry.get("source", {}).get("title", domain),
                    "link": entry.get("link", ""),
                    "trust_score": score,
                }
            )

        items.sort(key=lambda item: item["trust_score"], reverse=True)

        return {
            "success": True,
            "company": company,
            "items": items[:limit],
            "note": (
                "News is context, not proof. Publisher ranking is only a "
                "quality aid, not a guarantee of accuracy."
            ),
        }

    except Exception as exc:
        return {
            "success": False,
            "company": company,
            "items": [],
            "error": str(exc),
            "note": "News service unavailable; local report analysis remains available.",
        }


def search(company, limit=10):
    normalized = str(company or "").strip().upper()
    key = f"company-news:{normalized}:{int(limit)}"
    cached = EVIDENCE_CACHE.get(key, ttl=900.0, stale_ttl=86400.0)
    if cached and cached.fresh:
        return {**cached.value, "cache_hit": True}
    payload = _search_live(normalized, limit=limit)
    if payload.get("items"):
        EVIDENCE_CACHE.put(key, payload)
        return {**payload, "cache_hit": False}
    if cached:
        return {**cached.value, "cache_hit": True, "stale_fallback": True}
    return payload
