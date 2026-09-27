import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from engine.event_probability import db


class ForecastLabTests(TestCase):
    SCOPE = {"owner_user_id": 7, "workspace_id": "test-workspace"}

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "forecast_lab.sqlite3"
        self.patches = (
            patch.object(db, "DB_PATH", self.db_path),
            patch.object(db, "STORAGE_DIR", Path(self.temp.name)),
            patch.object(db, "_is_postgres", return_value=False),
        )
        for item in self.patches:
            item.start()
        db.init_db()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def sample_result(self):
        return {
            "factor": "gdp",
            "focus": "Vietnam",
            "ranked": [
                {"candidate": "Growth improves", "normalized_probability": 50.0},
                {"candidate": "Growth stays mixed", "normalized_probability": 30.0},
                {"candidate": "Growth weakens", "normalized_probability": 20.0},
            ],
        }

    def test_saved_notes_and_resolution_persist(self):
        forecast_id = db.save_forecast("Growth outlook", "30 days", "economy", self.sample_result(), [], **self.SCOPE)
        review = db.update_review(forecast_id, {"saved": True, "note": "Review after GDP release", "resolved_outcome": "Growth improves"}, **self.SCOPE)
        self.assertTrue(review["saved"])
        self.assertEqual(db.recent_forecasts(10, saved_only=True, **self.SCOPE)[0]["review"]["note"], "Review after GDP release")
        calibration = db.calibration_summary(**self.SCOPE)
        self.assertEqual(calibration["resolved_forecasts"], 1)
        self.assertEqual(calibration["top_outcome_accuracy_pct"], 100.0)

    def test_resolution_must_match_a_forecast_scenario(self):
        forecast_id = db.save_forecast("Growth outlook", "30 days", "economy", self.sample_result(), [], **self.SCOPE)
        with self.assertRaises(ValueError):
            db.update_review(forecast_id, {"resolved_outcome": "Invented outcome"}, **self.SCOPE)

    def test_forecasts_and_reviews_are_private_to_the_owner(self):
        forecast_id = db.save_forecast("Private outlook", "30 days", "economy", self.sample_result(), [], **self.SCOPE)
        other_scope = {"owner_user_id": 8, "workspace_id": "test-workspace"}

        self.assertIsNone(db.get_forecast(forecast_id, **other_scope))
        self.assertIsNone(db.update_review(forecast_id, {"saved": True}, **other_scope))
        self.assertEqual(db.recent_forecasts(10, **other_scope), [])
        self.assertEqual(len(db.recent_forecasts(10, **self.SCOPE)), 1)

    def test_workspace_boundary_is_enforced_for_same_user(self):
        forecast_id = db.save_forecast("Workspace outlook", "30 days", "economy", self.sample_result(), [], **self.SCOPE)
        wrong_workspace = {"owner_user_id": self.SCOPE["owner_user_id"], "workspace_id": "another-workspace"}

        self.assertIsNone(db.get_forecast(forecast_id, **wrong_workspace))
        self.assertEqual(db.calibration_summary(**wrong_workspace)["resolved_forecasts"], 0)

    def test_unowned_legacy_forecasts_are_not_exposed(self):
        with db._conn() as connection:
            connection.execute(
                "INSERT INTO forecasts(created_at,query,horizon,category,result_json) VALUES(?,?,?,?,?)",
                ("2026-01-01T00:00:00+00:00", "Legacy shared forecast", "30 days", "economy", "{}"),
            )
        self.assertEqual(db.recent_forecasts(10, **self.SCOPE), [])


if __name__ == "__main__":
    import unittest

    unittest.main()
