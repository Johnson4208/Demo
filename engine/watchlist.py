"""Per-user valuation watchlists, history, and explainable alerts.

All rows are scoped by both user and workspace. Passwords, session tokens, and
manual valuation inputs never enter these tables.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sqlite3

from config import DB_PATH


def _connect():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=30000")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _finite(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _loads(value, fallback):
    try:
        loaded = json.loads(value) if value else fallback
        return loaded
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback


def _scope(user_id, workspace_id):
    return int(user_id), str(workspace_id or "default")[:64]


def _ensure_column(connection, table, column, definition):
    columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def init_db():
    with _connect() as connection:
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS valuation_snapshots(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                workspace_id TEXT NOT NULL,
                company TEXT NOT NULL,
                ticker TEXT,
                currency TEXT,
                market_price REAL,
                fair_value REAL,
                research_entry_price REAL,
                bear_value REAL,
                base_value REAL,
                bull_value REAL,
                confidence_score REAL,
                confidence_label TEXT,
                assumptions_json TEXT NOT NULL,
                source_evidence_json TEXT NOT NULL,
                summary_json TEXT NOT NULL,
                scenarios_json TEXT NOT NULL,
                signature TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                UNIQUE(user_id,workspace_id,company,signature)
            );
            CREATE TABLE IF NOT EXISTS watchlist_items(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                workspace_id TEXT NOT NULL,
                company TEXT NOT NULL,
                ticker TEXT,
                currency TEXT,
                preferred_entry_threshold REAL,
                above_range_threshold REAL,
                valuation_change_pct REAL NOT NULL DEFAULT 10,
                alert_price_below INTEGER NOT NULL DEFAULT 1,
                alert_price_above INTEGER NOT NULL DEFAULT 1,
                alert_valuation_change INTEGER NOT NULL DEFAULT 1,
                alert_new_evidence INTEGER NOT NULL DEFAULT 1,
                last_snapshot_id INTEGER,
                last_price REAL,
                last_fair_value REAL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(last_snapshot_id) REFERENCES valuation_snapshots(id) ON DELETE SET NULL,
                UNIQUE(user_id,workspace_id,company)
            );
            CREATE TABLE IF NOT EXISTS user_alerts(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                workspace_id TEXT NOT NULL,
                company TEXT NOT NULL,
                kind TEXT NOT NULL,
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                severity TEXT NOT NULL DEFAULT 'info',
                metric_value REAL,
                trigger_value REAL,
                dedupe_key TEXT NOT NULL,
                created_at TEXT NOT NULL,
                read_at TEXT,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                UNIQUE(user_id,workspace_id,dedupe_key)
            );
            CREATE INDEX IF NOT EXISTS idx_valuation_history_scope ON valuation_snapshots(user_id,workspace_id,company,created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_watchlist_scope ON watchlist_items(user_id,workspace_id,updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_alert_scope ON user_alerts(user_id,workspace_id,read_at,created_at DESC);
        """)
        _ensure_column(connection, "valuation_snapshots", "currency", "TEXT")
        _ensure_column(connection, "watchlist_items", "currency", "TEXT")


def readiness_check():
    """Return a non-sensitive storage readiness result for the monitor tables."""
    try:
        with _connect() as connection:
            required = {"valuation_snapshots", "watchlist_items", "user_alerts"}
            rows = connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name IN (?,?,?)",
                tuple(sorted(required)),
            ).fetchall()
            connection.execute("SELECT COUNT(*) FROM watchlist_items").fetchone()
        return {row["name"] for row in rows} == required
    except (OSError, sqlite3.Error):
        return False


def _scenario_values(valuation):
    rows = {str(row.get("key") or ""): row for row in valuation.get("scenarios") or []}
    return (
        _finite(rows.get("bear", {}).get("fair_value")),
        _finite(rows.get("base", {}).get("fair_value")),
        _finite(rows.get("bull", {}).get("fair_value")),
    )


