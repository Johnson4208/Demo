import unittest
from pathlib import Path

from engine.position_sizing import ACTIVE_METHODS, REFERENCE_METHODS, calculate_position_size
from engine.scenario_weighting import weight_scenarios


ROOT = Path(__file__).resolve().parents[1]


class FoundationV45Tests(unittest.TestCase):
    def test_single_company_and_portfolio_methods_have_distinct_ownership(self):
        self.assertEqual(ACTIVE_METHODS, {"fixed-fractional", "kelly", "half-kelly"})
        self.assertEqual(REFERENCE_METHODS, {"volatility-targeting", "risk-parity", "r-multiple"})

    def test_method_change_changes_the_canonical_allocation(self):
        common = dict(
            account_equity=100_000, entry_price=100, stop_price=90,
            requested_risk_pct=1, target_r_multiple=2,
            win_probability=0.55, resolved_paths=100,
        )
        results = {key: calculate_position_size(key, **common)["allocation_pct"] for key in ACTIVE_METHODS}
        self.assertEqual(results["fixed-fractional"], 10.0)
        self.assertEqual(results["kelly"], 25.0)
        self.assertEqual(results["half-kelly"], 12.5)

    def test_valuation_scenarios_expose_weights_not_probability_aliases(self):
        scenarios = [
            {"key": "bear", "label": "Bear", "fair_value": 70, "research_entry_price": 56},
            {"key": "base", "label": "Base", "fair_value": 100, "research_entry_price": 80},
            {"key": "bull", "label": "Bull", "fair_value": 140, "research_entry_price": 112},
        ]
        weighted, analysis = weight_scenarios(scenarios, {"coverage_pct": 0, "raw_tilt": 0}, price=90)
        self.assertEqual(sum(row["research_weight_pct"] for row in weighted), 100)
        self.assertTrue(all("probability_pct" not in row for row in weighted))
        self.assertNotIn("probabilities", analysis)
        self.assertFalse(analysis["semantic_contract"]["calibrated_probability"])

    def test_frontend_separates_research_and_trade_controllers(self):
        template = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        app = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        sizing = (ROOT / "static" / "position-sizing-workspace.js").read_text(encoding="utf-8")
        self.assertEqual(template.count('id="risk"'), 1)
        self.assertEqual(template.count('id="tradePlanner"'), 1)
        self.assertIn("SolvAIControllers.tradePlanner", sizing)
        self.assertIn("runFeatureController('tradePlanner'", app)

    def test_dashboard_and_login_background_remain_present(self):
        template = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        auth_css = (ROOT / "static" / "auth.css").read_text(encoding="utf-8")
        self.assertIn('id="dashboardMacroMount"', template)
        self.assertIn("/static/auth-background.jpg", auth_css)
        self.assertTrue((ROOT / "static" / "auth-background.jpg").is_file())


if __name__ == "__main__":
    unittest.main()
