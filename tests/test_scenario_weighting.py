import unittest
from unittest.mock import patch

from engine.scenario_weighting import build_forward_driver_model, weight_scenarios
from engine.valuation import value_company


MARKET = {
    "ticker": "TEST.VN",
    "price": 80.0,
    "currency": "VND",
    "updated_at": "2026-09-10T00:00:00+00:00",
    "source": "Deterministic test provider",
    "shares_outstanding": 10.0,
    "free_cash_flow": 100.0,
    "eps": 8.0,
    "book_value_per_share": 50.0,
    "dividend_rate": 4.0,
}


class ForwardDriverTests(unittest.TestCase):
    def test_missing_drivers_are_not_fabricated(self):
        model = build_forward_driver_model({}, supplied={})
        self.assertEqual(model["status"], "unavailable")
        self.assertEqual(model["available_drivers"], 0)
        self.assertTrue(all(row["value"] is None for row in model["drivers"]))

    def test_positive_and_negative_drivers_tilt_opposite_directions(self):
        positive = build_forward_driver_model({}, supplied={
            "revenue_growth_pct": 20,
            "eps_growth_pct": 25,
            "margin_change_pct_points": 3,
            "net_debt_to_ebitda": 0.5,
            "return_on_equity_pct": 25,
        })
        negative = build_forward_driver_model({}, supplied={
            "revenue_growth_pct": -20,
            "eps_growth_pct": -25,
            "margin_change_pct_points": -3,
            "net_debt_to_ebitda": 6,
            "return_on_equity_pct": 0,
        })
        scenarios = [
            {"key": "bear", "label": "Bear", "fair_value": 60, "research_entry_price": 48},
            {"key": "base", "label": "Base", "fair_value": 90, "research_entry_price": 72},
            {"key": "bull", "label": "Bull", "fair_value": 130, "research_entry_price": 104},
        ]
        _, positive_analysis = weight_scenarios(scenarios, positive, price=80, data_quality_score=90)
        _, negative_analysis = weight_scenarios(scenarios, negative, price=80, data_quality_score=90)
        self.assertGreater(positive_analysis["research_weights"]["bull"], positive_analysis["research_weights"]["bear"])
        self.assertGreater(negative_analysis["research_weights"]["bear"], negative_analysis["research_weights"]["bull"])

    @patch("engine.valuation.latest", return_value=None)
    @patch("engine.valuation.growth", return_value=None)
    def test_value_company_returns_weighted_value_and_traceable_drivers(self, _growth, _latest):
        result = value_company(
            "TEST",
            market_data=MARKET,
            forward_drivers={
                "revenue_growth_pct": 10,
                "eps_growth_pct": 12,
                "margin_change_pct_points": 1,
                "net_debt_to_ebitda": 1.5,
            },
        )
        weights = [row["research_weight_pct"] for row in result["scenarios"]]
        expected = sum(
            row["fair_value"] * row["research_weight_pct"]
            for row in result["scenarios"]
        ) / 100.0
        self.assertAlmostEqual(sum(weights), 100.0, places=1)
        self.assertTrue(all("probability_pct" not in row for row in result["scenarios"]))
        self.assertAlmostEqual(result["scenario_analysis"]["weighted_fair_value"], expected, places=1)
        self.assertEqual(result["forward_driver_model"]["available_drivers"], 4)
        self.assertTrue(any(
            row["origin"] == "manual" and "not independently verified" in row["source"]
            for row in result["forward_driver_model"]["drivers"]
        ))
        self.assertEqual(len(result["forward_driver_model"]["manual_fields"]), 4)
        self.assertIn("heuristic", result["scenario_analysis"]["warning"])


if __name__ == "__main__":
    unittest.main()