def _snapshot_payload(row):
    if not row:
        return None
    return {
        "id": int(row["id"]),
        "company": row["company"],
        "ticker": row["ticker"],
        "currency": row["currency"] or "VND",
        "market_price": row["market_price"],
        "fair_value": row["fair_value"],
        "research_entry_price": row["research_entry_price"],
        "bear_value": row["bear_value"],
        "base_value": row["base_value"],
        "bull_value": row["bull_value"],
        "confidence_score": row["confidence_score"],
        "confidence_label": row["confidence_label"],
        "assumptions": _loads(row["assumptions_json"], {}),
        "source_evidence": _loads(row["source_evidence_json"], []),
        "summary": _loads(row["summary_json"], {}),
        "scenarios": _loads(row["scenarios_json"], []),
        "created_at": row["created_at"],
    }


def _latest_snapshot(connection, user_id, workspace_id, company):
    return connection.execute(
        "SELECT * FROM valuation_snapshots WHERE user_id=? AND workspace_id=? AND company=? ORDER BY created_at DESC,id DESC LIMIT 1",
        (user_id, workspace_id, company),
    ).fetchone()


def latest_snapshot(user_id, workspace_id, company):
    user_id, workspace_id = _scope(user_id, workspace_id)
    with _connect() as connection:
        return _snapshot_payload(_latest_snapshot(connection, user_id, workspace_id, company.upper()))


def _source_dates(snapshot):
    return {
        str(row.get("field")): str(row.get("as_of"))
        for row in (snapshot or {}).get("source_evidence") or []
        if row.get("field") and row.get("as_of")
    }


