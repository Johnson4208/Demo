import unittest

import numpy as np
import pandas as pd

from engine.stock import _walk_forward_slices, analyze_frame


class StockQuantTests(unittest.TestCase):
    def test_walk_forward_validation_preserves_horizon_gap(self):
        rows = _walk_forward_slices(900, 63)
        self.assertGreaterEqual(len(rows), 2)
        for training, validation in rows:
            self.assertEqual(validation.start - training.stop, 63)
            self.assertGreaterEqual(training.stop, 180)
            self.assertGreaterEqual(validation.stop - validation.start, 20)

    def test_calibrated_horizon_has_bounded_probabilities_and_quality_metrics(self):
        rng = np.random.default_rng(7)
        count = 760
        cycle = np.sin(np.arange(count) / 16.0) * 0.004
        returns = 0.0002 + cycle + rng.normal(0, 0.009, count)
        close = 100.0 * np.exp(np.cumsum(returns))
        volume = rng.lognormal(15.0, 0.25, count)
        frame = pd.DataFrame(
            {"Close": close, "Volume": volume},
            index=pd.date_range("2022-01-03", periods=count, freq="B"),
        )
        result = analyze_frame(
            frame,
            horizons=({"key": "5d", "label": "1 week", "trading_days": 5},),
        )
        self.assertEqual(result["status"], "ok")
        horizon = result["horizons"][0]
        self.assertAlmostEqual(horizon["up_probability"] + horizon["down_probability"], 1.0)
        self.assertIn(horizon["direction"], {"UPWARD", "DOWNWARD", "UNCERTAIN"})
        self.assertIn("brier_score", horizon["validation"])
        self.assertIn("baseline_brier_score", horizon["validation"])
        self.assertIn("log_loss", horizon["validation"])
        self.assertGreaterEqual(horizon["validation"]["folds"], 2)
        self.assertTrue(horizon["feature_importance"])

    def test_short_history_does_not_force_a_direction(self):
        frame = pd.DataFrame(
            {
                "Close": np.linspace(100, 120, 180),
                "Volume": np.linspace(1_000_000, 1_200_000, 180),
            },
            index=pd.date_range("2025-01-01", periods=180, freq="B"),
        )
        result = analyze_frame(frame)
        self.assertNotEqual(result["status"], "ok")
        self.assertTrue(all(row["status"] == "unavailable" for row in result["horizons"]))

    def test_quant_interface_exposes_validation_not_just_accuracy(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        script = (root / "static" / "app.js").read_text(encoding="utf-8")
        styles = (root / "static" / "quant.css").read_text(encoding="utf-8")
        self.assertIn("MULTI-HORIZON OUTLOOK", script)
        self.assertIn("Brier skill", script)
        self.assertIn("WALK-FORWARD VALIDATION", script)
        self.assertIn("quant-horizon-grid", styles)


if __name__ == "__main__":
    unittest.main()
