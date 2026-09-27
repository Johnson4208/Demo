import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app as app_module
from engine.valuation import infer_dividend_schedule, value_company


MARKET = {
    "success": True,
    "ticker": "TEST.VN",
    "price": 80.0,
    "currency": "VND",
    "updated_at": "2026-09-09T00:00:00+00:00",
    "source": "Deterministic test data",
    "shares_outstanding": 10.0,
    "free_cash_flow": 100.0,
    "eps": 8.0,
    "book_value_per_share": 50.0,
    "dividend_rate": 4.0,
    "dividend_yield_pct": 5.0,
    "payout_ratio_pct": 50.0,
    "earnings_growth_pct": 8.0,
    "dividend_history": [
        {"date": "2025-10-01", "amount": 1.0},
        {"date": "2026-01-02", "amount": 1.0},
        {"date": "2026-04-02", "amount": 1.0},
        {"date": "2026-07-02", "amount": 1.0},
    ],
}


class ValuationEngineTests(unittest.TestCase):
    @patch("engine.valuation.latest", return_value=None)
    @patch("engine.valuation.growth", return_value=7.0)
    def test_all_five_methods_return_specific_per_share_values(self, _growth, _latest):
        result = value_company("TEST", market_data=MARKET)
        methods = {row["name"]: row for row in result["methods"]}
        self.assertEqual(result["summary"]["method_coverage"], 5)
        self.assertEqual(methods["P/E earnings value"]["value_per_share"], 96.0)
        self.assertEqual(methods["Gordon growth value"]["value_per_share"], 52.0)
        self.assertEqual(methods["Asset-based reference"]["value_per_share"], 50.0)
        self.assertGreater(methods["Equity DCF"]["value_per_share"], 0)
        self.assertGreater(result["summary"]["fair_value"], 0)
        self.assertTrue(result["summary"]["comments"])
        self.assertIsNotNone(result["summary"]["method_dispersion_pct"])
        self.assertEqual([row["label"] for row in result["scenarios"]], ["Bear", "Base", "Bull"])
        self.assertLess(result["scenarios"][0]["fair_value"], result["scenarios"][1]["fair_value"])
        self.assertLess(result["scenarios"][1]["fair_value"], result["scenarios"][2]["fair_value"])
        self.assertAlmostEqual(result["scenarios"][1]["fair_value"], result["summary"]["fair_value"], places=1)
        self.assertEqual(result["sensitivity"]["status"], "available")
        self.assertEqual(len(result["sensitivity"]["rows"]), 3)
        self.assertIn(result["data_quality"]["label"], {"High", "Moderate", "Low"})
        self.assertGreaterEqual(result["data_quality"]["score"], 0)
        self.assertLessEqual(result["data_quality"]["score"], 100)
        self.assertEqual(result["source_evidence"][0]["as_of"], MARKET["updated_at"])
        self.assertIn("preferred_entry_threshold", result["investment_plan"])
        self.assertEqual(len(result["investment_plan"]["outlooks"]), 3)
        self.assertAlmostEqual(
            result["summary"]["research_entry_price"],
            result["summary"]["fair_value"] * 0.8,
            places=1,
        )

    @patch("engine.valuation.latest", return_value=None)
    @patch("engine.valuation.growth", return_value=None)
    def test_missing_inputs_are_unavailable_not_invented(self, _growth, _latest):
        result = value_company("EMPTY", market_data={"ticker": "EMPTY.VN", "currency": "VND"})
        self.assertEqual(result["summary"]["status"], "unavailable")
        self.assertEqual(result["summary"]["method_coverage"], 0)
        self.assertTrue(all(row["status"] == "unavailable" for row in result["methods"]))
        self.assertEqual(result["sensitivity"]["status"], "unavailable")
        self.assertEqual(result["data_quality"]["label"], "Low")

    @patch("engine.valuation.latest", return_value=None)
    @patch("engine.valuation.growth", return_value=None)
    def test_manual_inputs_are_labelled_and_restore_calculations_during_outage(self, _growth, _latest):
        result = value_company(
            "TEST",
            market_data={"ticker": "TEST.VN", "currency": "VND", "source": "Unavailable provider"},
            manual_inputs={
                "price": 80,
                "shares_outstanding": 10,
                "free_cash_flow": 100,
                "eps": 8,
                "dividend_rate": 4,
                "book_value_per_share": 50,
                "currency": "VND",
            },
        )
        self.assertEqual(result["summary"]["method_coverage"], 5)
        self.assertIn("price", result["market"]["manual_fields"])
        self.assertIn("User-provided override", result["market"]["source"])
        self.assertTrue(any(
            "User-provided override" in row.get("source", "")
            for method in result["methods"] for row in method["inputs"]
        ))

    @patch("engine.valuation.latest", return_value=None)
    @patch("engine.valuation.growth", return_value=None)
    def test_assumptions_are_bounded_and_terminal_growth_stays_below_return(self, _growth, _latest):
        result = value_company(
            "TEST",
            assumptions={
                "required_return_pct": 6,
                "terminal_growth_pct": 10,
                "near_growth_pct": 99,
                "forecast_years": 99,
                "normalized_pe": 99,
                "margin_of_safety_pct": 99,
            },
            market_data=MARKET,
        )
        assumptions = result["assumptions"]
        self.assertEqual(assumptions["terminal_growth_pct"], 5.0)
        self.assertEqual(assumptions["near_growth_pct"], 30.0)
        self.assertEqual(assumptions["forecast_years"], 10)
        self.assertEqual(assumptions["normalized_pe"], 40.0)
        self.assertEqual(assumptions["margin_of_safety_pct"], 50.0)

    def test_dividend_schedule_is_explicitly_an_estimate(self):
        schedule = infer_dividend_schedule(MARKET["dividend_history"])
        self.assertEqual(schedule["cadence"], "Quarterly")
        self.assertEqual(schedule["status"], "estimated")
        self.assertIsNotNone(schedule["next_estimated_window"])
        self.assertIn("not a board-declared", schedule["note"])

    @patch("engine.valuation.series", return_value=[
        {"period_end": "2023-06-30", "value": 100.0},
        {"period_end": "2024-06-30", "value": 112.0},
        {"period_end": "2025-06-30", "value": 123.2},
        {"period_end": "2026-06-30", "value": 133.06},
    ])
    @patch("engine.valuation.latest", return_value=None)
    @patch("engine.valuation.growth", return_value=8.0)
    def test_long_holding_outlook_uses_fading_growth_and_user_share_count(self, _growth, _latest, _series):
        market = {
            **MARKET,
            "revenue_growth_pct": 9.0,
            "return_on_equity_pct": 18.0,
        }
        result = value_company(
            "TEST",
            market_data=market,
            holding_inputs={
                "shares_held": 1000,
                "average_cost_per_share": 70,
                "horizon_years": 7,
                "reinvest_dividends": True,
            },
        )
        outlook = result["long_holding_outlook"]
        self.assertEqual(outlook["status"], "available")
        self.assertEqual(outlook["horizon_years"], 7)
        self.assertEqual(outlook["user_inputs"]["shares_held"], 1000)
        self.assertEqual([row["key"] for row in outlook["scenarios"]], ["bear", "base", "bull"])
        self.assertEqual(len(outlook["scenarios"][1]["path"]), 7)
        self.assertGreater(
            outlook["scenarios"][1]["growth_path_pct"][0],
            outlook["scenarios"][1]["growth_path_pct"][-1],
        )
        self.assertAlmostEqual(
            outlook["weighted"]["portfolio_value"],
            outlook["weighted"]["terminal_wealth_per_starting_share"] * 1000,
            delta=10,
        )
        self.assertGreaterEqual(len(outlook["growth_model"]["evidence"]), 4)
        self.assertEqual(result["automatic_inputs"]["manual_count"], 0)
        self.assertEqual(result["automatic_inputs"]["available_count"], 7)

    @patch("engine.valuation.latest", return_value=None)
    @patch("engine.valuation.growth", return_value=None)
    @patch("engine.valuation.series", return_value=[])
    def test_holding_outlook_refuses_to_predict_without_a_market_price(self, _series, _growth, _latest):
        result = value_company(
            "EMPTY",
            market_data={"ticker": "EMPTY.VN", "currency": "VND"},
            holding_inputs={"shares_held": 500, "horizon_years": 5},
        )
        self.assertEqual(result["long_holding_outlook"]["status"], "unavailable")
        self.assertIn("market price", result["long_holding_outlook"]["reason"].lower())


class ValuationRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original_db = app_module.auth.DB_PATH
        self.original_storage = app_module.auth.STORAGE_DIR
        self.original_watchlist_db = app_module.watchlist.DB_PATH
        app_module.auth.STORAGE_DIR = Path(self.temp.name)
        app_module.auth.DB_PATH = Path(self.temp.name) / "valuation-route.sqlite3"
        app_module.watchlist.DB_PATH = app_module.auth.DB_PATH
        app_module.auth.init_auth_db()
        app_module.watchlist.init_db()
        app_module.app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
        self.client = app_module.app.test_client()
        user = app_module.auth.create_user("value@example.com", "ValuationPass123", "Valuation User")
        token = app_module.auth.start_session(user["id"], user_agent="Valuation route test")
        with self.client.session_transaction() as session:
            session["user_id"] = user["id"]
            session["auth_token"] = token
            session["csrf_token"] = "valuation-csrf"

    def tearDown(self):
        app_module.auth.DB_PATH = self.original_db
        app_module.auth.STORAGE_DIR = self.original_storage
        app_module.watchlist.DB_PATH = self.original_watchlist_db
        self.temp.cleanup()

    def test_route_requires_csrf_and_returns_no_personalized_order(self):
        fake = {"success": True, "company": "FPT", "summary": {"research_entry_price": 100}}
        with patch.object(app_module, "value_company", return_value=fake) as mocked_value:
            denied = self.client.post("/api/valuation/FPT", json={})
            self.assertEqual(denied.status_code, 400)
            response = self.client.post(
                "/api/valuation/FPT",
                json={"assumptions": {"required_return_pct": 12}, "drivers": {"eps_growth_pct": 8}, "holding": {"shares_held": 250, "horizon_years": 7}},
                headers={"X-CSRF-Token": "valuation-csrf"},
            )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["company"], "FPT")
        self.assertNotIn("password", str(payload).lower())
        self.assertEqual(mocked_value.call_args.kwargs["forward_drivers"], {"eps_growth_pct": 8})
        self.assertEqual(mocked_value.call_args.kwargs["holding_inputs"], {"shares_held": 250, "horizon_years": 7})


