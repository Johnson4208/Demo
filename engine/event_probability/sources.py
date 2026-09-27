from __future__ import annotations
import hashlib, html, json, os, re, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from urllib.parse import quote_plus, urlparse
import requests
try:
    import feedparser
except ImportError:
    feedparser = None
from dateutil import parser as dtparse
from config import STORAGE_DIR
from engine.system_health import record_provider

CACHE_DIR = STORAGE_DIR / "event_probability_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
CACHE_TTL = int(os.getenv("EVENT_CACHE_TTL", "900"))
PARTIAL_CACHE_TTL = int(os.getenv("EVENT_PARTIAL_CACHE_TTL", "60"))
SOURCE_STALE_TTL = int(os.getenv("EVENT_SOURCE_STALE_TTL", "86400"))
GDELT_COOLDOWN_SECONDS = int(os.getenv("GDELT_COOLDOWN_SECONDS", "300"))
GDELT_RETRIES = int(os.getenv("GDELT_RETRIES", "1"))
GDELT_BACKOFF_SECONDS = float(os.getenv("GDELT_BACKOFF_SECONDS", "0.6"))
HEADERS={"User-Agent":"FinancialAI-EventProbability/1.0"}
GDELT_COOLDOWN_PATH = CACHE_DIR / "gdelt_cooldown.json"


def _clean_text(value):
    text = str(value or "")
    # Some RSS summaries double-encode entities (for example &amp;nbsp;).
    # Decode twice, then strip markup and normalize whitespace.
    for _ in range(2):
        text = html.unescape(text)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def _safe_date(v):
    if not v: return None
    try:
        value = dtparse.parse(v)
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    except Exception: return None


def _item(source,title,url,snippet,published=None,reliability=0.5,meta=None):
    title = _clean_text(title)
    snippet = _clean_text(snippet)
    metadata = dict(meta or {})
    metadata.setdefault("source_tier", _source_tier(source, url))
    metadata.setdefault("domain", _domain(url) or metadata.get("domain"))
    return {"id": hashlib.sha1((source+"|"+title+"|"+url).encode("utf-8","ignore")).hexdigest()[:12], "source":source,"title":title,"url":url,"snippet":snippet,"published_at":_safe_date(published),"reliability":reliability,"meta":metadata}


def _domain(url):
    try:
        return urlparse(str(url or "")).netloc.lower().removeprefix("www.")
    except Exception:
        return ""


def _source_tier(source, url):
    domain = _domain(url)
    source_name = str(source or "").lower()
    if domain.endswith((".gov", ".gov.vn")) or "official" in source_name:
        return "primary"
    if source_name in {"crossref", "arxiv"} or domain.endswith(".edu"):
        return "academic"
    if source_name in {"google news rss", "gdelt"}:
        return "aggregator"
    return "publisher"


def _title_tokens(value):
    return set(re.findall(r"[a-z0-9]+", _clean_text(value).lower()))


def _near_duplicate(left, right):
    a, b = _title_tokens(left), _title_tokens(right)
    if not a or not b:
        return False
    return len(a & b) / max(1, len(a | b)) >= 0.82


def _dedupe_balanced(items, per_domain=3, limit=60):
    """Cluster repeated headlines and keep a balanced set of source domains."""
    ordered = sorted(
        items,
        key=lambda item: (float(item.get("reliability", 0.5)), item.get("published_at") or ""),
        reverse=True,
    )
    kept, domain_counts = [], {}
    for item in ordered:
        url_key = (item.get("url") or "").strip().lower()
        duplicate = next((row for row in kept if url_key and url_key == (row.get("url") or "").strip().lower()), None)
        if duplicate is None:
            duplicate = next((row for row in kept if _near_duplicate(item.get("title"), row.get("title"))), None)
        if duplicate is not None:
            duplicate["meta"] = {**(duplicate.get("meta") or {}), "duplicate_count": int((duplicate.get("meta") or {}).get("duplicate_count", 1)) + 1}
            continue
        domain = _domain(item.get("url")) or str(item.get("source") or "unknown").lower()
        if domain_counts.get(domain, 0) >= per_domain:
            continue
        enriched = dict(item)
        enriched["meta"] = {**(item.get("meta") or {}), "duplicate_count": 1, "domain": domain}
        kept.append(enriched)
        domain_counts[domain] = domain_counts.get(domain, 0) + 1
        if len(kept) >= limit:
            break
    return kept