def _insert_alert(connection, user_id, workspace_id, company, kind, title, message, severity, metric_value, trigger_value):
    day = datetime.now(timezone.utc).date().isoformat()
    dedupe_key = f"{company}:{kind}:{day}"
    cursor = connection.execute(
        """INSERT OR IGNORE INTO user_alerts(
            user_id,workspace_id,company,kind,title,message,severity,metric_value,trigger_value,dedupe_key,created_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (user_id, workspace_id, company, kind, title[:120], message[:500], severity, metric_value, trigger_value, dedupe_key, _now()),
    )
    return 1 if cursor.rowcount else 0


def _evaluate_alerts(connection, watch, previous, current):
    created = 0
    company = watch["company"]
    price = _finite(current.get("market_price"))
    old_price = _finite(previous.get("market_price")) if previous else None
    fair = _finite(current.get("fair_value"))
    old_fair = _finite(previous.get("fair_value")) if previous else None
    entry = _finite(watch["preferred_entry_threshold"])
    above = _finite(watch["above_range_threshold"])

    if watch["alert_price_below"] and price is not None and entry is not None and price <= entry and (old_price is None or old_price > entry):
        created += _insert_alert(connection, watch["user_id"], watch["workspace_id"], company, "price_entry", f"{company} entered the research-entry range", f"Current price {price:,.2f} is at or below the saved threshold {entry:,.2f}.", "positive", price, entry)
    if watch["alert_price_above"] and price is not None and above is not None and price >= above and (old_price is None or old_price < above):
        created += _insert_alert(connection, watch["user_id"], watch["workspace_id"], company, "price_above", f"{company} moved above the modeled range", f"Current price {price:,.2f} is at or above the saved threshold {above:,.2f}.", "warning", price, above)
    if watch["alert_valuation_change"] and fair is not None and old_fair not in (None, 0):
        change_pct = abs(fair / old_fair - 1.0) * 100.0
        threshold = _finite(watch["valuation_change_pct"]) or 10.0
        if change_pct >= threshold:
            direction = "increased" if fair > old_fair else "decreased"
            created += _insert_alert(connection, watch["user_id"], watch["workspace_id"], company, "valuation_change", f"{company} valuation changed materially", f"Base fair value {direction} by {change_pct:.1f}% from {old_fair:,.2f} to {fair:,.2f}.", "info", change_pct, threshold)
    if watch["alert_new_evidence"] and previous:
        previous_dates = _source_dates(previous)
        current_dates = _source_dates(current)
        changed = [field for field, value in current_dates.items() if value and value != previous_dates.get(field)]
        if changed:
            created += _insert_alert(connection, watch["user_id"], watch["workspace_id"], company, "new_evidence", f"New valuation evidence for {company}", f"Source dates changed for: {', '.join(changed[:5])}. Recheck the valuation assumptions.", "info", None, None)
    return created


def record_valuation(user_id, workspace_id, valuation):
    """Save one calculation and evaluate alerts; skip any manual-input run."""
    user_id, workspace_id = _scope(user_id, workspace_id)
    company = str(valuation.get("company") or "").strip().upper()
    if not company:
        return {"saved": False, "reason": "Company is unavailable."}
    if (valuation.get("market") or {}).get("manual_fields") or (valuation.get("forward_driver_model") or {}).get("manual_fields"):
        return {"saved": False, "reason": "Manual-input valuations remain calculation-only and are not saved."}

    summary = valuation.get("summary") or {}
    quality = valuation.get("data_quality") or {}
    bear, base, bull = _scenario_values(valuation)
    core = {
        "company": company,
        "price": _finite((valuation.get("market") or {}).get("price")),
        "fair": _finite(summary.get("fair_value")),
        "entry": _finite(summary.get("research_entry_price")),
        "bear": bear,
        "base": base,
        "bull": bull,
        "confidence": _finite(quality.get("score")),
        "assumptions": valuation.get("assumptions") or {},
        "source_dates": _source_dates({"source_evidence": valuation.get("source_evidence") or []}),
        "hour": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H"),
    }
    signature = hashlib.sha256(_json(core).encode("utf-8")).hexdigest()
    created_at = _now()
    with _connect() as connection:
        previous_row = _latest_snapshot(connection, user_id, workspace_id, company)
        previous = _snapshot_payload(previous_row)
        cursor = connection.execute(
            """INSERT OR IGNORE INTO valuation_snapshots(
                user_id,workspace_id,company,ticker,currency,market_price,fair_value,research_entry_price,
                bear_value,base_value,bull_value,confidence_score,confidence_label,assumptions_json,
                source_evidence_json,summary_json,scenarios_json,signature,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                user_id, workspace_id, company, str(valuation.get("ticker") or "")[:40], str(valuation.get("currency") or "VND")[:5], core["price"], core["fair"], core["entry"],
                bear, base, bull, core["confidence"], str(quality.get("label") or "Low")[:20], _json(valuation.get("assumptions") or {}),
                _json(valuation.get("source_evidence") or []), _json(summary), _json(valuation.get("scenarios") or []), signature, created_at,
            ),
        )
        if not cursor.rowcount:
            existing = connection.execute(
                "SELECT id FROM valuation_snapshots WHERE user_id=? AND workspace_id=? AND company=? AND signature=?",
                (user_id, workspace_id, company, signature),
            ).fetchone()
            return {"saved": False, "duplicate": True, "snapshot_id": int(existing["id"]) if existing else None, "alerts_created": 0}
        snapshot_id = int(cursor.lastrowid)
        current = _snapshot_payload(connection.execute("SELECT * FROM valuation_snapshots WHERE id=?", (snapshot_id,)).fetchone())
        watch = connection.execute(
            "SELECT * FROM watchlist_items WHERE user_id=? AND workspace_id=? AND company=?",
            (user_id, workspace_id, company),
        ).fetchone()
        alerts_created = 0
        if watch:
            alerts_created = _evaluate_alerts(connection, watch, previous, current)
            connection.execute(
                "UPDATE watchlist_items SET ticker=?,currency=?,last_snapshot_id=?,last_price=?,last_fair_value=?,updated_at=? WHERE id=?",
                (current["ticker"], current["currency"], snapshot_id, current["market_price"], current["fair_value"], created_at, watch["id"]),
            )
        return {"saved": True, "snapshot_id": snapshot_id, "alerts_created": alerts_created}


