import sqlite3
import tempfile
import unittest
from pathlib import Path

from engine import auth


class AuthenticationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original_db = auth.DB_PATH
        self.original_storage = auth.STORAGE_DIR
        auth.STORAGE_DIR = Path(self.temp.name)
        auth.DB_PATH = auth.STORAGE_DIR / "auth-test.sqlite3"
        auth.init_auth_db()

    def tearDown(self):
        auth.DB_PATH = self.original_db
        auth.STORAGE_DIR = self.original_storage
        self.temp.cleanup()

    def test_self_registered_account_is_viewer_and_password_is_not_exposed(self):
        user = auth.create_user("Owner@Example.com", "StrongPass123", "Workspace Owner")
        self.assertEqual(user["email"], "owner@example.com")
        self.assertEqual(user["role"], "viewer")
        self.assertNotIn("password", user)
        self.assertNotIn("password_hash", user)
        with sqlite3.connect(auth.DB_PATH) as connection:
            stored = connection.execute("SELECT password_hash FROM users").fetchone()[0]
        self.assertNotEqual(stored, "StrongPass123")
        self.assertTrue(auth.verify_password("StrongPass123", stored))

    def test_later_accounts_are_viewers(self):
        auth.create_user("owner@example.com", "StrongPass123", "Owner")
        user = auth.create_user("analyst@example.com", "AnalystPass123", "Research Analyst")
        self.assertEqual(user["role"], "viewer")
        self.assertTrue(all("password_hash" not in item for item in auth.list_users()))

    def test_login_records_activity_and_uses_generic_failure(self):
        auth.create_user("owner@example.com", "StrongPass123", "Owner")
        with self.assertRaises(auth.AuthError) as caught:
            auth.authenticate("owner@example.com", "WrongPass123")
        self.assertEqual(caught.exception.code, "invalid_credentials")
        user = auth.authenticate("owner@example.com", "StrongPass123")
        self.assertEqual(user["login_count"], 1)
        self.assertIsNotNone(user["last_login_at"])
        events = auth.recent_login_events()
        self.assertEqual(events[0]["event"], "login_succeeded")

    def test_duplicate_email_is_rejected_case_insensitively(self):
        auth.create_user("owner@example.com", "StrongPass123", "Owner")
        with self.assertRaises(auth.AuthError) as caught:
            auth.create_user("OWNER@example.com", "AnotherPass123", "Other Owner")
        self.assertEqual(caught.exception.code, "email_exists")

    def test_password_policy(self):
        with self.assertRaises(auth.AuthError) as caught:
            auth.create_user("owner@example.com", "short", "Owner")
        self.assertEqual(caught.exception.code, "weak_password")

    def test_five_failures_temporarily_lock_account(self):
        auth.create_user("owner@example.com", "StrongPass123", "Owner")
        for _ in range(auth.MAX_FAILED_ATTEMPTS):
            with self.assertRaises(auth.AuthError):
                auth.authenticate("owner@example.com", "WrongPass123")
        with self.assertRaises(auth.AuthError) as caught:
            auth.authenticate("owner@example.com", "StrongPass123")
        self.assertEqual(caught.exception.code, "locked")

    def test_session_can_be_revoked(self):
        user = auth.create_user("viewer@example.com", "StrongPass123", "Viewer")
        token = auth.start_session(user["id"], address="192.0.2.1", user_agent="Test browser")
        current, active = auth.validate_session(user["id"], token)
        self.assertEqual(current["email"], "viewer@example.com")
        self.assertEqual(active["user_agent"], "Test browser")
        self.assertTrue(auth.revoke_session(active["id"], user_id=user["id"]))
        self.assertEqual(auth.validate_session(user["id"], token), (None, None))

    def test_unknown_email_is_not_stored_in_clear_text(self):
        with self.assertRaises(auth.AuthError):
            auth.authenticate("private-person@example.com", "WrongPass123", address="192.0.2.10")
        event = auth.recent_login_events()[0]
        self.assertTrue(event["email"].startswith("unrecognized:"))
        self.assertNotIn("private-person", event["email"])
        self.assertNotEqual(event["network_hash"], "192.0.2.10")

    def test_admin_controls_are_audited_and_last_admin_is_protected(self):
        admin = auth.create_user("owner@example.com", "StrongPass123", "Owner", role="admin")
        analyst = auth.create_user("analyst@example.com", "AnalystPass123", "Analyst")
        updated = auth.set_role(analyst["id"], "editor", actor_id=admin["id"])
        self.assertEqual(updated["role"], "editor")
        self.assertEqual(auth.recent_admin_audit()[0]["action"], "role_changed")
        with self.assertRaises(auth.AuthError) as caught:
            auth.set_active(admin["id"], False, actor_id=admin["id"])
        self.assertEqual(caught.exception.code, "self_protected")


if __name__ == "__main__":
    unittest.main()