def _cache_key(query, source_profile):
    raw=json.dumps([query,source_profile],ensure_ascii=False,sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _cache_get(key, max_age=CACHE_TTL):
    path=CACHE_DIR/(key+".json")
    try:
        payload=json.loads(path.read_text(encoding="utf-8"))
        ttl=min(max_age, int(payload.get("_ttl_seconds", max_age)))
        if time.time()-path.stat().st_mtime > ttl: return None
        return payload
    except Exception:
        return None


def _cache_put(key,payload):
    path=CACHE_DIR/(key+".json")
    tmp=path.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(payload,ensure_ascii=False),encoding="utf-8")
        tmp.replace(path)
    except Exception:
        pass


def _source_cache_key(source, query):
    return _cache_key(query, [source, "last-success"])


def _source_success_get(source, query):
    payload = _cache_get(_source_cache_key(source, query), SOURCE_STALE_TTL)
    return list(payload.get("items", [])) if payload else []


def _source_success_put(source, query, items):
    _cache_put(
        _source_cache_key(source, query),
        {"items": items, "source": source, "saved_at": datetime.now(timezone.utc).isoformat(), "_ttl_seconds": SOURCE_STALE_TTL},
    )


def _gdelt_cooldown_remaining():
    try:
        payload=json.loads(GDELT_COOLDOWN_PATH.read_text(encoding="utf-8"))
        return max(0, int(float(payload.get("blocked_until", 0))-time.time()))
    except Exception:
        return 0


def _set_gdelt_cooldown(seconds):
    seconds=max(30,min(3600,int(seconds or GDELT_COOLDOWN_SECONDS)))
    tmp=GDELT_COOLDOWN_PATH.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps({"blocked_until":time.time()+seconds}),encoding="utf-8")
        tmp.replace(GDELT_COOLDOWN_PATH)
    except Exception:
        pass
    return seconds


def _retry_after(response):
    try:
        return int(float(response.headers.get("Retry-After", GDELT_COOLDOWN_SECONDS)))
    except Exception:
        return GDELT_COOLDOWN_SECONDS


def _stale_items(items):
    out=[]
    for item in items:
        enriched=dict(item)
        # Cached evidence remains useful for continuity, but should carry less
        # weight than a successful live retrieval in the probability model.
        enriched["reliability"]=round(float(item.get("reliability",0.5))*0.82,3)
        enriched["meta"]={**(item.get("meta") or {}),"stale_fallback":True}
        out.append(enriched)
    return out


def _source_issue(source, code, message, **extra):
    return {"source":source,"code":code,"severity":"info","message":message,**extra}


def _friendly_exception(source, exc):
    status=getattr(getattr(exc,"response",None),"status_code",None)
    if status==429:
        return _source_issue(source,"rate_limited",f"{source} temporarily paused requests. Analysis continued with other available sources.")
    if status and status>=500:
        return _source_issue(source,"provider_unavailable",f"{source} is temporarily unavailable. Analysis continued with other available sources.")
    return _source_issue(source,"connection_issue",f"{source} could not be reached. Analysis continued with other available sources.")


def google_news(query, limit=10):
    url=f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=en-US&gl=US&ceid=US:en"
    if feedparser is None:
        raise RuntimeError("feedparser is not installed; run pip install -r requirements.txt")
    feed=feedparser.parse(url, request_headers=HEADERS)
    out=[]
    for e in feed.entries[:limit]:
        provider=e.get("source",{}).get("title") if isinstance(e.get("source"),dict) else ""
        out.append(_item("Google News RSS",e.get("title",""),e.get("link",""),re.sub(r"<.*?>","",e.get("summary", "")),e.get("published"),.68,{"provider":provider}))
    return out


