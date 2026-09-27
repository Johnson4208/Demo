import re
import tempfile
from pathlib import Path
from unittest import TestCase

import app as app_module


class Phase2SecurityTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.database = self.root / "phase2.sqlite3"
        self.originals = {
            "auth_db": app_module.auth.DB_PATH,
            "auth_storage": app_module.auth.STORAGE_DIR,
            "event_db": app_module.event_db.DB_PATH,
            "event_storage": app_module.event_db.STORAGE_DIR,
            "watchlist_db": app_module.watchlist.DB_PATH,
            "core_db": app_module.db.DB_PATH,
            "core_storage": app_module.db.STORAGE_DIR,
        }
        app_module.auth.DB_PATH = self.database
        app_module.auth.STORAGE_DIR = self.root
        app_module.event_db.DB_PATH = self.database
        app_module.event_db.STORAGE_DIR = self.root
        app_module.watchlist.DB_PATH = self.database
        app_module.db.DB_PATH = self.database
        app_module.db.STORAGE_DIR = self.root
        app_module.db.init_db()
        app_module.auth.init_auth_db()
        app_module.event_db.init_db()
        app_module.watchlist.init_db()
        app_module.app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
        self.client = app_module.app.test_client()
        self.first = app_module.auth.create_user("first@example.invalid", "FirstPassword123", "First User")
        self.second = app_module.auth.create_user("second@example.invalid", "SecondPassword123", "Second User")

    def tearDown(self):
        app_module.auth.DB_PATH = self.originals["auth_db"]
        app_module.auth.STORAGE_DIR = self.originals["auth_storage"]
        app_module.event_db.DB_PATH = self.originals["event_db"]
        app_module.event_db.STORAGE_DIR = self.originals["event_storage"]
        app_module.watchlist.DB_PATH = self.originals["watchlist_db"]
        app_module.db.DB_PATH = self.originals["core_db"]
        app_module.db.STORAGE_DIR = self.originals["core_storage"]
        self.temp.cleanup()

    def sign_in(self, user):
        token = app_module.auth.start_session(user["id"], user_agent="Phase 2 test")
        with self.client.session_transaction() as session:
            session.clear()
            session["user_id"] = user["id"]
            session["auth_token"] = token
            session["csrf_token"] = "phase2-csrf"

    @staticmethod
    def result(label):
        return {"factor": "growth", "focus": label, "ranked": [{"candidate": label, "normalized_probability": 100.0}]}

    def test_event_probability_routes_enforce_user_ownership(self):
        first_id = app_module.event_db.save_forecast(
            "First forecast", "30 days", "economy", self.result("First outcome"), [],
            owner_user_id=self.first["id"], workspace_id=self.first["workspace_id"],
        )
        second_id = app_module.event_db.save_forecast(
            "Second forecast", "30 days", "economy", self.result("Second outcome"), [],
            owner_user_id=self.second["id"], workspace_id=self.second["workspace_id"],
        )
        self.sign_in(self.first)

        history = self.client.get("/api/event-probability/history").get_json()["forecasts"]
        self.assertEqual([row["id"] for row in history], [first_id])
        self.assertEqual(self.client.get(f"/api/event-probability/forecast/{second_id}").status_code, 404)
        response = self.client.post(
            f"/api/event-probability/review/{second_id}", json={"saved": True},
            headers={"X-CSRF-Token": "phase2-csrf"},
        )
        self.assertEqual(response.status_code, 404)

    def test_csp_nonce_request_id_and_readiness(self):
        self.sign_in(self.first)
        response = self.client.get("/", headers={"X-Request-ID": "phase2-test-123"})
        csp = response.headers["Content-Security-Policy"]
        nonce = re.search(r"'nonce-([^']+)'", csp).group(1)
        self.assertIn(f'nonce="{nonce}"', response.get_data(as_text=True))
        self.assertIn("script-src-attr 'none'", csp)
        self.assertEqual(response.headers["X-Request-ID"], "phase2-test-123")
        self.assertEqual(self.client.get("/api/ready").status_code, 200)

    def test_templates_and_dynamic_markup_have_no_inline_handlers(self):
        source_root = Path(__file__).resolve().parents[1]
        combined = "\n".join(
            path.read_text(encoding="utf-8")
            for folder in (source_root / "templates", source_root / "static")
            for path in folder.glob("*.html") if path.is_file()
        ) + (source_root / "static" / "app.js").read_text(encoding="utf-8")
        self.assertNotRegex(combined, r"\bon(?:click|submit|change|input)\s*=")

    def test_shared_sidebar_shell_is_immune_to_feature_stylesheet(self):
        source_root = Path(__file__).resolve().parents[1]
        script = (source_root / "static" / "app.js").read_text(encoding="utf-8")
        shell = (source_root / "static" / "dashboard.css").read_text(encoding="utf-8")
        template = (source_root / "templates" / "index.html").read_text(encoding="utf-8")

        self.assertIn('if(featureStyles)featureStyles.disabled=viewName==="overview"', script)
        self.assertIn("if(dashboardStyles)dashboardStyles.disabled=false", script)
        self.assertLess(template.index('id="featureStylesheet"'), template.index('id="dashboardStylesheet"'))
        self.assertIn("one immutable left navigation shell on every feature", shell)
        self.assertIn("body .sidebar .brand", shell)
        self.assertIn("body .sidebar nav button", shell)
        self.assertIn("body.sidebar-collapsed .sidebar", shell)
        self.assertIn("@media(max-width:850px)", shell)
