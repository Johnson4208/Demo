import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app as app_module
from engine import auth, watchlist


def valuation(price=120.0, fair=125.0, source_date="2026-09-01", manual=False):
    return {
        "success": True,
        "company": "FPT",
        "ticker": "FPT.VN",
        "currency": "VND",
        "market": {
            "price": price,
            "updated_at": source_date + "T00:00:00+00:00",
            "source": "Deterministic test data",
            "manual_fields": ["price"] if manual else [],
        },
        "assumptions": {"required_return_pct": 12, "near_growth_pct": 8, "terminal_growth_pct": 4},
        "summary": {
            "fair_value": fair,
            "fair_range_low": fair * 0.85,
            "fair_range_high": fair * 1.2,
            "research_entry_price": 100.0,
            "zone": "watch_or_hold",
        },
        "scenarios": [
            {"key": "bear", "fair_value": fair * 0.75},
            {"key": "base", "fair_value": fair},
            {"key": "bull", "fair_value": fair * 1.3},
        ],
        "data_quality": {"score": 82, "label": "High"},
        "source_evidence": [
            {"field": "Market price", "value": price, "source": "Test provider", "as_of": source_date},
            {"field": "Trailing EPS", "value": 8, "source": "Test provider", "as_of": source_date},
        ],
    }


class WatchlistStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original_auth_db = auth.DB_PATH
        self.original_auth_storage = auth.STORAGE_DIR
        self.original_watchlist_db = watchlist.DB_PATH
        test_path = Path(self.temp.name) / "watchlist.sqlite3"
        auth.DB_PATH = test_path
        auth.STORAGE_DIR = Path(self.temp.name)
        watchlist.DB_PATH = test_path
        auth.init_auth_db()
        watchlist.init_db()
        self.user = auth.create_user("watch@example.com", "WatchlistPass123", "Watch User")

    def tearDown(self):
        auth.DB_PATH = self.original_auth_db
        auth.STORAGE_DIR = self.original_auth_storage
        watchlist.DB_PATH = self.original_watchlist_db
        self.temp.cleanup()

    def test_history_watchlist_and_explainable_alerts_are_user_scoped(self):
        first = watchlist.record_valuation(self.user["id"], "default", valuation())
        self.assertTrue(first["saved"])
        item = watchlist.upsert_watchlist(self.user["id"], "default", "FPT")
        self.assertEqual(item["preferred_entry_threshold"], 100.0)

        crossed = watchlist.record_valuation(self.user["id"], "default", valuation(price=90.0, fair=150.0, source_date="2026-09-02"))
        self.assertTrue(crossed["saved"])
        self.assertGreaterEqual(crossed["alerts_created"], 3)

        history = watchlist.list_history(self.user["id"], "default", "FPT")
        alerts = watchlist.list_alerts(self.user["id"], "default")
        self.assertEqual(len(history), 2)
        self.assertGreaterEqual(alerts["unread_alerts"], 3)
        self.assertTrue({"price_entry", "valuation_change", "new_evidence"}.issubset({row["kind"] for row in alerts["alerts"]}))

        other = auth.create_user("other@example.com", "OtherUserPass123", "Other User")
        self.assertEqual(watchlist.list_watchlist(other["id"], "default")["items"], [])
        self.assertEqual(watchlist.list_history(other["id"], "default", "FPT"), [])

    def test_manual_input_valuation_is_never_saved(self):
        result = watchlist.record_valuation(self.user["id"], "default", valuation(manual=True))
        self.assertFalse(result["saved"])
        self.assertIn("calculation-only", result["reason"])
        self.assertEqual(watchlist.list_history(self.user["id"], "default", "FPT"), [])

    def test_alerts_can_be_marked_read_and_watchlist_removed(self):
        watchlist.record_valuation(self.user["id"], "default", valuation())
        watchlist.upsert_watchlist(self.user["id"], "default", "FPT")
        watchlist.record_valuation(self.user["id"], "default", valuation(price=90.0, fair=150.0, source_date="2026-09-02"))
        before = watchlist.list_alerts(self.user["id"], "default")
        self.assertGreater(before["unread_alerts"], 0)
        watchlist.mark_alert_read(self.user["id"], "default")
        self.assertEqual(watchlist.list_alerts(self.user["id"], "default")["unread_alerts"], 0)
        self.assertTrue(watchlist.remove_watchlist(self.user["id"], "default", "FPT"))


class WatchlistRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original_auth_db = app_module.auth.DB_PATH
        self.original_auth_storage = app_module.auth.STORAGE_DIR
        self.original_watchlist_db = app_module.watchlist.DB_PATH
        test_path = Path(self.temp.name) / "routes.sqlite3"
        app_module.auth.DB_PATH = test_path
        app_module.auth.STORAGE_DIR = Path(self.temp.name)
        app_module.watchlist.DB_PATH = test_path
        app_module.auth.init_auth_db()
        app_module.watchlist.init_db()
        app_module.app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
        self.client = app_module.app.test_client()
        user = app_module.auth.create_user("routes@example.com", "RouteUserPass123", "Route User")
        token = app_module.auth.start_session(user["id"], user_agent="Watchlist route test")
        with self.client.session_transaction() as session:
            session["user_id"] = user["id"]
            session["auth_token"] = token
            session["csrf_token"] = "watchlist-csrf"

    def tearDown(self):
        app_module.auth.DB_PATH = self.original_auth_db
        app_module.auth.STORAGE_DIR = self.original_auth_storage
        app_module.watchlist.DB_PATH = self.original_watchlist_db
        self.temp.cleanup()

    def test_valuation_is_recorded_then_watchlist_and_history_are_available(self):
        with patch.object(app_module, "value_company", return_value=valuation()):
            response = self.client.post(
                "/api/valuation/FPT", json={"assumptions": {}},
                headers={"X-CSRF-Token": "watchlist-csrf"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["persistence"]["saved"])

        saved = self.client.post(
            "/api/watchlist/FPT", json={}, headers={"X-CSRF-Token": "watchlist-csrf"}
        )
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.get_json()["item"]["company"], "FPT")
        self.assertEqual(len(self.client.get("/api/watchlist").get_json()["items"]), 1)
        self.assertEqual(len(self.client.get("/api/valuation/history/FPT").get_json()["history"]), 1)

        denied = self.client.delete("/api/watchlist/FPT")
        self.assertEqual(denied.status_code, 400)


class WatchlistUITests(unittest.TestCase):
    def test_monitor_and_chat_polish_are_present(self):
        root = Path(__file__).resolve().parents[1]
        template = (root / "templates" / "index.html").read_text(encoding="utf-8")
        script = (root / "static" / "app.js").read_text(encoding="utf-8")
        styles = (root / "static" / "dashboard.css").read_text(encoding="utf-8")
        self.assertIn('data-view="watchlist"', template)
        self.assertIn('id="watchlistItems"', template)
        self.assertIn('id="watchlistAlerts"', template)
        self.assertIn('id="valuationHistoryOut"', template)
        self.assertIn("function loadWatchlistWorkspace", script)
        self.assertIn("function watchlistHistoryChart", script)
        self.assertIn("'watchlist-add'", script)
        self.assertIn("SolvAI30 chat polish", styles)
        self.assertIn('.assistant-composer{display:grid', styles)
        self.assertIn('.notification-button.has-unread i{display:block}', styles)


if __name__ == "__main__":
    unittest.main()