def gdelt(query, limit=10):
    # GDELT DOC 2.1 supports ranked recent article lists; use a short lookback via timespan for freshness.
    url=f"https://api.gdeltproject.org/api/v2/doc/doc?query={quote_plus(query)}&mode=ArtList&format=json&maxrecords={limit}&sort=HybridRel&timespan=30d"
    stale=_source_success_get("gdelt",query)
    cooldown=_gdelt_cooldown_remaining()
    if cooldown:
        if stale:
            return _stale_items(stale), [_source_issue(
                "GDELT","cached_fallback","GDELT is cooling down after a rate limit. Recent cached GDELT evidence is being used.",
                retry_after_seconds=cooldown,fallback_used=True,
            )]
        return [], [_source_issue(
            "GDELT","rate_limited","GDELT is cooling down after a rate limit. Analysis continued with other available sources.",
            retry_after_seconds=cooldown,fallback_used=False,
        )]

    last_error=None
    for attempt in range(max(0,GDELT_RETRIES)+1):
        try:
            response=requests.get(url,headers=HEADERS,timeout=10)
            if getattr(response,"status_code",None)==429:
                cooldown=_set_gdelt_cooldown(_retry_after(response))
                if stale:
                    return _stale_items(stale), [_source_issue(
                        "GDELT","cached_fallback","GDELT reached its temporary request limit. Recent cached GDELT evidence is being used.",
                        retry_after_seconds=cooldown,fallback_used=True,
                    )]
                return [], [_source_issue(
                    "GDELT","rate_limited","GDELT reached its temporary request limit. Analysis continued with other available sources.",
                    retry_after_seconds=cooldown,fallback_used=False,
                )]
            response.raise_for_status()
            data=response.json(); out=[]
            for e in data.get("articles",[]):
                out.append(_item("GDELT",e.get("title",""),e.get("url",""),e.get("seendate","") ,e.get("seendate"),.64,{"domain":e.get("domain"),"language":e.get("language")}))
            _source_success_put("gdelt",query,out)
            return out, []
        except Exception as exc:
            last_error=exc
            if attempt<max(0,GDELT_RETRIES):
                time.sleep(min(1.5,GDELT_BACKOFF_SECONDS*(2**attempt)))
    if stale:
        return _stale_items(stale), [_source_issue(
            "GDELT","cached_fallback","Live GDELT data is temporarily unavailable. Recent cached GDELT evidence is being used.",
            fallback_used=True,
        )]
    raise last_error or RuntimeError("GDELT is temporarily unavailable")


def wikipedia(query, limit=5):
    url=f"https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch={quote_plus(query)}&format=json&utf8=1&srlimit={limit}"
    r=requests.get(url,headers=HEADERS,timeout=10); r.raise_for_status(); data=r.json(); out=[]
    for e in data.get("query",{}).get("search",[]):
        title=e.get("title",""); page="https://en.wikipedia.org/wiki/"+quote_plus(title.replace(" ","_"))
        out.append(_item("Wikipedia",title,page,re.sub(r"<.*?>","",e.get("snippet","")),None,.55))
    return out


def crossref(query, limit=5):
    url=f"https://api.crossref.org/works?query.bibliographic={quote_plus(query)}&rows={limit}&select=DOI,title,URL,published,abstract,container-title"
    r=requests.get(url,headers=HEADERS,timeout=10); r.raise_for_status(); items=r.json().get("message",{}).get("items",[]); out=[]
    for e in items:
        title=(e.get("title") or [""])[0]; url=e.get("URL") or ("https://doi.org/"+e.get("DOI") if e.get("DOI") else "")
        pub=e.get("published",{}).get("date-parts",[[None]])[0]
        pubiso="-".join(str(x) for x in pub if x)
        out.append(_item("Crossref",title,url,re.sub(r"<[^>]+>","",e.get("abstract","") or "")[:700],pubiso,.78,{"container":(e.get("container-title") or [""])[0]}))
    return out


