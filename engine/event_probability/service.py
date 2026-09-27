from __future__ import annotations

import math
import re
from datetime import datetime, timezone

from . import db
from .catalog import CATALOG
from .sources import search_all


POSITIVE = [
    "confirmed", "approved", "announced", "signed", "completed",
    "wins", "won", "successful", "launches", "expects",
    "agreement", "record", "on track", "improve", "strong", "accelerate",
    "recovery", "supportive", "easing", "resilient", "expansion",
]
NEGATIVE = [
    "unlikely", "denied", "failed", "delay", "delayed", "canceled", "cancelled",
    "reject", "rejected", "falls short", "concern", "warning", "dispute",
    "missed", "postponed", "weaken", "decline", "slow", "restrictive",
    "deteriorate", "contraction", "uncertainty", "volatile",
]
NEUTRAL_MARKERS = ("mixed", "range-bound", "range bound", "broadly stable", "stays steady", "remains steady")
ADVERSE_NOUNS = (
    "risk", "pressure", "friction", "uncertainty", "volatility", "inflation",
    "restriction", "restrictive", "sanction", "conflict", "bad debt", "npl",
)
FAVORABLE_NOUNS = (
    "appetite", "growth", "demand", "earnings", "investment", "activity", "momentum",
    "flows", "orders", "employment", "jobs", "liquidity", "margins", "asset quality",
)
UP_WORDS = ("increase", "increases", "rises", "rise", "intensifies", "spikes", "strengthens", "accelerates")
DOWN_WORDS = ("ease", "eases", "easing", "falls", "declines", "slows", "weakens", "compresses", "deteriorates")
FAVORABLE_WORDS = ("improve", "improves", "strengthen", "strengthens", "supportive", "accommodative", "accelerate", "accelerates")
UNFAVORABLE_WORDS = ("weaken", "weakens", "deteriorate", "deteriorates", "slow", "slows", "compress", "compresses", "restrictive")
OUTCOME_STOPWORDS = {
    "the", "and", "for", "more", "turn", "become", "will", "over", "selected",
    "horizon", "conditions", "condition", "stays", "stay", "remains", "remain",
    "broadly", "momentum", "activity", "environment", "backdrop",
}


def _text(item):
    return (item.get("title", "") + " " + item.get("snippet", "")).lower()


def _recency(item):
    raw = item.get("published_at")
    if not raw:
        return 0.5
    try:
        stamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        age = max(0, (datetime.now(timezone.utc) - stamp.astimezone(timezone.utc)).days)
        return math.exp(-age / 60)
    except Exception:
        return 0.5


def _tokens(value, *, outcome=False):
    words = {word for word in re.findall(r"[a-z0-9]+", (value or "").lower()) if len(word) > 3}
    return words - OUTCOME_STOPWORDS if outcome else words


def _lexical(query, text):
    words = _tokens(query)
    if not words:
        return 0.1
    text_words = set(re.findall(r"[a-z0-9]+", (text or "").lower()))
    return min(1.0, len(words & text_words) / max(3, len(words)))


def _value_score(item, query):
    reliability = float(item.get("reliability", 0.5))
    recency = _recency(item)
    relevance = _lexical(query, _text(item))
    return round(100 * (0.45 * reliability + 0.30 * recency + 0.25 * relevance), 1)


def _has_phrase(text, phrases):
    return any(
        re.search(r"(?<!\w)" + re.escape(phrase).replace(r"\ ", r"\s+") + r"(?!\w)", text)
        for phrase in phrases
    )


def _sentiment(item):
    text = _text(item)
    positive = sum(1 for word in POSITIVE if _has_phrase(text, (word,)))
    negative = sum(1 for word in NEGATIVE if _has_phrase(text, (word,)))
    # Directional nouns need context: "risk appetite rises" is constructive,
    # while "risk pressure rises" is adverse. Avoid scoring either noun alone.
    adverse_text = text.replace("risk appetite", "appetite")
    adverse = _has_phrase(adverse_text, ADVERSE_NOUNS)
    favorable = _has_phrase(text, FAVORABLE_NOUNS)
    rising = _has_phrase(text, UP_WORDS)
    easing = _has_phrase(text, DOWN_WORDS)
    if adverse and rising:
        negative += 2
    elif adverse and easing:
        positive += 2
    elif favorable and rising:
        positive += 2
    elif favorable and easing:
        negative += 2
    return max(-1, min(1, (positive - negative) / max(2, positive + negative + 1)))


