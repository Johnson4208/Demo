from __future__ import annotations
import math, re
from datetime import datetime, timezone
from dateutil import parser as dtparse

POSITIVE = ["confirmed","announced","approved","signed","completed","increased","wins","won","successful","launches","will","expects","forecast","likely","agreement","record","evidence supports","on track"]
NEGATIVE = ["unlikely","denied","failed","delay","delayed","canceled","cancelled","reject","rejected","falls short","risk","concern","warning","dispute","missed","postponed"]


def _text(item): return ((item.get("title","")+" "+item.get("snippet","")).lower())

def _sentiment(item):
    t=_text(item); p=sum(1 for w in POSITIVE if w in t); n=sum(1 for w in NEGATIVE if w in t)
    return max(-1,min(1,(p-n)/max(2,p+n+1)))


def _recency_weight(item):
    raw=item.get("published_at")
    if not raw: return .55
    try:
        d=dtparse.parse(raw); age=max(0,(datetime.now(timezone.utc)-d.astimezone(timezone.utc)).days)
        return math.exp(-age/90)
    except Exception: return .55


def _prior(category,horizon):
    cat=(category or "general").lower()
    priors={"general":.5,"politics":.5,"economics":.5,"business":.5,"technology":.5,"science":.35,"weather":.45,"sports":.5}
    p=priors.get(cat,.5)
    if horizon:
        h=horizon.lower()
        if "hour" in h or "today" in h: p*=.92
        elif "week" in h: p*=.97
        elif "month" in h: p*=1.00
        elif "year" in h: p*=1.05
    return max(.05,min(.95,p))


def _claim_score(items):
    if not items: return 0.0,0.0,0,0
    weighted=[]; support=oppose=0.0; domains=set(); source_types=set()
    for x in items:
        s=_sentiment(x); w=float(x.get("reliability",.5))*(.35+.65*_recency_weight(x))
        weighted.append((s,w));
        if s>0: support += s*w
        if s<0: oppose += (-s)*w
        u=x.get("url") or ""; domains.add(u.split('/')[2] if '://' in u else x.get("source"))
        source_types.add(x.get("source"))
    total=support+oppose or 1
    signal=(support-oppose)/total
    evidence_strength=min(1,(support+oppose)/max(2,len(items)*.7))
    diversity=min(1,len(domains)/6)
    source_div=min(1,len(source_types)/4)
    return signal,evidence_strength,diversity,source_div


def forecast_probability(candidate, research_items, category="general", horizon=None):
    p0=_prior(category,horizon)
    signal,strength,diversity,source_div=_claim_score(research_items)
    # Query-specific lexical anchors modestly shift the prior; evidence dominates.
    cand=(candidate or "").lower()
    direct_yes=sum(1 for x in research_items if any(k in _text(x) for k in ("confirmed","approved","announced","signed","completed")))
    direct_no=sum(1 for x in research_items if any(k in _text(x) for k in ("denied","rejected","canceled","cancelled","failed")))
    direct=(direct_yes-direct_no)/max(4,len(research_items))
    raw=math.log(p0/(1-p0)) + 1.45*signal*max(.25,strength) + .45*direct + .22*(diversity-.5) + .18*(source_div-.5)
    p=1/(1+math.exp(-raw))
    # Research completeness is intentionally separate from probability confidence.
    confidence=min(0.99, .30 + .38*strength + .16*diversity + .12*source_div)
    return {"probability":round(p*100,1),"confidence":round(confidence*100,1),"evidence_signal":round(signal,3),"evidence_strength":round(strength,3),"source_diversity":round(diversity,3),"source_type_diversity":round(source_div,3),"supporting":direct_yes,"opposing":direct_no}


def rank_candidates(candidates, research_by_candidate, category="general", horizon=None):
    out=[]
    for c in candidates:
        stats=forecast_probability(c,research_by_candidate.get(c,[]),category,horizon)
        out.append({"candidate":c,**stats})
    out.sort(key=lambda x:(x["probability"],x["confidence"]),reverse=True)
    for i,x in enumerate(out,1): x["rank"]=i
    # Normalize multi-outcome ranks to a proper probability distribution when the user supplied alternatives.
    if len(out)>1:
        s=sum(x["probability"] for x in out)
        if s>0:
            for x in out: x["normalized_probability"]=round(x["probability"]/s*100,1)
    else:
        out[0]["normalized_probability"]=out[0]["probability"]
    return out
