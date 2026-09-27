import unittest
from pathlib import Path
from engine.report_extractor import extract
from engine.report_reader import infer_scope, infer_period_end


class V90Tests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[1]

    def test_pnj_coordinate_ocr_rows_reconcile(self):
        text = (self.ROOT / 'tests' / 'fixtures' / 'pnj_q2_ocr_rows.txt').read_text(encoding='utf-8')
        parsed = extract(
            'BAO CAO KET QUA HOAT DONG KINH DOANH HOP NHAT\n'
            'Quy 2 - ket thuc ngay 30 thang 6 nam 2026\n' + text,
            'PNJ_202607302020PNJ2020BCTC20quy20220nam20202620Hop20nhat_Signed_31072026112507.pdf',
        )
        vals = {x[0]: x[1] for x in parsed['observations']}
        self.assertEqual(parsed['scope'], 'consolidated')
        self.assertEqual(parsed['period_end'], '2026-06-30')
        self.assertAlmostEqual(vals['gross_revenue'], 8_584_251_763_101)
        self.assertAlmostEqual(vals['revenue_reductions'], 100_517_281_627)
        self.assertAlmostEqual(vals['revenue'], 8_483_734_481_474)
        self.assertAlmostEqual(vals['cost_of_goods_sold'], 6_920_475_604_552)
        self.assertAlmostEqual(vals['gross_profit'], 1_563_258_876_922)
        self.assertEqual(parsed['status'], 'verified')

    def test_vnz_separate_q2_never_becomes_consolidated(self):
        path = 'VNZ_000000016688778_VNGG_2026_FS_SSC_Separate_Q22026__V_execd_05082026102848.pdf'
        self.assertEqual(infer_scope(path, 'BAO CAO TAI CHINH RIENG'), 'separate')
        self.assertEqual(infer_period_end('Cho ky ke toan sau thang ket thuc ngay 30 thang 6 nam 2026', path).isoformat(), '2026-06-30')


if __name__ == '__main__':
    unittest.main()
