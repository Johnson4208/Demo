import sqlite3
import tempfile
import unittest
from pathlib import Path

import app as app_module
from engine import auth


class AccessApprovalDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original_db = auth.DB_PATH
        self.original_storage = auth.STORAGE_DIR
        auth.STORAGE_DIR = Path(self.temp.name)
        auth.DB_PATH = auth.STORAGE_DIR / "access-approval.sqlite3"
        auth.init_auth_db()
        self.admin = auth.create_user(
            "admin@example.com", "Administrator123", "Workspace Admin", role="admin"
        )

    def tearDown(self):
        auth.DB_PATH = self.original_db
        auth.STORAGE_DIR = self.original_storage
        self.temp.cleanup()

    def test_request_is_pending_and_password_material_is_never_returned(self):
        request = auth.create_access_request(
            "Analyst@Example.com",
            "RequesterPass123",
            "Research Analyst",
            request_note="Review company statements",
            address="192.0.2.30",
            user_agent="Approval test browser",
        )
        self.assertEqual(request["status"], "pending")
        self.assertEqual(request["email"], "analyst@example.com")
        self.assertNotIn("password", request)
        self.assertNotIn("password_hash", request)
        self.assertEqual(auth.user_count(), 1)
        listed = auth.list_access_requests(status="pending")
        self.assertEqual(len(listed), 1)
        self.assertNotIn("password_hash", listed[0])
        with sqlite3.connect(auth.DB_PATH) as connection:
            stored = connection.execute(
                "SELECT password_hash FROM access_requests WHERE id=?", (request["id"],)
            ).fetchone()[0]
        self.assertNotEqual(stored, "RequesterPass123")
        self.assertTrue(auth.verify_password("RequesterPass123", stored))

    def test_admin_approval_creates_account_and_clears_request_hash(self):
        request = auth.create_access_request(
            "analyst@example.com", "RequesterPass123", "Research Analyst"
        )
        result = auth.review_access_request(
            request["id"], "approve", role="editor", actor_id=self.admin["id"],
            decision_note="Verified research team member",
        )
        self.assertEqual(result["request"]["status"], "approved")
        self.assertEqual(result["user"]["role"], "editor")
        signed_in = auth.authenticate("analyst@example.com", "RequesterPass123")
        self.assertEqual(signed_in["id"], result["user"]["id"])
        with sqlite3.connect(auth.DB_PATH) as connection:
            stored = connection.execute(
                "SELECT password_hash FROM access_requests WHERE id=?", (request["id"],)
            ).fetchone()[0]
        self.assertEqual(stored, "")
        self.assertEqual(auth.recent_admin_audit()[0]["action"], "access_request_approved")

    def test_rejection_clears_hash_and_allows_a_new_request(self):
        request = auth.create_access_request(
            "candidate@example.com", "CandidatePass123", "Candidate"
        )
        result = auth.review_access_request(
            request["id"], "reject", actor_id=self.admin["id"], decision_note="Identity not verified"
        )
        self.assertEqual(result["request"]["status"], "rejected")
        self.assertIsNone(result["user"])
        with sqlite3.connect(auth.DB_PATH) as connection:
            stored = connection.execute(
                "SELECT password_hash FROM access_requests WHERE id=?", (request["id"],)
            ).fetchone()[0]
        self.assertEqual(stored, "")
        replacement = auth.create_access_request(
            "candidate@example.com", "DifferentPass456", "Candidate"
        )
        self.assertEqual(replacement["status"], "pending")

    def test_duplicate_pending_request_and_admin_role_approval_are_blocked(self):
        request = auth.create_access_request(
            "candidate@example.com", "CandidatePass123", "Candidate"
        )
        with self.assertRaises(auth.AuthError) as duplicate:
            auth.create_access_request("candidate@example.com", "CandidatePass123", "Candidate")
        self.assertEqual(duplicate.exception.code, "request_pending")
        with self.assertRaises(auth.AuthError) as elevated:
            auth.review_access_request(
                request["id"], "approve", role="admin", actor_id=self.admin["id"]
            )
        self.assertEqual(elevated.exception.code, "invalid_role")


class AccessApprovalRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original_db = app_module.auth.DB_PATH
        self.original_storage = app_module.auth.STORAGE_DIR
        app_module.auth.STORAGE_DIR = Path(self.temp.name)
        app_module.auth.DB_PATH = Path(self.temp.name) / "access-approval-routes.sqlite3"
        app_module.auth.init_auth_db()
        app_module.app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
        self.client = app_module.app.test_client()
        self.admin = app_module.auth.create_user(
            "admin@example.com", "Administrator123", "Workspace Admin", role="admin"
        )

    def tearDown(self):
        app_module.auth.DB_PATH = self.original_db
        app_module.auth.STORAGE_DIR = self.original_storage
        self.temp.cleanup()

    def set_public_csrf(self):
        with self.client.session_transaction() as session:
            session.clear()
            session["csrf_token"] = "approval-csrf"

    def sign_in_as_admin(self):
        token = app_module.auth.start_session(self.admin["id"], user_agent="Approval route test")
        with self.client.session_transaction() as session:
            session.clear()
            session["user_id"] = self.admin["id"]
            session["auth_token"] = token
            session["csrf_token"] = "approval-csrf"

    def test_registration_waits_for_admin_and_admin_can_approve(self):
        self.set_public_csrf()
        response = self.client.post(
            "/api/auth/register",
            json={
                "display_name": "New Researcher",
                "email": "new@example.com",
                "password": "NewResearcher123",
                "request_note": "Company statement research",
            },
            headers={"X-CSRF-Token": "approval-csrf"},
        )
        self.assertEqual(response.status_code, 202)
        payload = response.get_json()
        self.assertTrue(payload["pending_approval"])
        self.assertNotIn("password_hash", str(payload))
        with self.client.session_transaction() as session:
            self.assertNotIn("user_id", session)

        self.sign_in_as_admin()
        page = self.client.get("/admin/users")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"New Researcher", page.data)
        self.assertIn(b"Company statement research", page.data)
        request_id = app_module.auth.list_access_requests(status="pending")[0]["id"]
        approved = self.client.post(
            f"/api/admin/access-requests/{request_id}/action",
            json={"action": "approve", "role": "viewer", "decision_note": "Verified"},
            headers={"X-CSRF-Token": "approval-csrf"},
        )
        self.assertEqual(approved.status_code, 200)
        self.assertEqual(approved.get_json()["user"]["role"], "viewer")

        self.client = app_module.app.test_client()
        self.set_public_csrf()
        login = self.client.post(
            "/api/auth/login",
            json={"email": "new@example.com", "password": "NewResearcher123"},
            headers={"X-CSRF-Token": "approval-csrf"},
        )
        self.assertEqual(login.status_code, 200)

    def test_non_admin_cannot_review_requests(self):
        request = app_module.auth.create_access_request(
            "new@example.com", "NewResearcher123", "New Researcher"
        )
        viewer = app_module.auth.create_user(
            "viewer@example.com", "ViewerPassword123", "Viewer"
        )
        token = app_module.auth.start_session(viewer["id"])
        with self.client.session_transaction() as session:
            session.clear()
            session["user_id"] = viewer["id"]
            session["auth_token"] = token
            session["csrf_token"] = "approval-csrf"
        response = self.client.post(
            f"/api/admin/access-requests/{request['id']}/action",
            json={"action": "approve", "role": "viewer"},
            headers={"X-CSRF-Token": "approval-csrf"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(app_module.auth.pending_access_request_count(), 1)


if __name__ == "__main__":
    unittest.main()
