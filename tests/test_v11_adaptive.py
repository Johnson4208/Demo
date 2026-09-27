import unittest
import config
from engine import report_reader

class V11AdaptiveTests(unittest.TestCase):
    def test_all_pages_is_default(self):
        self.assertEqual(config.OCR_MAX_PAGES, 0)

    def test_anchor_scoring_detects_accounting_page(self):
        text = "BAO CAO KET QUA HOAT DONG KINH DOANH\nDoanh thu thuan 8.483.734.481.474"
        self.assertGreaterEqual(report_reader._page_anchor_score(text), 10)

    def test_ocr_page_selection_is_not_first_n_only(self):
        pages=[(i,"") for i in range(45)]
        self.assertEqual(report_reader._choose_ocr_pages(None,pages), list(range(45)))

if __name__ == "__main__":
    unittest.main()


class TestWebsiteMetricFixes(unittest.TestCase):
    def setUp(self):
        import sqlite3, tempfile, shutil
        from pathlib import Path
        import config
        source=Path(__file__).resolve().parents[1] / "storage" / "financial_ai.sqlite3"
        if not source.exists() or source.stat().st_size == 0:
            self.skipTest("indexed financial report database is not bundled")
        try:
            with sqlite3.connect(f"file:{source.resolve().as_posix()}?mode=ro", uri=True) as connection:
                indexed_rows=connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
        except sqlite3.Error:
            indexed_rows=0
        if not indexed_rows:
            self.skipTest("indexed financial report database is not bundled")
        self.tmp=tempfile.TemporaryDirectory()
        config.DB_PATH=Path(self.tmp.name)/"financial_ai.sqlite3"
        from engine import db
        db.DB_PATH=config.DB_PATH
        if source.exists():
            shutil.copy2(source, config.DB_PATH)
        db.init_db()

    def tearDown(self):
        self.tmp.cleanup()

    def test_expected_latest_period_metrics_from_known_reports(self):
        # These are calculated from the actual indexed reports bundled with the package.
        from engine.analysis import overview
        fpt=overview("FPT")["metrics"]
        self.assertAlmostEqual(float(fpt["revenue_growth"]),16.3614,places=2)
        self.assertAlmostEqual(fpt["net_margin"]["value"],18.6217,places=2)
        self.assertAlmostEqual(fpt["ebitda_margin"]["value"],24.0816,places=2)
        self.assertAlmostEqual(fpt["roa"]["value"],3.1724,places=2)
        self.assertAlmostEqual(fpt["roe"]["value"],6.0598,places=2)

    def test_pnj_revenue_growth_from_reconciled_comparator(self):
        from engine.analysis import overview
        pnj=overview("PNJ")["metrics"]
        self.assertIsNotNone(pnj["revenue_growth"])
        self.assertAlmostEqual(float(pnj["revenue_growth"]),11.8865,places=2)

    def test_pnj_ebitda_can_use_q2_reported_depreciation(self):
        from engine.analysis import _quarter_depreciation, overview
        dep=_quarter_depreciation("PNJ")
        self.assertTrue(dep)
        pnj=overview("PNJ")["metrics"]
        # PNJ Q2 operating profit is negative; EBITDA should therefore also be negative.
        self.assertIsNotNone(pnj["ebitda_margin"])
        self.assertAlmostEqual(pnj["ebitda_margin"]["value"],-3.6339,places=2)

    def test_cmg_q2_does_not_subtract_fiscal_year_end_depreciation(self):
        from engine.analysis import overview
        cmg=overview("CMC")["metrics"]
        self.assertAlmostEqual(cmg["ebitda_margin"]["value"],10.1787,places=2)
