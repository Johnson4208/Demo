import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from engine import system_health


class SystemHealthTests(TestCase):
    def test_provider_state_is_recorded_without_breaking_unknown_sources(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "health.json"
            with patch.object(system_health, "HEALTH_PATH", path):
                system_health.record_provider("GDELT", "degraded", message="Cached evidence is active.", latency_ms=125, cached=True, evidence_count=4)
                snapshot = system_health.provider_snapshot({"companies": 2, "reports": 5})
        gdelt = next(row for row in snapshot["providers"] if row["name"] == "GDELT")
        self.assertEqual(gdelt["status"], "degraded")
        self.assertTrue(gdelt["cached"])
        self.assertEqual(gdelt["evidence_count"], 4)
        self.assertGreater(snapshot["score"], 0)


if __name__ == "__main__":
    import unittest

    unittest.main()
