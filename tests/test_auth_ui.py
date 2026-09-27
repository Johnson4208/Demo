import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class AuthenticationUITests(unittest.TestCase):
    def test_hidden_auth_form_overrides_grid_layout(self):
        css = (ROOT / "static" / "auth.css").read_text(encoding="utf-8").replace(" ", "")
        self.assertIn(".auth-form[hidden]{display:none!important}", css)

    def test_first_account_initially_selects_only_registration(self):
        template = (ROOT / "templates" / "auth.html").read_text(encoding="utf-8")
        self.assertIn("first_account and registration_enabled", template)
        self.assertIn('data-auth-form="login" {% if first_account and registration_enabled %}hidden{% endif %}', template)
        self.assertIn('data-auth-form="register" {% if not first_account %}hidden{% endif %}', template)

    def test_auth_assets_use_application_cache_version(self):
        template = (ROOT / "templates" / "auth.html").read_text(encoding="utf-8")
        self.assertIn("auth.css?v={{ app_version }}", template)
        self.assertIn("account-workspace.css?v={{ app_version }}", template)
        self.assertIn("auth.js?v={{ app_version }}", template)

    def test_pending_registration_uses_the_shared_status_handler(self):
        javascript = (ROOT / "static" / "auth.js").read_text(encoding="utf-8")
        self.assertIn("setStatus(data.message||'Access request submitted", javascript)
        self.assertNotIn("showStatus(data.message||'Access request submitted", javascript)

    def test_login_story_keeps_its_original_background_image(self):
        template = (ROOT / "templates" / "auth.html").read_text(encoding="utf-8")
        css = (ROOT / "static" / "account-workspace.css").read_text(encoding="utf-8")
        self.assertIn('class="auth-story-shade"', template)
        self.assertIn("url('/static/auth-background.jpg')", css)
        self.assertTrue((ROOT / "static" / "auth-background.jpg").is_file())


if __name__ == "__main__":
    unittest.main()
