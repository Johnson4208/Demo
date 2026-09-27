import unittest
from unittest.mock import patch

import pandas as pd

from engine import dashboard_macro


def frame(series, rows):
    return pd.DataFrame({
        "observation_date": pd.to_datetime([date for date, _value in rows]),
        series: [value for _date, value in rows],
    })


def payload(points, latest=None):
    values = [{"date": date, "value": value} for date, value in points]
    return {
        "success": True,
        "points": values,
        "latest": values[-1] if latest is None else latest,
    }


class DashboardMacroTests(unittest.TestCase):
    def test_retail_sales_is_transparently_normalized_to_january_2020(self):
        source = frame("RSXFS", [
            ("2019-12-01", 180.0),
            ("2020-01-01", 200.0),
            ("2020-02-01", 220.0),
        ])
        spec = next(item for item in dashboard_macro.SERIES_SPECS if item["key"] == "retail_sales")
        points = dashboard_macro._points(source, spec)
        self.assertAlmostEqual(points[1]["value"], 100.0)
        self.assertAlmostEqual(points[2]["value"], 110.0)

    def test_series_payload_reports_previous_change_and_period_peaks(self):
        spec = next(item for item in dashboard_macro.SERIES_SPECS if item["key"] == "cpi")
        source = frame("CPIAUCSL", [
            ("2024-01-01", 305.0),
            ("2025-01-01", 310.0),
            ("2025-02-01", 312.0),
            ("2025-03-01", 311.0),
        ])
        with patch.object(dashboard_macro, "_fred", return_value=source):
            result = dashboard_macro._series_payload(spec)
        self.assertTrue(result["success"])
        self.assertEqual(result["comparison"]["direction"], "down")
        self.assertFalse(result["comparison"]["exceeds_previous"])
        self.assertEqual(result["peaks"]["12m"]["value"], 312.0)
        self.assertEqual(result["peaks"]["12m"]["date"], "2025-02-01")

    def test_outlook_combines_inflation_and_slowdown_conditions(self):
        series = {
            "cpi": payload([(f"2024-{month:02d}-01", 100.0 + month * .1) for month in range(1, 13)] + [("2025-01-01", 105.0)]),
            "fed_rate": payload([("2024-12-01", 4.5), ("2025-01-01", 4.5)]),
            "retail_sales": payload([
                ("2024-10-01", 101.0), ("2024-11-01", 100.5),
                ("2024-12-01", 100.0), ("2025-01-01", 98.5),
            ]),
            "unemployment": payload([
                ("2024-10-01", 3.8), ("2024-11-01", 3.9),
                ("2024-12-01", 4.0), ("2025-01-01", 4.2),
            ]),
            "gasoline": payload([
                ("2024-12-02", 3.00), ("2024-12-09", 3.04), ("2024-12-16", 3.08),
                ("2024-12-23", 3.12), ("2024-12-30", 3.20),
            ]),
        }
        result = dashboard_macro._outlook(series)
        self.assertEqual(result["status"], "Inflation and slowdown risk")
        self.assertEqual(result["tone"], "risk")
        self.assertGreaterEqual(len(result["warnings"]), 4)
        self.assertIn("purchasing power", result["conclusion"])
        self.assertIn("not a forecast", result["methodology"])

    def test_scenario_rankings_match_the_current_five_chart_signal_order(self):
        rankings = dashboard_macro._scenario_rankings({
            "cpi_yoy_pct": 3.7,
            "cpi_1m_pct": 0.4,
            "fed_rate_pct": 3.63,
            "fed_rate_3m_pp": 0.0,
            "retail_3m_pct": 0.8,
            "retail_1m_pct": 1.2,
            "unemployment_rate_pct": 4.1,
            "unemployment_3m_pp": -0.2,
            "sahm_indicator_pp": -0.2,
            "gasoline_4w_pct": 6.7,
        })
        self.assertEqual(
            [row["key"] for row in rankings],
            [
                "higher_for_longer",
                "soft_landing",
                "inflation_reacceleration",
                "consumer_slowdown",
                "disinflation_cuts",
            ],
        )
        self.assertEqual([row["signal_score"] for row in rankings], [5.0, 5.0, 4.0, 3.0, 2.0])
        self.assertEqual([row["rank"] for row in rankings], [1, 2, 3, 4, 5])
        self.assertTrue(rankings[0]["is_leading"])
        self.assertTrue(all(row["coverage"] == 5 for row in rankings))
        self.assertTrue(all(len(row["evidence"]) == 5 for row in rankings))

    def test_disinflation_path_ranks_first_when_all_five_charts_turn_weaker(self):
        rankings = dashboard_macro._scenario_rankings({
            "cpi_yoy_pct": 1.8,
            "cpi_1m_pct": -0.2,
            "fed_rate_pct": 2.0,
            "fed_rate_3m_pp": -0.5,
            "retail_3m_pct": -0.7,
            "retail_1m_pct": -0.3,
            "unemployment_rate_pct": 4.8,
            "unemployment_3m_pp": 0.4,
            "sahm_indicator_pp": 0.5,
            "gasoline_4w_pct": -5.0,
        })
        self.assertEqual(rankings[0]["key"], "disinflation_cuts")
        self.assertEqual(rankings[0]["signal_score"], 5.0)
        self.assertIn("rate cuts", rankings[0]["consequence"])

    def test_scenario_strength_is_labeled_as_fit_not_probability(self):
        rankings = dashboard_macro._scenario_rankings({
            "cpi_yoy_pct": 3.1,
            "cpi_1m_pct": 0.2,
            "fed_rate_pct": 4.0,
            "fed_rate_3m_pp": 0.0,
            "retail_3m_pct": 0.2,
            "retail_1m_pct": 0.1,
            "unemployment_rate_pct": 4.2,
            "unemployment_3m_pp": 0.0,
            "sahm_indicator_pp": 0.0,
            "gasoline_4w_pct": 2.0,
        })
        self.assertTrue(all("probability" not in row["signal_label"].lower() for row in rankings))
        self.assertTrue(all(1.0 <= row["signal_score"] <= 5.0 for row in rankings))

    def test_macro_engine_uses_real_retail_sahm_and_half_weighted_gasoline(self):
        rankings = dashboard_macro._scenario_rankings({
            "cpi_yoy_pct": 3.2,
            "cpi_1m_pct": 0.3,
            "fed_rate_pct": 4.0,
            "fed_rate_3m_pp": 0.0,
            "retail_3m_pct": 0.4,
            "unemployment_rate_pct": 4.1,
            "unemployment_3m_pp": 0.0,
            "sahm_indicator_pp": 0.1,
            "gasoline_4w_pct": 4.0,
        })
        leading = rankings[0]
        gas = next(row for row in leading["evidence"] if row["key"] == "gasoline")
        retail = next(row for row in leading["evidence"] if row["key"] == "retail_sales")
        labor = next(row for row in leading["evidence"] if row["key"] == "unemployment")
        self.assertEqual(gas["weight"], 0.5)
        self.assertIn("real / 3m", retail["value"])
        self.assertIn("Sahm", labor["value"])

    def test_snapshot_keeps_the_five_series_in_the_product_order(self):
        def fake_series(spec, force=False):
            result = payload([("2024-12-01", 1.0), ("2025-01-01", 2.0)])
            return {**spec, **result, "data_mode": "live", "live": True, "stale_fallback": False, "comparison": dashboard_macro._change(result["points"]), "peaks": {"12m": result["latest"], "24m": result["latest"], "5y": result["latest"]}}

        with patch.object(dashboard_macro, "_series_payload", side_effect=fake_series):
            result = dashboard_macro.dashboard_macro_snapshot()
        self.assertTrue(result["success"])
        self.assertEqual(result["available_series"], 5)
        self.assertEqual(result["live_series"], 5)
        self.assertEqual(result["snapshot_series"], 0)
        self.assertEqual(result["data_mode"], "live")
        self.assertEqual(list(result["series"]), ["cpi", "fed_rate", "retail_sales", "unemployment", "gasoline"])
        self.assertEqual(result["refresh_seconds"], 1800)

    def test_live_failure_uses_the_packaged_official_snapshot(self):
        spec = next(item for item in dashboard_macro.SERIES_SPECS if item["key"] == "gasoline")
        source = frame("GASREGW", [("2025-01-06", 3.01), ("2025-01-13", 3.08)])
        with patch.object(dashboard_macro, "_fred", side_effect=RuntimeError("provider offline")), patch.object(
            dashboard_macro, "_snapshot_frame", return_value=(source, "2025-01-14T00:00:00+00:00")
        ):
            result = dashboard_macro._series_payload(spec)
        self.assertTrue(result["success"])
        self.assertTrue(result["stale_fallback"])
        self.assertFalse(result["live"])
        self.assertEqual(result["data_mode"], "snapshot")
        self.assertEqual(result["latest"]["value"], 3.08)
        self.assertIn("packaged official FRED snapshot", result["provider_note"])

    def test_series_is_unavailable_only_when_live_and_snapshot_both_fail(self):
        spec = next(item for item in dashboard_macro.SERIES_SPECS if item["key"] == "gasoline")
        with patch.object(dashboard_macro, "_fred", side_effect=RuntimeError("provider offline")), patch.object(
            dashboard_macro, "_snapshot_frame", side_effect=RuntimeError("snapshot missing")
        ):
            result = dashboard_macro._series_payload(spec)
        self.assertFalse(result["success"])
        self.assertEqual(result["points"], [])
        self.assertIsNone(result["latest"]["value"])
        self.assertEqual(result["data_mode"], "unavailable")
        self.assertIn("Live provider failed", result["error"])

    def test_packaged_snapshot_contains_every_official_series(self):
        for spec in dashboard_macro.SERIES_SPECS:
            with self.subTest(series=spec["series"]):
                source, captured_at = dashboard_macro._snapshot_frame(spec["series"])
                self.assertGreaterEqual(len(source), 60)
                self.assertTrue(captured_at)
                self.assertTrue(source[spec["series"]].notna().all())

    def test_outlook_is_withheld_when_too_few_official_series_are_available(self):
        result = dashboard_macro._outlook({
            "cpi": payload([("2024-01-01", 100.0), ("2025-01-01", 104.0)]),
        })
        self.assertEqual(result["status"], "Insufficient published data")
        self.assertEqual(result["warnings"], [])
        self.assertIn("withheld", result["conclusion"])


if __name__ == "__main__":
    unittest.main()
