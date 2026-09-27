import io
import hashlib
import json
import os
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from werkzeug.datastructures import FileStorage

from engine import auth
from engine.web_security import SlidingWindowLimiter, safe_path_segment, safe_uploaded_name
from manage_backups import create_backup, restore_backup, verify_backup


ROOT = Path(__file__).resolve().parents[1]


class ProductionConfigurationTests(unittest.TestCase):
    def test_container_uses_gunicorn_and_dynamic_port(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        lock = (ROOT / "requirements.lock").read_text(encoding="utf-8")
        self.assertIn("gunicorn==26.2.0", requirements)
        self.assertIn("exec gunicorn", dockerfile)
        self.assertIn("--no-control-socket", dockerfile)
        self.assertIn("${PORT:-${SOLVAI_PORT:-5000}}", dockerfile)
        self.assertIn("--require-hashes -r requirements.lock", dockerfile)
        self.assertIn("--hash=sha256:", lock)
        self.assertIn("/api/ready", dockerfile)

    def test_render_blueprint_keeps_closed_single_instance_with_disk(self):
        blueprint = (ROOT / "render.yaml").read_text(encoding="utf-8")
        self.assertIn("region: singapore", blueprint)
        self.assertIn("numInstances: 1", blueprint)
        self.assertIn("mountPath: /data", blueprint)
        self.assertIn("healthCheckPath: /api/ready", blueprint)
        self.assertRegex(blueprint, r"SOLVAI_ALLOW_REGISTRATION\s*\n\s*value: [\"']?0")
        self.assertRegex(blueprint, r"SOLVAI_SECURE_COOKIES\s*\n\s*value: [\"']?1")

    def test_production_requires_explicit_session_secret(self):
        with patch.dict(os.environ, {"SOLVAI_ENV": "production", "SOLVAI_SECRET_KEY": ""}, clear=False):
            with self.assertRaisesRegex(RuntimeError, "SOLVAI_SECRET_KEY is required"):
                auth.session_secret()

    def test_upload_names_and_segments_reject_path_traversal(self):
        with self.assertRaises(ValueError):
            safe_path_segment("../../private", "Company")
        with self.assertRaises(ValueError):
            safe_path_segment("Technology/../../", "Industry")
        upload = FileStorage(stream=io.BytesIO(b"test"), filename="../../report.exe")
        with self.assertRaises(ValueError):
            safe_uploaded_name(upload, {".pdf"}, "report")
        valid = FileStorage(stream=io.BytesIO(b"test"), filename="../FPT Q2 2026.pdf")
        self.assertEqual(safe_uploaded_name(valid, {".pdf"}, "report"), "FPT_Q2_2026.pdf")

    def test_auth_request_window_is_bounded(self):
        limiter = SlidingWindowLimiter()
        for index in range(5):
            self.assertFalse(limiter.exceeded("login", "test-client", 5, 300, now=index))
        self.assertTrue(limiter.exceeded("login", "test-client", 5, 300, now=6))
        self.assertFalse(limiter.exceeded("login", "test-client", 5, 300, now=301))


class BackupTests(unittest.TestCase):
    def test_backup_is_consistent_and_includes_reports(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            database = root / "financial_ai.sqlite3"
            reports = root / "reports"
            output = root / "backups"
            report = reports / "Technology" / "FPT" / "report.txt"
            report.parent.mkdir(parents=True)
            report.write_text("verified report", encoding="utf-8")
            with sqlite3.connect(database) as connection:
                connection.execute("CREATE TABLE users(id INTEGER PRIMARY KEY, email TEXT)")
                connection.execute("INSERT INTO users(email) VALUES(?)", ("private@example.invalid",))

            archive = create_backup(database, reports, output, include_reports=True)
            manifest = verify_backup(archive)
            self.assertEqual(manifest["format"], "solvai-backup-v2")
            self.assertEqual(manifest["report_file_count"], 1)
            with zipfile.ZipFile(archive) as backup_zip:
                self.assertIn("storage/financial_ai.sqlite3", backup_zip.namelist())
                self.assertIn("reports/Companies_reports/Technology/FPT/report.txt", backup_zip.namelist())
                stored_manifest = json.loads(backup_zip.read("backup-manifest.json"))
            self.assertEqual(stored_manifest["database_sha256"], manifest["database_sha256"])
            self.assertEqual(len(stored_manifest["files"]), 2)

    def test_restore_stages_a_verified_copy_without_overwriting(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            database = root / "financial_ai.sqlite3"
            reports = root / "reports"
            reports.mkdir()
            with sqlite3.connect(database) as connection:
                connection.execute("CREATE TABLE marker(value TEXT)")
                connection.execute("INSERT INTO marker(value) VALUES('phase-2')")
            archive = create_backup(database, reports, root / "backups", include_reports=False)
            target = root / "restore-preview"

            restored = restore_backup(archive, target)
            with sqlite3.connect(restored / "storage" / "financial_ai.sqlite3") as connection:
                self.assertEqual(connection.execute("SELECT value FROM marker").fetchone()[0], "phase-2")
            with self.assertRaises(FileExistsError):
                restore_backup(archive, target)

    def test_backup_verification_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            database = root / "financial_ai.sqlite3"
            with sqlite3.connect(database) as connection:
                connection.execute("CREATE TABLE marker(value TEXT)")
            archive = create_backup(database, root / "reports", root / "backups", include_reports=False)
            with zipfile.ZipFile(archive, "a") as backup_zip:
                backup_zip.writestr("../outside.txt", "unsafe")
            with self.assertRaisesRegex(RuntimeError, "unsafe archive member"):
                verify_backup(archive)

    def test_phase1_backup_can_be_verified_and_staged_for_upgrade(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            database = root / "financial_ai.sqlite3"
            with sqlite3.connect(database) as connection:
                connection.execute("CREATE TABLE marker(value TEXT)")
                connection.execute("INSERT INTO marker(value) VALUES('phase-1')")
            archive = root / "phase1-backup.zip"
            manifest = {
                "format": "solvai-backup-v1",
                "database": "storage/financial_ai.sqlite3",
                "database_sha256": hashlib.sha256(database.read_bytes()).hexdigest(),
                "report_file_count": 0,
            }
            with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as backup_zip:
                backup_zip.write(database, "storage/financial_ai.sqlite3")
                backup_zip.writestr("backup-manifest.json", json.dumps(manifest))

            verified = verify_backup(archive)
            self.assertEqual(verified["verification_level"], "legacy_database_only")
            restored = restore_backup(archive, root / "phase1-restore-preview")
            self.assertTrue((restored / "storage" / "financial_ai.sqlite3").is_file())


if __name__ == "__main__":
    unittest.main()
