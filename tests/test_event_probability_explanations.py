from datetime import datetime, timezone
from unittest import TestCase
from unittest.mock import patch

from engine.event_probability.catalog import CATALOG
from engine.event_probability import service


class EventProbabilityExplanationTests(TestCase):
    def setUp(self):
        now = datetime.now(timezone.utc).isoformat()
        self.items = [
            {
                "source": "Official release",
                "title": "Growth improves as demand strengthens",
                "snippet": "Recent data confirmed resilient expansion and supportive investment.",
                "published_at": now,
                "reliability": 0.95,
                "url": "https://official.example/growth",
            },
            {
                "source": "Market research",
                "title": "New orders accelerate",
                "snippet": "Activity is on track and the outlook improves.",
                "published_at": now,
                "reliability": 0.82,
                "url": "https://research.example/orders",
            },
            {
                "source": "Newswire",
                "title": "Risks remain but decline",
                "snippet": "Some concern remains and momentum may slow.",
                "published_at": now,
                "reliability": 0.72,
                "url": "https://news.example/risk",
            },
        ]

    def analyze(self, items):
        with (
            patch.object(service, "search_all", return_value=(items, [], False)),
            patch.object(service.db, "init_db"),
            patch.object(service.db, "save_forecast", return_value=42),
            patch.object(service.db, "latest_comparable", return_value=None),
        ):
            return service.analyze_factor(
                "economy", "gdp", "Vietnam", "30 days",
                owner_user_id=1, workspace_id="test-workspace",
            )

    def test_every_three_way_catalog_has_distinct_directional_tones(self):
        for category, category_spec in CATALOG.items():
            for factor, factor_spec in category_spec["factors"].items():
                with self.subTest(category=category, factor=factor):
                    self.assertEqual(
                        sorted(service._resolved_tones(factor_spec["outcomes"])),
                        ["negative", "neutral", "positive"],
                    )

    def test_directional_language_distinguishes_appetite_from_risk_pressure(self):
        appetite = {"title": "Risk appetite strengthens", "snippet": "Investor demand accelerates."}
        pressure = {"title": "Risk pressure rises", "snippet": "Uncertainty increases."}
        easing = {"title": "Currency pressure eases", "snippet": "Conditions improve."}
        self.assertGreater(service._sentiment(appetite), 0)
        self.assertLess(service._sentiment(pressure), 0)
        self.assertGreater(service._sentiment(easing), 0)

    def test_distribution_sums_to_exactly_one_hundred(self):
        result = self.analyze(self.items)
        probabilities = [outcome["normalized_probability"] for outcome in result["ranked"]]
        self.assertEqual(sum(probabilities), 100.0)
        self.assertEqual(result["probability_model"]["total_pct"], 100.0)

    def test_each_outcome_explains_support_mixed_and_counter_evidence(self):
        result = self.analyze(self.items)
        for outcome in result["ranked"]:
            with self.subTest(outcome=outcome["candidate"]):
                self.assertIn("equal-outcome starting point", outcome["why"])
                self.assertEqual(
                    set(outcome["analysis"]["counts"]),
                    {"support", "mixed", "counter"},
                )
                self.assertIn("weighted_evidence_pct", outcome["analysis"])
                self.assertIsInstance(outcome["analysis"]["drivers"], list)
                self.assertIsInstance(outcome["analysis"]["counter_signals"], list)

    def test_no_evidence_returns_a_balanced_not_invented_distribution(self):
        result = self.analyze([])
        probabilities = sorted(outcome["normalized_probability"] for outcome in result["ranked"])
        self.assertEqual(probabilities, [33.3, 33.3, 33.4])
        self.assertTrue(all(outcome["evidence_count"] == 0 for outcome in result["ranked"]))

    def test_mixed_evidence_promotes_the_mixed_scenario(self):
        now = datetime.now(timezone.utc).isoformat()
        items = [
            {
                "source": "Official data",
                "title": "Quarterly GDP data update",
                "snippet": "The statistical release reports current output and demand levels.",
                "published_at": now,
                "reliability": 0.95,
                "url": "https://official.example/update",
            }
        ]
        result = self.analyze(items)
        self.assertEqual(result["ranked"][0]["tone"], "neutral")

    def test_negative_evidence_promotes_the_weakening_scenario(self):
        now = datetime.now(timezone.utc).isoformat()
        items = [
            {
                "source": "Official data",
                "title": "Growth weakens as new orders decline",
                "snippet": "Demand slows and contraction risk increases.",
                "published_at": now,
                "reliability": 0.95,
                "url": "https://official.example/slowdown",
            }
        ]
        result = self.analyze(items)
        self.assertEqual(result["ranked"][0]["tone"], "negative")

    def test_forecast_lab_metadata_is_returned(self):
        result = self.analyze(self.items)
        self.assertEqual(len(result["monitor_signals"]), 4)
        self.assertIn("quality", result["research"])
        self.assertIn("sensitivity_range", result["ranked"][0])
        self.assertFalse(result["comparison"]["available"])


if __name__ == "__main__":
    import unittest

    unittest.main()
