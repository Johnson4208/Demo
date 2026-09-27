import unittest
from pathlib import Path
import config
from engine import db
from engine.evidence import FORMULAS
from engine.portfolio_risk import analyze_portfolio

class V15FeatureTests(unittest.TestCase):
    def test_evidence_formulas(self):
        self.assertIn("Net margin", FORMULAS["net_margin"])
        self.assertIn("Same-period YoY", FORMULAS["revenue_growth"])
    def test_database_path_can_be_restored(self):
        db.DB_PATH = config.DB_PATH
        self.assertTrue(Path(config.STORAGE_DIR).exists())
    def test_portfolio_requires_two_holdings(self):
        out=analyze_portfolio([{"company":"FPT","weight":100}])
        self.assertTrue(out["status"].startswith("At least two"))

if __name__ == "__main__":
    unittest.main()
