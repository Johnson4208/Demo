"""Small persistent cache for provider responses.

The cache is deliberately JSON-only.  Provider files are never executed or
unpickled, which keeps a damaged or replaced cache entry from becoming code.
Freshness is decided by the caller because market, macro, and news sources all
publish on different schedules.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from threading import RLock
import time
from typing import Any

from config import STORAGE_DIR


@dataclass(frozen=True)
class CacheValue:
    value: Any
    age_seconds: float
    fresh: bool


class ProviderCache:
    def __init__(self, namespace: str):
        safe = "".join(ch for ch in str(namespace) if ch.isalnum() or ch in "-_") or "default"
        self.root = STORAGE_DIR / "provider_cache" / safe
        self._lock = RLock()

    def _path(self, key: str) -> Path:
        digest = sha256(str(key).encode("utf-8")).hexdigest()
        return self.root / f"{digest}.json"

    def get(self, key: str, *, ttl: float, stale_ttl: float | None = None) -> CacheValue | None:
        path = self._path(key)
        try:
            with self._lock:
                payload = json.loads(path.read_text(encoding="utf-8"))
            stored_at = float(payload["stored_at"])
            age = max(0.0, time.time() - stored_at)
            maximum = float(stale_ttl if stale_ttl is not None else ttl)
            if age > maximum:
                return None
            return CacheValue(payload.get("value"), age, age <= float(ttl))
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            return None

    def put(self, key: str, value: Any) -> None:
        path = self._path(key)
        temporary = path.with_suffix(".tmp")
        payload = {"stored_at": time.time(), "value": value}
        try:
            with self._lock:
                self.root.mkdir(parents=True, exist_ok=True)
                temporary.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
                temporary.replace(path)
        except OSError:
            # Cache failure must never make research unavailable.
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


MARKET_CACHE = ProviderCache("market")
MODEL_CACHE = ProviderCache("models")
EVIDENCE_CACHE = ProviderCache("evidence")
MACRO_CACHE = ProviderCache("macro")
