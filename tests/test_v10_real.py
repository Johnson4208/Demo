import unittest
from pathlib import Path
from pypdf import PdfReader
from engine.report_extractor import extract

class V10RealTests(unittest.TestCase):
    def test_cmg_q2_real_statement_reconciles(self):
        p=Path("/mnt/data/CMG(1).pdf")
        if not p.exists(): self.skipTest("CMG report not available")
        text="\n".join((pg.extract_text() or "") for pg in PdfReader(str(p)).pages)
        r=extract(text,p); vals={x[0]:x[1] for x in r["observations"]}
        self.assertEqual(r["period_end"],"2026-06-30")
        self.assertEqual(r["scope"],"consolidated")
        self.assertAlmostEqual(vals["revenue"],2_323_243_675_183)
        self.assertAlmostEqual(vals["assets"],10_769_089_838_852)
        self.assertAlmostEqual(vals["total_liabilities"],6_576_410_384_030)
        self.assertAlmostEqual(vals["equity"],4_192_679_454_822)
        self.assertAlmostEqual(vals["assets"],vals["total_liabilities"]+vals["equity"],delta=1)
        self.assertAlmostEqual(vals["short_term_debt"],1_515_315_059_906)
        self.assertAlmostEqual(vals["long_term_debt"],2_304_232_434_546)

    def test_market_aliases(self):
        from engine.stock import ticker_for
        self.assertEqual(ticker_for("VNG"),"VNZ.VN")
        self.assertEqual(ticker_for("Công ty Cổ phần Tập đoàn VNG"),"VNZ.VN")
        self.assertEqual(ticker_for("Công ty Cổ phần Tập đoàn Công nghệ CMC"),"CMG.VN")

if __name__=="__main__": unittest.main()
