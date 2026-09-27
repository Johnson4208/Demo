import unittest
from pathlib import Path
from pypdf import PdfReader
from engine.report_reader import infer_period_end, infer_year, infer_scope
from engine.report_extractor import extract

class V85Tests(unittest.TestCase):
    ROOT=Path(__file__).resolve().parents[1]
    def _text(self, rel):
        p=self.ROOT/rel
        if not p.exists():
            self.skipTest(f"fixture not bundled: {rel}")
        return "\n".join((pg.extract_text() or "") for pg in PdfReader(str(p)).pages)
    def test_cmg_quarter_has_correct_period_and_scope(self):
        rel='reports/Companies_reports/Technology/CMG/CMG.pdf'
        t=self._text(rel)
        p=self.ROOT/rel
        self.assertEqual(infer_period_end(t,p).isoformat(),'2026-06-30')
        self.assertEqual(infer_year(p,t),2026)
        self.assertEqual(infer_scope(p,t),'consolidated')
    def test_cmg_annual_is_verified_core_statement_not_toc(self):
        rel='reports/Companies_reports/Technology/CMG/20260629_-_CMG_-_BCTC_hop_nhat_kiem_toan_nam_2025_-_signed_1782787187.pdf'
        t=self._text(rel); parsed=extract(t,self.ROOT/rel)
        self.assertEqual(parsed['period_end'],'2026-03-31')
        self.assertEqual(parsed['scope'],'consolidated')
        self.assertIn('revenue',parsed['evidence_summary']['metrics'])
        self.assertIn('gross_profit',parsed['evidence_summary']['metrics'])
        self.assertIn('operating_profit',parsed['evidence_summary']['metrics'])
        self.assertIn('net_income',parsed['evidence_summary']['metrics'])
        self.assertEqual(parsed['status'],'verified')
    def test_noisy_quarter_filenames_do_not_use_upload_timestamp(self):
        self.assertEqual(infer_period_end('', 'FPT_202607272020FPT2020BCTC20hop20nhat20Quy202202026_28072026095429.pdf').isoformat(), '2026-06-30')
        self.assertEqual(infer_period_end('', 'PNJ_202607302020PNJ2020BCTC20quy20220nam20202620Hop20nhat_Signed_31072026112507.pdf').isoformat(), '2026-06-30')
        self.assertEqual(infer_period_end('', 'VNZ_vnz-bao-cao-tai-chinh-quy-1-2026-0-613317_20260616102031.pdf').isoformat(), '2026-03-31')

    def test_revenue_deductions_are_positive_for_reconciliation(self):
        rel='reports/Companies_reports/Technology/CMG/20260629_-_CMG_-_BCTC_hop_nhat_kiem_toan_nam_2025_-_signed_1782787187.pdf'
        t=self._text(rel); parsed=extract(t,self.ROOT/rel)
        vals={o[0]:o[1] for o in parsed['observations']}
        if 'revenue_reductions' in vals:
            self.assertGreaterEqual(vals['revenue_reductions'],0)
    def test_fuzzy_annual_filename_year_prefers_explicit_year(self):
        rel='reports/Companies_reports/Technology/CMG/20260629_-_CMG_-_BCTC_hop_nhat_kiem_toan_nam_2025_-_signed_1782787187.pdf'
        t=self._text(rel); self.assertEqual(infer_year(rel,t),2026)

if __name__=='__main__': unittest.main()