def _signal_and_confidence(items):
    if not items:
        return 0.0, 20.0
    support = oppose = weight = 0.0
    domains, source_types = set(), set()
    for item in items:
        signal = _sentiment(item)
        item_weight = float(item.get("reliability", 0.5)) * (0.35 + 0.65 * _recency(item))
        if signal > 0:
            support += signal * item_weight
        elif signal < 0:
            oppose += (-signal) * item_weight
        weight += item_weight
        url = item.get("url") or ""
        domains.add(url.split("/")[2] if "://" in url else item.get("source"))
        source_types.add(item.get("source"))
    signal = (support - oppose) / (support + oppose or 1)
    diversity = min(1, len(domains) / 6)
    source_diversity = min(1, len(source_types) / 4)
    confidence = min(0.99, 0.28 + 0.42 * min(1, weight / max(3, len(items))) + 0.18 * diversity + 0.12 * source_diversity)
    return signal, round(confidence * 100, 1)


def _tone(outcome):
    """Map an outcome to the evidence tone that would support it."""
    text = outcome.lower()
    if _has_phrase(text, NEUTRAL_MARKERS) or _has_phrase(text, ("mixed",)):
        return "neutral"
    adverse = _has_phrase(text, ADVERSE_NOUNS)
    rising = _has_phrase(text, UP_WORDS)
    easing = _has_phrase(text, DOWN_WORDS)
    if adverse and rising:
        return "negative"
    if adverse and easing:
        return "positive"
    if _has_phrase(text, ("contained",)):
        return "positive"
    if _has_phrase(text, UNFAVORABLE_WORDS):
        return "negative"
    if _has_phrase(text, FAVORABLE_WORDS) or rising:
        return "positive"
    return "neutral"


def _resolved_tones(outcomes):
    """Guarantee one supportive, one mixed, and one weakening regime for a 3-way catalog."""
    tones = [_tone(outcome) for outcome in outcomes]
    if len(outcomes) != 3:
        return tones
    neutral_candidates = [
        index for index, outcome in enumerate(outcomes)
        if _has_phrase(outcome.lower(), ("mixed", "stable", "steady", "range-bound", "range bound"))
    ]
    neutral_index = neutral_candidates[0] if neutral_candidates else 1
    tones[neutral_index] = "neutral"
    left, right = [index for index in range(3) if index != neutral_index]
    if tones[left] == "neutral" and tones[right] in {"positive", "negative"}:
        tones[left] = "negative" if tones[right] == "positive" else "positive"
    elif tones[right] == "neutral" and tones[left] in {"positive", "negative"}:
        tones[right] = "negative" if tones[left] == "positive" else "positive"
    elif tones[left] == tones[right]:
        tones[right] = "negative" if tones[left] == "positive" else "positive"
    return tones


def _tone_score(signal, tone):
    if tone == "positive":
        return math.exp(2.25 * signal)
    if tone == "negative":
        return math.exp(-2.25 * signal)
    # A genuinely balanced evidence signal should make the mixed regime more
    # likely than either directional extreme, without overwhelming them.
    return math.exp(0.42 - 1.50 * abs(signal))


def _alignment(sentiment, tone):
    if tone == "positive":
        return (sentiment + 1) / 2
    if tone == "negative":
        return (1 - sentiment) / 2
    return max(0.0, 1 - abs(sentiment))


def _evidence_bucket(sentiment, tone):
    if tone == "neutral":
        return "support" if abs(sentiment) <= 0.12 else ("mixed" if abs(sentiment) <= 0.35 else "counter")
    aligned = sentiment if tone == "positive" else -sentiment
    if aligned >= 0.12:
        return "support"
    if aligned <= -0.12:
        return "counter"
    return "mixed"


def _outcome_evidence(items, outcome, tone, base_query, limit=12):
    outcome_tokens = _tokens(outcome, outcome=True)
    scored = []
    for item in items:
        text = _text(item)
        text_tokens = set(re.findall(r"[a-z0-9]+", text))
        overlap = len(outcome_tokens & text_tokens) / max(2, len(outcome_tokens))
        sentiment = _sentiment(item)
        alignment = _alignment(sentiment, tone)
        value = float(item.get("value_score", _value_score(item, base_query))) / 100
        query_relevance = _lexical(base_query, text)
        evidence_score = 0.42 * value + 0.25 * query_relevance + 0.18 * min(1, overlap) + 0.15 * alignment
        enriched = dict(item)
        enriched["outcome_score"] = round(100 * evidence_score, 1)
        enriched["sentiment_signal"] = round(sentiment, 3)
        enriched["evidence_bucket"] = _evidence_bucket(sentiment, tone)
        scored.append(enriched)
    scored.sort(key=lambda item: (item["outcome_score"], item.get("published_at") or ""), reverse=True)
    return scored[:limit]