def upsert_watchlist(user_id, workspace_id, company, settings=None):
    user_id, workspace_id = _scope(user_id, workspace_id)
    company = str(company or "").strip().upper()
    settings = settings if isinstance(settings, dict) else {}
    with _connect() as connection:
        snapshot_row = _latest_snapshot(connection, user_id, workspace_id, company)
        if not snapshot_row:
            raise ValueError("Calculate this company's core value before adding it to the watchlist.")
        snapshot = _snapshot_payload(snapshot_row)
        default_above = _finite(snapshot["summary"].get("fair_range_high"))
        if default_above is not None:
            default_above *= 1.10

        def number(name, default, low=0.0, high=1e18):
            value = _finite(settings.get(name))
            if value is None:
                value = default
            if value is None:
                return None
            return max(low, min(high, value))

        preferred = number("preferred_entry_threshold", snapshot["research_entry_price"])
        above = number("above_range_threshold", default_above)
        change_pct = number("valuation_change_pct", 10.0, 1.0, 100.0)
        now = _now()
        connection.execute(
            """INSERT INTO watchlist_items(
                user_id,workspace_id,company,ticker,currency,preferred_entry_threshold,above_range_threshold,
                valuation_change_pct,alert_price_below,alert_price_above,alert_valuation_change,
                alert_new_evidence,last_snapshot_id,last_price,last_fair_value,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(user_id,workspace_id,company) DO UPDATE SET
                ticker=excluded.ticker,currency=excluded.currency,preferred_entry_threshold=excluded.preferred_entry_threshold,
                above_range_threshold=excluded.above_range_threshold,valuation_change_pct=excluded.valuation_change_pct,
                alert_price_below=excluded.alert_price_below,alert_price_above=excluded.alert_price_above,
                alert_valuation_change=excluded.alert_valuation_change,alert_new_evidence=excluded.alert_new_evidence,
                last_snapshot_id=excluded.last_snapshot_id,last_price=excluded.last_price,
                last_fair_value=excluded.last_fair_value,updated_at=excluded.updated_at
            """,
            (
                user_id, workspace_id, company, snapshot["ticker"], snapshot["currency"], preferred, above, change_pct,
                int(bool(settings.get("alert_price_below", True))), int(bool(settings.get("alert_price_above", True))),
                int(bool(settings.get("alert_valuation_change", True))), int(bool(settings.get("alert_new_evidence", True))),
                snapshot["id"], snapshot["market_price"], snapshot["fair_value"], now, now,
            ),
        )
    return get_watchlist_item(user_id, workspace_id, company)