class ValuationUITests(unittest.TestCase):
    def test_core_value_lab_and_roomier_sidebar_are_present(self):
        root = Path(__file__).resolve().parents[1]
        template = (root / "templates" / "index.html").read_text(encoding="utf-8")
        script = (root / "static" / "app.js").read_text(encoding="utf-8")
        styles = (root / "static" / "dashboard.css").read_text(encoding="utf-8")
        quant_styles = (root / "static" / "quant.css").read_text(encoding="utf-8")
        self.assertIn('id="valuationOut"', template)
        self.assertIn('data-action="overview-valuation"', template)
        self.assertIn('id="valuationFCF"', template)
        self.assertIn("function renderValuation", script)
        self.assertIn("function renderValuationScenarios", script)
        self.assertIn("function renderValuationConfidence", script)
        self.assertIn("function renderInvestmentPlan", script)
        self.assertIn("function renderValuationSensitivity", script)
        self.assertIn("AUTOMATIC CORE VALUE", template)
        self.assertIn('id="valuationRevenueGrowth"', template)
        self.assertIn('id="valuationSharesHeld"', template)
        self.assertIn('id="valuationHoldingYears"', template)
        self.assertIn("Most users can leave this closed", template)
        self.assertIn("valuation-workspace.js", template)
        self.assertIn("function renderLongHoldingOutlook", (root / "static" / "valuation-workspace.js").read_text(encoding="utf-8"))
        self.assertIn("function renderScenarioAnalysis", script)
        self.assertIn("function renderForwardDriverModel", script)
        self.assertIn("valuation-probability-bar", quant_styles)
        self.assertIn("valuation-driver-grid", quant_styles)
        self.assertIn("valuation-scenario-grid", styles)
        self.assertIn("valuation-price-track", styles)
        self.assertIn("body .sidebar{width:272px", styles)
        self.assertIn('class="valuation-field-label">Near growth %', template)
        self.assertIn("position:sticky!important", styles)
        self.assertIn("white-space:nowrap!important", styles)
        self.assertIn("font-size:14px!important", styles)


if __name__ == "__main__":
    unittest.main()