def _weighted_breakdown(items, tone):
    totals = {"support": 0.0, "mixed": 0.0, "counter": 0.0}
    for item in items:
        bucket = item.get("evidence_bucket") or _evidence_bucket(_sentiment(item), tone)
        weight = float(item.get("reliability", 0.5)) * (0.35 + 0.65 * _recency(item))
        weight *= 0.55 + 0.45 * float(item.get("value_score", 50)) / 100
        totals[bucket] += weight
    total = sum(totals.values()) or 1.0
    keys = ("support", "mixed", "counter")
    rounded = _rounded_distribution([totals[key] / total * 100 for key in keys])
    return dict(zip(keys, rounded))


def _driver(item):
    bucket = item.get("evidence_bucket", "mixed")
    if bucket == "support":
        reason = "Direction and factor language align with this outcome."
    elif bucket == "counter":
        reason = "This is a material counter-signal that reduces this outcome's share."
    else:
        reason = "Relevant evidence is non-directional, preserving uncertainty."
    return {
        "title": item.get("title") or "Untitled evidence",
        "source": item.get("source") or "Source",
        "published_at": item.get("published_at"),
        "value_score": item.get("value_score"),
        "outcome_score": item.get("outcome_score"),
        "bucket": bucket,
        "reason": reason,
        "url": item.get("url") or "",
    }


def _rounded_distribution(values):
    """Round percentages to one decimal while preserving an exact 100.0 total."""
    if not values:
        return []
    raw_units = [max(0.0, float(value)) * 10 for value in values]
    units = [math.floor(value) for value in raw_units]
    remainder = 1000 - sum(units)
    order = sorted(range(len(values)), key=lambda index: raw_units[index] - units[index], reverse=True)
    for index in order[:max(0, remainder)]:
        units[index] += 1
    return [unit / 10 for unit in units]


def _attach_explanation(outcome, baseline):
    analysis = outcome["analysis"]
    probability = outcome["normalized_probability"]
    delta = probability - baseline
    if delta > 0.6:
        baseline_read = f"{abs(delta):.1f} points above"
    elif delta < -0.6:
        baseline_read = f"{abs(delta):.1f} points below"
    else:
        baseline_read = "close to"
    support = analysis["counts"]["support"]
    counter = analysis["counts"]["counter"]
    mixed = analysis["counts"]["mixed"]
    outcome["why"] = (
        f"Its {probability:.1f}% evidence share is {baseline_read} the {baseline:.1f}% equal-outcome starting point. "
        f"After weighting source reliability, freshness and factor relevance, {support} items support this direction, "
        f"{counter} oppose it and {mixed} remain mixed. Confidence limits how far the estimate can move from the baseline."
    )


def _research_quality(items, errors):
    tiers = {"primary": 0, "academic": 0, "publisher": 0, "aggregator": 0}
    domains = set()
    stale = duplicates_removed = 0
    for item in items:
        meta = item.get("meta") or {}
        tier = meta.get("source_tier", "publisher")
        tiers[tier if tier in tiers else "publisher"] += 1
        if meta.get("domain"):
            domains.add(meta["domain"])
        stale += int(bool(meta.get("stale_fallback")))
        duplicates_removed += max(0, int(meta.get("duplicate_count", 1)) - 1)
    live_share = (len(items) - stale) / max(1, len(items))
    diversity = min(1.0, len(domains) / 6)
    authority = min(1.0, (tiers["primary"] * 1.0 + tiers["academic"] * 0.9 + tiers["publisher"] * 0.7 + tiers["aggregator"] * 0.5) / max(1, len(items)))
    availability = max(0.35, 1.0 - 0.12 * len(errors or []))
    score = round(100 * (0.38 * live_share + 0.32 * diversity + 0.22 * authority + 0.08 * availability)) if items else 0
    grade = "Strong" if score >= 78 else "Usable" if score >= 58 else "Limited"
    return {
        "score": score,
        "grade": grade,
        "live_items": max(0, len(items) - stale),
        "cached_items": stale,
        "independent_domains": len(domains),
        "duplicates_removed": duplicates_removed,
        "source_mix": tiers,
    }


