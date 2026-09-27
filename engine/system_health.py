from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from config import STORAGE_DIR


HEALTH_PATH = Path(STORAGE_DIR) / "system_health.json"
_LOCK = threading.Lock()
KNOWN_PROVIDERS = (
    "Local report library",
    "Yahoo Finance",
    "Macro data",
    "Market news",
    "Google News",
    "GDELT",
    "Crossref",
    "arXiv",
    "Wikipedia",
)


def _read() -> dict:
    try:
        value = json.loads(HEALTH_PATH.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _write(payload: dict) -> None:
    try:
        HEALTH_PATH.parent.mkdir(parents=True, exist_ok=True)
        temp = HEALTH_PATH.with_suffix(".tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        temp.replace(HEALTH_PATH)
    except Exception:
        # Health reporting must never break a research request.
        pass


def record_provider(
    name: str,
    status: str,
    *,
    message: str = "",
    latency_ms: int | float | None = None,
    cached: bool = False,
    evidence_count: int | None = None,
) -> None:
    safe_status = status if status in {"healthy", "degraded", "unavailable"} else "degraded"
    safe_message = " ".join(str(message or "").split())[:220]
    now = datetime.now(timezone.utc).isoformat()
    with _LOCK:
        payload = _read()
        previous = payload.get(name, {}) if isinstance(payload.get(name), dict) else {}
        payload[name] = {
            "name": name,
            "status": safe_status,
            "message": safe_message,
            "checked_at": now,
            "latency_ms": None if latency_ms is None else max(0, round(float(latency_ms))),
            "cached": bool(cached),
            "evidence_count": evidence_count,
            "last_success_at": now if safe_status == "healthy" else previous.get("last_success_at"),
        }
        _write(payload)


def provider_snapshot(local_stats: dict | None = None) -> dict:
    payload = _read()
    if local_stats is not None:
        report_count = int(local_stats.get("reports") or 0)
        company_count = int(local_stats.get("companies") or 0)
        payload["Local report library"] = {
            "name": "Local report library",
            "status": "healthy" if report_count else "degraded",
            "message": (
                f"{report_count} indexed reports across {company_count} companies."
                if report_count
                else "No indexed reports are available yet."
            ),
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "last_success_at": datetime.now(timezone.utc).isoformat() if report_count else None,
            "latency_ms": None,
            "cached": False,
            "evidence_count": report_count,
        }

    now = time.time()
    providers = []
    for name in KNOWN_PROVIDERS:
        row = dict(payload.get(name) or {})
        checked_at = row.get("checked_at")
        age_seconds = None
        if checked_at:
            try:
                age_seconds = max(0, int(now - datetime.fromisoformat(checked_at).timestamp()))
            except Exception:
                age_seconds = None
        providers.append({
            "name": name,
            "status": row.get("status", "not_checked"),
            "message": row.get("message") or "Not used during this session yet.",
            "checked_at": checked_at,
            "last_success_at": row.get("last_success_at"),
            "latency_ms": row.get("latency_ms"),
            "cached": bool(row.get("cached")),
            "evidence_count": row.get("evidence_count"),
            "age_seconds": age_seconds,
        })

    used = [row for row in providers if row["status"] != "not_checked"]
    weights = {"healthy": 100, "degraded": 64, "unavailable": 25, "not_checked": 50}
    score = round(sum(weights[row["status"]] for row in used) / len(used)) if used else 50
    unavailable = sum(row["status"] == "unavailable" for row in used)
    degraded = sum(row["status"] == "degraded" for row in used)
    if unavailable:
        label = "Some sources unavailable"
    elif degraded:
        label = "Operating with fallbacks"
    elif used:
        label = "All checked systems healthy"
    else:
        label = "Waiting for first data request"
    return {
        "success": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "score": score,
        "label": label,
        "checked_providers": len(used),
        "providers": providers,
    }