def arxiv(query, limit=5):
    url=f"http://export.arxiv.org/api/query?search_query=all:{quote_plus(query)}&start=0&max_results={limit}&sortBy=relevance&sortOrder=descending"
    if feedparser is None:
        raise RuntimeError("feedparser is not installed; run pip install -r requirements.txt")
    feed=feedparser.parse(url); out=[]
    for e in feed.entries:
        out.append(_item("arXiv",e.get("title","").replace("\n"," "),e.get("link",""),e.get("summary",""),e.get("published"),.80,{"authors":[a.get("name") for a in e.get("authors",[])]}))
    return out


def search_all(query, source_profile="market", source_flags=None):
    profiles={
        "market":[("news",google_news),("gdelt",gdelt)],
        "macro":[("news",google_news),("gdelt",gdelt)],
        "banking":[("news",google_news),("gdelt",gdelt)],
        "business":[("news",google_news),("gdelt",gdelt)],
        "academic":[("news",google_news),("gdelt",gdelt),("crossref",crossref),("arxiv",arxiv)],
        "general":[("news",google_news),("gdelt",gdelt),("wikipedia",wikipedia)],
    }
    if source_flags is not None:
        jobs=[]
        if source_flags.get("news"): jobs.append(("news",google_news))
        if source_flags.get("gdelt"): jobs.append(("gdelt",gdelt))
        if source_flags.get("wikipedia"): jobs.append(("wikipedia",wikipedia))
        if source_flags.get("academic"): jobs.extend([("crossref",crossref),("arxiv",arxiv)])
    else:
        jobs=profiles.get(source_profile,profiles["general"])
    provider_labels={"news":"Google News","gdelt":"GDELT","wikipedia":"Wikipedia","crossref":"Crossref","arxiv":"arXiv"}
    key=_cache_key(query, [x[0] for x in jobs])
    cached=_cache_get(key)
    if cached is not None:
        cached_items=cached.get("items",[])
        cached_errors=cached.get("errors",[])
        for name,_ in jobs:
            provider=provider_labels.get(name,name.title())
            count=sum(1 for item in cached_items if provider.lower() in str(item.get("source") or "").lower() or (provider=="Google News" and item.get("source")=="Google News RSS"))
            issue=next((row for row in cached_errors if str(row.get("source") or "").lower()==provider.lower()),None)
            record_provider(provider,"degraded" if issue else "healthy",message=(issue or {}).get("message") or "Recent research cache reused to avoid an unnecessary provider request.",cached=True,evidence_count=count)
        return cached_items, cached_errors, True
    items=[]; errors=[]
    with ThreadPoolExecutor(max_workers=min(4,len(jobs) or 1)) as ex:
        futures={ex.submit(fn,query):(name,time.monotonic()) for name,fn in jobs}
        for fut in as_completed(futures):
            name,started=futures[fut]
            provider=provider_labels.get(name,name.title())
            latency=round((time.monotonic()-started)*1000)
            try:
                result=fut.result()
                if isinstance(result,tuple) and len(result)==2:
                    source_items,source_issues=result
                else:
                    source_items,source_issues=result,[]
                items.extend(source_items or [])
                errors.extend(source_issues or [])
                fallback=any(issue.get("fallback_used") for issue in (source_issues or []))
                record_provider(
                    provider,
                    "degraded" if source_issues else "healthy",
                    message=(source_issues or [{}])[0].get("message") or "Live evidence retrieved successfully.",
                    latency_ms=latency,
                    cached=fallback,
                    evidence_count=len(source_items or []),
                )
            except Exception as exc:
                issue=_friendly_exception(provider,exc)
                errors.append(issue)
                record_provider(provider,"unavailable",message=issue["message"],latency_ms=latency,evidence_count=0)
    ded=_dedupe_balanced(items)
    payload={"items":ded[:60],"errors":errors,"_ttl_seconds":PARTIAL_CACHE_TTL if errors else CACHE_TTL}
    _cache_put(key,payload)
    return ded[:60], errors, False