def _monitor_signals(outcomes, factor_label):
    by_tone = {outcome["tone"]: outcome for outcome in outcomes}
    positive = by_tone.get("positive", {})
    negative = by_tone.get("negative", {})
    neutral = by_tone.get("neutral", {})
    return [
        {
            "direction": "raise",
            "title": f"Confirmation of {positive.get('candidate', 'the supportive scenario')}",
            "effect": "Could raise the supportive outcome by roughly 3–8 points.",
            "why": f"Two or more recent, high-reliability sources aligned with {factor_label.lower()} would strengthen the directional evidence signal.",
        },
        {
            "direction": "lower",
            "title": f"Evidence for {negative.get('candidate', 'the weakening scenario')}",
            "effect": "Could shift probability toward the weakening outcome.",
            "why": "An official release or several independent sources that contradict the leading drivers would reduce the current top share.",
        },
        {
            "direction": "mixed",
            "title": f"A more balanced signal set favors {neutral.get('candidate', 'the mixed scenario')}",
            "effect": "Would pull directional estimates back toward the equal baseline.",
            "why": "Conflicting evidence, older observations, or low source diversity increases uncertainty and makes the mixed regime more plausible.",
        },
        {
            "direction": "confidence",
            "title": "More primary evidence would narrow uncertainty",
            "effect": "Would increase confidence before materially changing direction.",
            "why": "Official releases and independent original reporting carry more weight than repeated aggregator headlines.",
        },
    ]


def _comparison(previous, outcomes):
    if not previous:
        return {"available": False, "message": "This is the first comparable forecast in the workspace."}
    prior_ranked = {row.get("candidate"): row for row in previous.get("result", {}).get("ranked", [])}
    changes = []
    for outcome in outcomes:
        prior = prior_ranked.get(outcome.get("candidate"))
        if not prior:
            continue
        before = float(prior.get("normalized_probability", prior.get("probability", 0)) or 0)
        after = float(outcome.get("normalized_probability", 0) or 0)
        changes.append({"candidate": outcome.get("candidate"), "previous": round(before, 1), "current": round(after, 1), "change": round(after - before, 1)})
    return {
        "available": bool(changes),
        "previous_forecast_id": previous.get("id"),
        "previous_at": previous.get("created_at"),
        "changes": changes,
    }


def catalog_options():
    return {
        key: {
            "label": value["label"],
            "factors": {factor_key: {"label": factor["label"]} for factor_key, factor in value["factors"].items()},
        }
        for key, value in CATALOG.items()
    }


