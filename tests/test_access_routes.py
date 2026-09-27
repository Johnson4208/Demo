import io
import tempfile
import unittest
from pathlib import Path

import app as app_module


class AccessRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original_db = app_module.auth.DB_PATH
        self.original_storage = app_module.auth.STORAGE_DIR
        app_module.auth.STORAGE_DIR = Path(self.temp.name)
        app_module.auth.DB_PATH = Path(self.temp.name) / "access-routes.sqlite3"
        app_module.auth.init_auth_db()
        app_module.app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
        self.client = app_module.app.test_client()
        self.admin = app_module.auth.create_user(
            "admin@example.com", "Administrator123", "Administrator", role="admin"
        )
        self.viewer = app_module.auth.create_user(
            "viewer@example.com", "ViewerPassword123", "Research Viewer"
        )

    def tearDown(self):
        app_module.auth.DB_PATH = self.original_db
        app_module.auth.STORAGE_DIR = self.original_storage
        self.temp.cleanup()

    def sign_in_as(self, user):
        token = app_module.auth.start_session(user["id"], user_agent="Route test")
        with self.client.session_transaction() as session:
            session.clear()
            session["user_id"] = user["id"]
            session["auth_token"] = token
            session["csrf_token"] = "route-test-csrf"

    def test_access_center_is_admin_only(self):
        self.sign_in_as(self.viewer)
        self.assertEqual(self.client.get("/admin/users").status_code, 403)
        self.sign_in_as(self.admin)
        response = self.client.get("/admin/users")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Access center", response.data)

    def test_admin_can_create_least_privilege_account(self):
        self.sign_in_as(self.admin)
        response = self.client.post(
            "/api/admin/users",
            json={
                "display_name": "New Analyst", "email": "new@example.com",
                "password": "TemporaryPass123", "role": "editor",
            },
            headers={"X-CSRF-Token": "route-test-csrf"},
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json()["user"]["role"], "editor")
        self.assertNotIn("password", response.get_json()["user"])

    def test_viewer_cannot_scan_or_upload(self):
        self.sign_in_as(self.viewer)
        headers = {"X-CSRF-Token": "route-test-csrf"}
        self.assertEqual(self.client.post("/api/scan", headers=headers).status_code, 403)
        response = self.client.post(
            "/api/upload",
            data={"industry": "Technology", "company": "FPT", "file": (io.BytesIO(b"%PDF-1.4"), "report.pdf")},
            headers=headers,
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 403)

    def test_editor_scan_is_queued_without_blocking_request(self):
        editor = app_module.auth.set_role(self.viewer["id"], "editor", actor_id=self.admin["id"])
        self.sign_in_as(editor)
        original_submit = app_module.jobs.submit
        app_module.jobs.submit = lambda *args, **kwargs: {"id": "job-1", "status": "queued"}
        try:
            response = self.client.post("/api/scan", headers={"X-CSRF-Token": "route-test-csrf"})
        finally:
            app_module.jobs.submit = original_submit
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.get_json()["job"]["status"], "queued")

    def test_spoofed_report_is_rejected_before_saving(self):
        self.sign_in_as(self.admin)
        response = self.client.post(
            "/api/upload",
            data={"industry": "Technology", "company": "FPT", "file": (io.BytesIO(b"not a pdf"), "report.pdf")},
            headers={"X-CSRF-Token": "route-test-csrf"},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("valid PDF signature", response.get_json()["error"])

    def test_password_change_rotates_session(self):
        self.sign_in_as(self.viewer)
        with self.client.session_transaction() as before:
            old_token = before["auth_token"]
        response = self.client.post(
            "/api/auth/password",
            json={"current_password": "ViewerPassword123", "new_password": "NewViewerPassword456"},
            headers={"X-CSRF-Token": "route-test-csrf"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(app_module.auth.validate_session(self.viewer["id"], old_token), (None, None))
        with self.client.session_transaction() as after:
            self.assertNotEqual(after["auth_token"], old_token)


if __name__ == "__main__":
    unittest.main()
