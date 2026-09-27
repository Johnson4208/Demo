import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock, patch

from engine.event_probability import sources


class EventProbabilitySourceTests(TestCase):
    def test_source_text_decodes_nested_entities_and_strips_markup(self):
        value = "Vietnam&amp;nbsp;&amp;nbsp;<b>consumer</b> outlook"
        self.assertEqual(sources._clean_text(value), "Vietnam consumer outlook")

    def test_source_date_is_normalized_to_utc(self):
        self.assertEqual(
            sources._safe_date("2026-07-17T07:00:00+00:00"),
            "2026-07-17T07:00:00+00:00",
        )

    def test_gdelt_rate_limit_returns_friendly_issue_without_url(self):
        response = Mock(status_code=429, headers={"Retry-After": "120"})
        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch.object(sources, "CACHE_DIR", Path(temp_dir)),
                patch.object(sources, "GDELT_COOLDOWN_PATH", Path(temp_dir) / "cooldown.json"),
                patch.object(sources, "_source_success_get", return_value=[]),
                patch.object(sources.requests, "get", return_value=response),
            ):
                items, issues = sources.gdelt("Vietnam retail outlook")

        self.assertEqual(items, [])
        self.assertEqual(issues[0]["code"], "rate_limited")
        self.assertEqual(issues[0]["retry_after_seconds"], 120)
        self.assertNotIn("http", issues[0]["message"].lower())

    def test_gdelt_rate_limit_uses_lower_weight_cached_success(self):
        stale = [{
            "source": "GDELT",
            "title": "Recent demand update",
            "url": "https://example.test/article",
            "snippet": "Demand remained resilient.",
            "published_at": "2026-07-17T07:00:00+00:00",
            "reliability": 0.64,
            "meta": {},
        }]
        response = Mock(status_code=429, headers={"Retry-After": "90"})
        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch.object(sources, "CACHE_DIR", Path(temp_dir)),
                patch.object(sources, "GDELT_COOLDOWN_PATH", Path(temp_dir) / "cooldown.json"),
                patch.object(sources, "_source_success_get", return_value=stale),
                patch.object(sources.requests, "get", return_value=response),
            ):
                items, issues = sources.gdelt("Vietnam retail outlook")

        self.assertTrue(items[0]["meta"]["stale_fallback"])
        self.assertLess(items[0]["reliability"], stale[0]["reliability"])
        self.assertTrue(issues[0]["fallback_used"])

    def test_generic_provider_failure_is_safe_for_the_interface(self):
        exc = RuntimeError("request failed for https://secret.example/raw?token=value")
        issue = sources._friendly_exception("Research source", exc)
        self.assertEqual(issue["code"], "connection_issue")
        self.assertNotIn("http", issue["message"].lower())

    def test_repeated_headlines_are_grouped_and_domains_are_balanced(self):
        items = [
            sources._item("GDELT", "Vietnam retail demand strengthens in 2026", "https://one.example/a", "", reliability=0.64),
            sources._item("Google News RSS", "Vietnam retail demand strengthens in 2026", "https://two.example/b", "", reliability=0.68),
            sources._item("GDELT", "Independent consumer confidence update", "https://one.example/c", "", reliability=0.64),
        ]
        grouped = sources._dedupe_balanced(items)
        self.assertEqual(len(grouped), 2)
        self.assertEqual(sum(row["meta"]["duplicate_count"] for row in grouped), 3)


if __name__ == "__main__":
    import unittest

    unittest.main()