def analyze_factor(category, factor, focus="", horizon="30 days", *, owner_user_id, workspace_id="default"):
    cat = CATALOG.get(category)
    if not cat or factor not in cat["factors"]:
        raise ValueError("Unknown category or factor.")
    spec = cat["factors"][factor]
    focus = (focus or "").strip()
    base_query = spec["query"] + (f" {focus}" if focus else "")
    items, errors, cache_hit = search_all(base_query, spec.get("sources", "general"))

    ranked_items = []
    for item in items:
        enriched = dict(item)
        enriched["value_score"] = _value_score(item, base_query)
        ranked_items.append(enriched)
    ranked_items.sort(key=lambda item: (item["value_score"], item.get("published_at") or ""), reverse=True)

    global_signal, global_confidence = _signal_and_confidence(ranked_items[:20])
    tones = _resolved_tones(spec["outcomes"])
    outcomes = []
    for candidate, tone in zip(spec["outcomes"], tones):
        subset = _outcome_evidence(ranked_items, candidate, tone, base_query)
        local_signal, local_confidence = _signal_and_confidence(subset)
        combined_signal = 0.72 * global_signal + 0.28 * local_signal
        confidence = round(0.65 * global_confidence + 0.35 * local_confidence, 1)
        breakdown = _weighted_breakdown(subset, tone)
        counts = {
            key: sum(1 for item in subset if item.get("evidence_bucket") == key)
            for key in ("support", "mixed", "counter")
        }
        supporting = [item for item in subset if item.get("evidence_bucket") == "support"]
        mixed = [item for item in subset if item.get("evidence_bucket") == "mixed"]
        counters = [item for item in subset if item.get("evidence_bucket") == "counter"]
        outcomes.append({
            "candidate": candidate,
            "tone": tone,
            "probability_raw": _tone_score(combined_signal, tone) if ranked_items else 1.0,
            "confidence": confidence,
            "evidence_signal": round(combined_signal, 3),
            "evidence_count": len(subset),
            "analysis": {
                "counts": counts,
                "weighted_evidence_pct": breakdown,
                "drivers": [_driver(item) for item in (supporting + mixed)[:3]],
                "counter_signals": [_driver(item) for item in counters[:2]],
            },
        })

    total = sum(outcome["probability_raw"] for outcome in outcomes) or 1
    baseline = 100.0 / max(1, len(outcomes))
    adjusted = []
    for outcome in outcomes:
        raw_probability = outcome["probability_raw"] / total * 100.0
        confidence_factor = min(0.85, max(0.35, outcome["confidence"] / 100.0))
        adjusted.append(baseline + (raw_probability - baseline) * confidence_factor)
    adjusted_total = sum(adjusted) or 1
    rounded = _rounded_distribution([value / adjusted_total * 100 for value in adjusted])
    for outcome, probability in zip(outcomes, rounded):
        outcome["normalized_probability"] = probability
        outcome["probability"] = probability
        outcome["evidence_share_pct"] = probability
        sensitivity_margin = round(max(4.0, (100.0 - float(outcome.get("confidence", 20))) * 0.12), 1)
        outcome["sensitivity_range"] = {
            "low": round(max(0.0, probability - sensitivity_margin), 1),
            "high": round(min(100.0, probability + sensitivity_margin), 1),
            "label": "model sensitivity range",
        }
        outcome.pop("probability_raw", None)
        _attach_explanation(outcome, baseline)
    outcomes.sort(key=lambda outcome: outcome["normalized_probability"], reverse=True)
    for rank, outcome in enumerate(outcomes, 1):
        outcome["rank"] = rank

    generated = datetime.now(timezone.utc).isoformat()
    previous = db.latest_comparable(
        category, horizon, factor, focus,
        owner_user_id=owner_user_id, workspace_id=workspace_id,
    )
    quality = _research_quality(ranked_items, errors)
    result = {
        "success": True,
        "category": category,
        "category_label": cat["label"],
        "factor": factor,
        "factor_label": spec["label"],
        "focus": focus,
        "horizon": horizon,
        "event": spec["event"],
        "ranked": outcomes,
        "generated_at": generated,
        "cache_hit": cache_hit,
        "comparison": _comparison(previous, outcomes),
        "monitor_signals": _monitor_signals(outcomes, spec["label"]),
        "research": {
            "items": len(ranked_items),
            "unique_sources": len({item.get("source") for item in ranked_items if item.get("source")}),
            "errors": errors,
            "top_items": ranked_items[:12],
            "quality": quality,
        },
        "probability_model": {
            "display_label": "Evidence-weighted share",
            "calibrated_probability": False,
            "semantic_stage": "event_research",
            "baseline_pct": round(baseline, 1),
            "total_pct": round(sum(outcome["normalized_probability"] for outcome in outcomes), 1),
            "global_evidence_signal": round(global_signal, 3),
            "global_confidence_pct": global_confidence,
            "explanation": (
                "The three mutually exclusive outcomes begin at equal weights. Evidence is then weighted by source reliability, "
                "freshness, relevance and directional language. Low confidence pulls every estimate back toward the equal-weight "
                "baseline; the final shares are normalized to exactly 100.0%."
            ),
            "uncertainty_note": "The displayed ranges are model-sensitivity bands, not statistical confidence intervals, calibrated probabilities, or guarantees.",
        },
        "method": (
            "Evidence-weighted scenario analysis using source reliability, recency, factor relevance, directional language and source diversity. "
            "The percentages are normalized evidence shares for comparing mutually exclusive scenarios; they are not calibrated outcome probabilities or forecast guarantees."
        ),
    }
    try:
        db.init_db()
        result["forecast_id"] = db.save_forecast(
            spec["event"], horizon, category, result, ranked_items[:40],
            owner_user_id=owner_user_id, workspace_id=workspace_id,
        )
        result["review"] = {"saved": False, "note": "", "resolved_outcome": None}
    except Exception as exc:
        result["history_warning"] = str(exc)
    return result
