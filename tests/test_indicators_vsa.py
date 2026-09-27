import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

import app as app_module
from engine import stock
from engine.indicators_vsa import analyze_frame, screen_companies
from engine.stock import ticker_for


def market_frame(count=280, seed=11):
    rng = np.random.default_rng(seed)
    returns = 0.0007 + rng.normal(0, 0.009, count)
    close = 100 * np.exp(np.cumsum(returns))
    open_ = np.r_[close[0], close[:-1]] * (1 + rng.normal(0, 0.002, count))
    spread = close * rng.uniform(0.009, 0.024, count)
    high = np.maximum(open_, close) + spread * rng.uniform(0.35, 0.65, count)
    low = np.minimum(open_, close) - spread * rng.uniform(0.35, 0.65, count)
    volume = rng.lognormal(14.5, 0.22, count)
    return pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume},
        index=pd.date_range("2025-01-02", periods=count, freq="B"),
    )


class IndicatorVSATests(unittest.TestCase):
    def test_analysis_separates_indicators_vsa_traps_phase_and_plan(self):
        result = analyze_frame(
            market_frame(),
            company="TEST",
            ticker="TEST.VN",
            fundamental_context={
                "available": True,
                "health_score": 78,
                "coverage_pct": 86,
                "risk_flag_count": 0,
                "latest_period": "2026-06-30",
            },
        )
        self.assertEqual(result["status"], "ok")
        self.assertIn("rsi14", result["indicators"])
        self.assertIn("relative_volume", result["indicators"])
        self.assertIn("recent_events", result["vsa"])
        self.assertIn("bull_trap_risk", result["traps"])
        self.assertIn(result["wyckoff"]["key"], {
            "accumulation", "markup", "distribution", "markdown", "trading_range"
        })
        self.assertIn("conditional_entry_zone", result["plan"])
        self.assertIn("invalidation", result["plan"])
        self.assertIn("sell_rules", result["plan"])
        self.assertNotIn(result["plan"]["action"], {"BUY", "SELL"})

    def test_failed_breakout_is_flagged_as_bull_trap_risk(self):
        frame = market_frame()
        prior_high = float(frame["High"].iloc[-21:-1].max())
        prior_low = float(frame["Low"].iloc[-21:-1].min())
        normal_volume = float(frame["Volume"].iloc[-21:-1].mean())
        frame.iloc[-1, frame.columns.get_loc("Open")] = prior_high * 1.002
        frame.iloc[-1, frame.columns.get_loc("High")] = prior_high * 1.04
        frame.iloc[-1, frame.columns.get_loc("Low")] = max(prior_low, prior_high * 0.965)
        frame.iloc[-1, frame.columns.get_loc("Close")] = prior_high * 0.985
        frame.iloc[-1, frame.columns.get_loc("Volume")] = normal_volume * 2.4
        result = analyze_frame(frame, company="TRAP", ticker="TRAP.VN")
        self.assertEqual(result["status"], "ok")
        self.assertGreaterEqual(result["traps"]["bull_trap_risk"], 45)
        self.assertTrue(any("Bull-trap" in item["name"] for item in result["traps"]["recent_events"]))
        self.assertIn(result["plan"]["action"], {"WAIT_TRAP_RESOLUTION", "TIGHTEN_RISK"})

    def test_failed_breakdown_is_flagged_as_bear_trap_risk(self):
        frame = market_frame(seed=31)
        prior_high = float(frame["High"].iloc[-21:-1].max())
        prior_low = float(frame["Low"].iloc[-21:-1].min())
        normal_volume = float(frame["Volume"].iloc[-21:-1].mean())
        frame.iloc[-1, frame.columns.get_loc("Open")] = prior_low * 0.998
        frame.iloc[-1, frame.columns.get_loc("High")] = min(prior_high, prior_low * 1.035)
        frame.iloc[-1, frame.columns.get_loc("Low")] = prior_low * 0.96
        frame.iloc[-1, frame.columns.get_loc("Close")] = prior_low * 1.015
        frame.iloc[-1, frame.columns.get_loc("Volume")] = normal_volume * 2.2
        result = analyze_frame(frame, company="TRAP", ticker="TRAP.VN")
        self.assertGreaterEqual(result["traps"]["bear_trap_risk"], 45)
        self.assertTrue(any("Bear-trap" in item["name"] for item in result["traps"]["recent_events"]))

    def test_position_size_respects_profile_and_sector_caps(self):
        result = analyze_frame(
            market_frame(),
            company="TEST",
            ticker="TEST.VN",
            profile="balanced",
            account_value=1_000_000,
            risk_pct=4,
            sector_exposure_pct=29,
        )
        sizing = result["plan"]["position_sizing"]
        self.assertEqual(sizing["effective_risk_pct"], 1.0)
        self.assertLessEqual(sizing["maximum_position_value"], 10_000)
        self.assertEqual(sizing["sector_room_pct"], 1.0)

    def test_short_or_incomplete_history_is_not_forced_into_a_plan(self):
        result = analyze_frame(market_frame(count=60), company="SHORT", ticker="SHORT.VN")
        self.assertFalse(result["success"])
        self.assertEqual(result["status"], "insufficient_history")

    def test_symbol_resolution_supports_vietnam_defaults_and_exact_yahoo_symbols(self):
        self.assertEqual(ticker_for("VCB"), "VCB.VN")
        self.assertEqual(ticker_for("YF:AAPL"), "AAPL")
        self.assertEqual(ticker_for("FPT Corporation"), "FPT.VN")

    def test_persistent_symbol_registry_can_add_a_company_without_code_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = Path(directory) / "company_symbols.json"
            registry.write_text('{"New International Company": "NIC"}', encoding="utf-8")
            with patch.object(stock, "SYMBOL_REGISTRY_PATH", registry):
                self.assertEqual(ticker_for("New International Company"), "NIC")

    @patch("engine.indicators_vsa._download_frames")
    def test_universe_screen_uses_one_batch_and_returns_ranked_research_candidates(self, download):
        download.return_value = {"AAA.VN": market_frame(seed=2), "BBB.VN": market_frame(seed=3)}
        result = screen_companies([
            {"company": "AAA", "fundamental_context": {"available": False}},
            {"company": "BBB", "fundamental_context": {"available": False}},
        ])
        self.assertEqual(download.call_count, 1)
        self.assertEqual(result["analyzed"], 2)
        self.assertEqual(len(result["candidates"]), 2)
        scores = [item["research_score"] for item in result["candidates"]]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertIn("not a command to buy", result["ranking_note"])


class IndicatorVSARouteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original_db = app_module.auth.DB_PATH
        self.original_storage = app_module.auth.STORAGE_DIR
        app_module.auth.STORAGE_DIR = Path(self.temp.name)
        app_module.auth.DB_PATH = Path(self.temp.name) / "vsa-route.sqlite3"
        app_module.auth.init_auth_db()
        app_module.app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
        self.client = app_module.app.test_client()
        user = app_module.auth.create_user(
            "vsa@example.com", "IndicatorsPass123", "VSA Researcher"
        )
        token = app_module.auth.start_session(user["id"], user_agent="VSA route test")
        with self.client.session_transaction() as session:
            session["user_id"] = user["id"]
            session["auth_token"] = token
            session["csrf_token"] = "vsa-csrf"

    def tearDown(self):
        app_module.auth.DB_PATH = self.original_db
        app_module.auth.STORAGE_DIR = self.original_storage
        self.temp.cleanup()

    def test_single_company_route_requires_csrf_and_passes_guarded_inputs(self):
        fake = {"success": True, "status": "ok", "company": "FPT", "plan": {"action": "WAIT_FOR_CONFIRMATION"}}
        with patch.object(app_module, "analyze_vsa_company", return_value=fake) as analyze:
            denied = self.client.post("/api/indicators-vsa/analyze", json={"company": "FPT"})
            self.assertEqual(denied.status_code, 400)
            response = self.client.post(
                "/api/indicators-vsa/analyze",
                json={"company": "FPT", "profile": "balanced", "risk_pct": 1},
                headers={"X-CSRF-Token": "vsa-csrf"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["plan"]["action"], "WAIT_FOR_CONFIRMATION")
        self.assertIn("fundamental_context", analyze.call_args.kwargs)

    def test_screen_route_uses_newly_discovered_library_companies(self):
        fake = {"success": True, "status": "ok", "analyzed": 1, "requested": 1, "candidates": []}
        with patch.object(app_module.db, "companies", return_value=[{"company": "NEW", "industry": "Test"}]), patch.object(
            app_module, "_indicator_statement_context", return_value={"available": True}
        ), patch.object(app_module, "screen_vsa_companies", return_value=fake) as screen:
            response = self.client.post(
                "/api/indicators-vsa/screen",
                json={"profile": "balanced"},
                headers={"X-CSRF-Token": "vsa-csrf"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(screen.call_args.args[0][0]["company"], "NEW")


if __name__ == "__main__":
    unittest.main()