def _watchlist_payload(row):
    return {
        "id": int(row["id"]),
        "company": row["company"],
        "ticker": row["ticker"],
        "currency": row["currency"] or "VND",
        "preferred_entry_threshold": row["preferred_entry_threshold"],
        "above_range_threshold": row["above_range_threshold"],
        "valuation_change_pct": row["valuation_change_pct"],
        "alert_price_below": bool(row["alert_price_below"]),
        "alert_price_above": bool(row["alert_price_above"]),
        "alert_valuation_change": bool(row["alert_valuation_change"]),
        "alert_new_evidence": bool(row["alert_new_evidence"]),
        "last_snapshot_id": row["last_snapshot_id"],
        "last_price": row["last_price"],
        "last_fair_value": row["last_fair_value"],
        "unread_alerts": int(row["unread_alerts"] or 0) if "unread_alerts" in row.keys() else 0,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def get_watchlist_item(user_id, workspace_id, company):
    user_id, workspace_id = _scope(user_id, workspace_id)
    with _connect() as connection:
        row = connection.execute(
            """SELECT w.*,(SELECT COUNT(*) FROM user_alerts a WHERE a.user_id=w.user_id AND a.workspace_id=w.workspace_id AND a.company=w.company AND a.read_at IS NULL) unread_alerts
               FROM watchlist_items w WHERE w.user_id=? AND w.workspace_id=? AND w.company=?""",
            (user_id, workspace_id, company.upper()),
        ).fetchone()
        return _watchlist_payload(row) if row else None


def list_watchlist(user_id, workspace_id):
    user_id, workspace_id = _scope(user_id, workspace_id)
    with _connect() as connection:
        rows = connection.execute(
            """SELECT w.*,(SELECT COUNT(*) FROM user_alerts a WHERE a.user_id=w.user_id AND a.workspace_id=w.workspace_id AND a.company=w.company AND a.read_at IS NULL) unread_alerts
               FROM watchlist_items w WHERE w.user_id=? AND w.workspace_id=? ORDER BY w.updated_at DESC,w.company""",
            (user_id, workspace_id),
        ).fetchall()
        unread = int(connection.execute(
            "SELECT COUNT(*) FROM user_alerts WHERE user_id=? AND workspace_id=? AND read_at IS NULL",
            (user_id, workspace_id),
        ).fetchone()[0])
    return {"items": [_watchlist_payload(row) for row in rows], "unread_alerts": unread}


def remove_watchlist(user_id, workspace_id, company):
    user_id, workspace_id = _scope(user_id, workspace_id)
    with _connect() as connection:
        cursor = connection.execute(
            "DELETE FROM watchlist_items WHERE user_id=? AND workspace_id=? AND company=?",
            (user_id, workspace_id, company.upper()),
        )
        return bool(cursor.rowcount)


def list_history(user_id, workspace_id, company, limit=30):
    user_id, workspace_id = _scope(user_id, workspace_id)
    limit = max(1, min(100, int(limit)))
    with _connect() as connection:
        rows = connection.execute(
            "SELECT * FROM valuation_snapshots WHERE user_id=? AND workspace_id=? AND company=? ORDER BY created_at DESC,id DESC LIMIT ?",
            (user_id, workspace_id, company.upper(), limit),
        ).fetchall()
    return [_snapshot_payload(row) for row in rows]


def list_alerts(user_id, workspace_id, limit=50, unread_only=False):
    user_id, workspace_id = _scope(user_id, workspace_id)
    limit = max(1, min(100, int(limit)))
    where = " AND read_at IS NULL" if unread_only else ""
    with _connect() as connection:
        rows = connection.execute(
            f"SELECT * FROM user_alerts WHERE user_id=? AND workspace_id=?{where} ORDER BY created_at DESC,id DESC LIMIT ?",
            (user_id, workspace_id, limit),
        ).fetchall()
        unread = int(connection.execute(
            "SELECT COUNT(*) FROM user_alerts WHERE user_id=? AND workspace_id=? AND read_at IS NULL",
            (user_id, workspace_id),
        ).fetchone()[0])
    return {
        "alerts": [{
            "id": int(row["id"]), "company": row["company"], "kind": row["kind"],
            "title": row["title"], "message": row["message"], "severity": row["severity"],
            "metric_value": row["metric_value"], "trigger_value": row["trigger_value"],
            "created_at": row["created_at"], "read_at": row["read_at"],
        } for row in rows],
        "unread_alerts": unread,
    }


def mark_alert_read(user_id, workspace_id, alert_id=None):
    user_id, workspace_id = _scope(user_id, workspace_id)
    now = _now()
    with _connect() as connection:
        if alert_id is None:
            cursor = connection.execute(
                "UPDATE user_alerts SET read_at=? WHERE user_id=? AND workspace_id=? AND read_at IS NULL",
                (now, user_id, workspace_id),
            )
        else:
            cursor = connection.execute(
                "UPDATE user_alerts SET read_at=? WHERE id=? AND user_id=? AND workspace_id=? AND read_at IS NULL",
                (now, int(alert_id), user_id, workspace_id),
            )
        return int(cursor.rowcount)
