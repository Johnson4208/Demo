import math
import tempfile
import unittest
from pathlib import Path

import engine.db as db
from engine.report_extractor import extract
from engine.report_reader import infer_period_end, infer_scope
from engine.analysis import growth, overview, series
from engine.risk import beneish

Q1 = '''BÁO CÁO KẾT QUẢ HOẠT ĐỘNG KINH DOANH HỢP NHẤT
Cho kỳ hoạt động từ ngày 01 tháng 01 năm 2026 đến ngày 31 tháng 03 năm 2026
1 Doanh thu bán hàng và cung cấp dịch vụ 01 12.485.836.704.352 16.064.980.391.264 12.485.836.704.352 16.064.980.391.264
2 Các khoản giảm trừ 02 5.839.497.577 6.839.448.804 5.839.497.577 6.839.448.804
3 Doanh thu thuần về bán hàng và cung cấp dịch vụ 10 12.479.997.206.775 16.058.140.942.460 12.479.997.206.775 16.058.140.942.460
5 Lợi nhuận gộp về bán hàng và cung cấp dịch vụ 20 4.244.889.890.688 6.301.347.904.266 4.244.889.890.688 6.301.347.904.266
11 Lợi nhuận thuần từ hoạt động kinh doanh 30 2.747.763.827.050 2.993.843.378.813 2.747.763.827.050 2.993.843.378.813
18 Lợi nhuận sau thuế thu nhập doanh nghiệp 60 2.476.789.833.481 2.595.557.480.309 2.476.789.833.481 2.595.557.480.309
BÁO CÁO LƯU CHUYỂN TIỀN TỆ HỢP NHẤT
Khấu hao tài sản cố định và bất động sản đầu tư 02 409.926.454.508 644.023.121.646
Lưu chuyển tiền thuần từ hoạt động kinh doanh 20 (2.847.813.717.192) (2.506.903.722.401)'''

Q2 = '''BÁO CÁO KẾT QUẢ HOẠT ĐỘNG KINH DOANH HỢP NHẤT
Cho kỳ hoạt động từ ngày 01 tháng 01 năm 2026 đến ngày 30 tháng 06 năm 2026
1 Doanh thu bán hàng và cung cấp dịch vụ 01 13.810.340.987.151 16.658.335.760.739 26.296.177.691.503 32.723.316.152.003
2 Các khoản giảm trừ 02 21.837.525.952 33.622.720.672 27.677.023.529 40.462.169.476
3 Doanh thu thuần về bán hàng và cung cấp dịch vụ 10 13.788.503.461.199 16.624.713.040.067 26.268.500.667.974 32.682.853.982.527
5 Lợi nhuận gộp về bán hàng và cung cấp dịch vụ 20 4.278.629.180.214 6.021.040.042.975 8.523.519.070.902 12.322.387.947.241
11 Lợi nhuận thuần từ hoạt động kinh doanh 30 2.885.793.042.568 3.129.408.582.030 5.633.556.869.618 6.123.251.960.843
18 Lợi nhuận sau thuế thu nhập doanh nghiệp 60 2.570.406.121.615 2.740.271.400.678 5.047.195.955.096 5.335.828.880.987
Để người đọc có cái nhìn tương đồng khi so sánh, chúng tôi đã điều chỉnh lại số liệu cùng kỳ năm 2025 theo cùng một phương pháp kế toán như năm 2026, cụ thể như dưới đây: DVT: Triệu đồng
Doanh thu thuần 13.788.503 11.849.726 1.938.778 16,4% 26.268.501 23.325.686 2.942.815 12,6%
BÁO CÁO LƯU CHUYỂN TIỀN TỆ HỢP NHẤT
Khấu hao tài sản cố định và bất động sản đầu tư 02 844.627.213.729 1.365.988.701.427
Lưu chuyển tiền thuần từ hoạt động kinh doanh 20 (1.144.550.905.787} 1.683.573.278.329'''


def add_parsed(company, r, path, scope="consolidated"):
    db.replace_document(path, company, "Technology", r["year"], r["period_end"], scope, "8.1", path, "synthetic evidence text", r.get("quality_score",100), r.get("status","verified"), r.get("warnings",[]), 0)
    db.replace_observations(path, company, "Technology", r["year"], r["period_end"], r["observations"])


class FinancialMetricsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = Path(self.tmp.name) / "test.sqlite3"
        db.init_db()

    def tearDown(self):
        self.tmp.cleanup()

    def test_fpt_revenue_label_first_and_reconciliation(self):
        r = extract(Q2, "FPT_BCTC_hop_nhat_Quy_2_2026.pdf")
        obs = {x[0]: x for x in r["observations"]}
        self.assertEqual(r["scope"], "consolidated")
        self.assertAlmostEqual(obs["gross_revenue"][1], 13_810_340_987_151)
        self.assertAlmostEqual(obs["revenue_reductions"][1], 21_837_525_952)
        self.assertAlmostEqual(obs["revenue"][1], 13_788_503_461_199)
        self.assertAlmostEqual(obs["revenue"][5], 11_849_726_000_000)
        self.assertEqual(r["status"], "verified")

    def test_fpt_q1_q2_margins_and_yoy_growth(self):
        r1 = extract(Q1, "FPT_BCTC_hop_nhat_Quy_1_2026.pdf")
        r2 = extract(Q2, "FPT_BCTC_hop_nhat_Quy_2_2026.pdf")
        add_parsed("FPT", r1, "/tmp/fpt_q1.pdf")
        add_parsed("FPT", r2, "/tmp/fpt_q2.pdf")
        self.assertAlmostEqual(growth("FPT", "revenue"), 16.3614, places=3)
        margins = series("FPT", "net_margin")
        self.assertAlmostEqual(margins[-2]["value"], 19.8461, places=3)
        self.assertAlmostEqual(margins[-1]["value"], 18.6417, places=3)
        ebitda = series("FPT", "ebitda")
        self.assertAlmostEqual(ebitda[-2]["value"], 3_157_690_281_558, delta=2_000_000)
        self.assertAlmostEqual(ebitda[-1]["value"], 3_320_493_801_789, delta=2_000_000)
        ebitda_margin = series("FPT", "ebitda_margin")
        self.assertAlmostEqual(ebitda_margin[-2]["value"], 25.3020, places=3)
        self.assertAlmostEqual(ebitda_margin[-1]["value"], 24.0816, places=3)

    def test_revenue_growth_is_same_period_not_sequential_quarter(self):
        r1 = extract(Q1, "FPT_BCTC_hop_nhat_Quy_1_2026.pdf")
        r2 = extract(Q2, "FPT_BCTC_hop_nhat_Quy_2_2026.pdf")
        add_parsed("FPT", r1, "/tmp/fpt_q1.pdf")
        add_parsed("FPT", r2, "/tmp/fpt_q2.pdf")
        self.assertNotAlmostEqual(growth("FPT", "revenue"), 10.468, places=2)
        self.assertAlmostEqual(growth("FPT", "revenue"), (13_788_503_461_199/11_849_726_000_000-1)*100, places=2)

    def test_separate_statement_is_not_core_source(self):
        r = extract(Q2, "FPT_BCTC_rieng_Quy_2_2026.pdf")
        add_parsed("FPT", r, "/tmp/fpt_separate.pdf", scope="separate")
        self.assertIsNone(series("FPT", "revenue")) if False else None
        self.assertEqual(series("FPT", "revenue"), [])

    def test_failed_empty_parse_is_not_trusted(self):
        path="/tmp/failed.pdf"
        db.replace_document(path,"BAD","Technology",2026,"2026-06-30","consolidated","8.1","x","",0,"failed",["No line items"],1)
        db.replace_observations(path,"BAD","Technology",2026,"2026-06-30",[])
        self.assertEqual(series("BAD","revenue"),[])

    def test_beneish_gmi_is_gross_margin_not_sga_ratio(self):
        metrics = {
            2025: {"revenue":100,"gross_profit":30,"receivables":10,"current_assets":50,"ppe":20,"assets":100,"depreciation":10,"sga":20,"current_liabilities":30,"long_term_debt":20,"net_income":10,"cash_flow":8},
            2026: {"revenue":120,"gross_profit":36,"receivables":12,"current_assets":60,"ppe":22,"assets":120,"depreciation":11,"sga":24,"current_liabilities":36,"long_term_debt":25,"net_income":12,"cash_flow":9},
        }
        for year,data in metrics.items():
            period=f"{year}-12-31"; path=f"/tmp/synthetic_{year}.pdf"
            db.replace_document(path,"SYN","Technology",year,period,"consolidated","8.1",str(year),"synthetic",100,"verified",[],0)
            obs=[]
            for metric,val in data.items():
                comp=metrics[year-1][metric] if year==2026 else None
                obs.append((metric,val,"absolute",0.9,"statement",comp))
            db.replace_observations(path,"SYN","Technology",year,period,obs)
        b=beneish("SYN")
        self.assertEqual(b["status"], "ok")
        self.assertIn("GMI", b["components"])
        self.assertTrue(math.isfinite(b["risk_proxy_pct"]))

    def test_growth_without_prior_year_is_unavailable_not_sequential_quarter(self):
        r1 = extract(Q1, "FPT_BCTC_hop_nhat_Quy_1_2026.pdf")
        r2 = extract(Q2, "FPT_BCTC_hop_nhat_Quy_2_2026.pdf")
        # Remove the report-provided Q2 prior-year comparator to simulate a dataset
        # containing only Q1/Q2 of the current year. Growth must not become Q2/Q1.
        r2["observations"]=[tuple(list(x[:5])+[None]) if x[0] in {"revenue","gross_revenue","revenue_reductions"} else x for x in r2["observations"]]
        add_parsed("NOYOY", r1, "/tmp/noyoy_q1.pdf")
        add_parsed("NOYOY", r2, "/tmp/noyoy_q2.pdf")
        self.assertIsNone(growth("NOYOY","revenue"))

    def test_filename_quarter_period_fallback(self):
        self.assertEqual(infer_period_end("", "FPT_Quy_1_2026.pdf").isoformat(), "2026-03-31")
        self.assertEqual(infer_period_end("", "FPT_Quy_2_2026.pdf").isoformat(), "2026-06-30")

    def test_period_end_and_scope_prefer_statement_context(self):
        text="Cho ky tai chinh tu ngay 01/04/2025 den ngay 31/03/2026\nBAO CAO TAI CHINH HOP NHAT"
        self.assertEqual(infer_period_end(text,"CMG_nam_2025.pdf").isoformat(),"2026-03-31")
        self.assertEqual(infer_scope("CMG_nam_2025.pdf",text),"consolidated")

    def test_added_derived_metrics(self):
        r1 = extract(Q1, "FPT_BCTC_hop_nhat_Quy_1_2026.pdf")
        r1["observations"].extend([
            ("assets",100,"absolute",0.9,"statement",90),
            ("equity",50,"absolute",0.9,"statement",45),
        ])
        add_parsed("DER", r1, "/tmp/der_q1.pdf")
        self.assertTrue(series("DER","roa"))
        self.assertTrue(series("DER","roe"))
        self.assertTrue(series("DER","cash_flow_margin"))

    def test_overview_exposes_every_scanned_report_line_to_full_research(self):
        parsed = extract(Q2, "FPT_BCTC_hop_nhat_Quy_2_2026.pdf")
        parsed["observations"].extend([
            ("assets", 1_000, "absolute", 0.98, "reconciled_balance_sheet", 900),
            ("total_liabilities", 400, "absolute", 0.98, "reconciled_balance_sheet", 350),
            ("equity", 600, "absolute", 0.98, "reconciled_balance_sheet", 550),
            ("total_sources", 1_000, "absolute", 0.98, "reconciled_balance_sheet", 900),
            ("current_assets", 500, "absolute", 0.92, "statement_label", 450),
            ("current_liabilities", 250, "absolute", 0.92, "statement_label", 220),
            ("receivables", 120, "absolute", 0.92, "statement_label", 100),
            ("ppe", 300, "absolute", 0.92, "statement_label", 280),
            ("short_term_debt", 80, "absolute", 0.92, "statement_label", 70),
            ("long_term_debt", 120, "absolute", 0.92, "statement_label", 110),
            ("debt", 200, "absolute", 0.92, "derived", 180),
        ])
        add_parsed("FULL", parsed, "/tmp/full_research_q2.pdf")

        result = overview("FULL")
        expected = {
            "gross_revenue", "revenue_reductions", "revenue", "gross_profit",
            "operating_profit", "net_income", "depreciation", "assets",
            "total_liabilities", "equity", "total_sources", "current_assets",
            "current_liabilities", "receivables", "ppe", "short_term_debt",
            "long_term_debt", "debt", "cash_flow", "ebitda", "net_margin",
        }
        self.assertTrue(expected.issubset(result["metrics"]))
        self.assertEqual(result["metrics"]["current_assets"]["value"], 500)
        self.assertEqual(result["metrics"]["debt"]["value"], 200)
        self.assertEqual(result["scan_coverage"]["total_metrics"], 26)
        self.assertEqual(result["scan_coverage"]["metric_status"]["current_assets"], "available")


    def test_parent_profit_code_61_rescue(self):
        text = '''BÁO CÁO KẾT QUẢ HOẠT ĐỘNG KINH DOANH HỢP NHẤT
Lợi nhuận sau thuế thu nhập doanh nghiệp 60 115.352.666.096 0
61 182.059.885.970 -4.844.877.110
62 -66.707.219.874 -10.089.673.118
'''
        r=extract(text,'VNG_BCTC_hop_nhat_Quy_1_2026.pdf')
        vals={x[0]:x[1] for x in r['observations']}
        self.assertAlmostEqual(vals['net_income'],182_059_885_970)


if __name__ == "__main__":
    unittest.main()

class V13RegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = Path(self.tmp.name) / 'test.sqlite3'
        db.init_db()

    def tearDown(self):
        self.tmp.cleanup()

    def test_parent_profit_drives_roa_roe_for_consolidated(self):
        path='/tmp/vng_q1.pdf'
        db.replace_document(path,'VNG','Technology',2026,'2026-03-31','consolidated','13.1.0','vng','synthetic',100,'verified',[],0)
        obs=[
            ('net_income_parent',182_059_885_970,'absolute',0.98,'statement_parent_profit',-4_844_877_110),
            ('net_income',115_352_666_096,'absolute',0.92,'statement_total_profit',-14_934_550_228),
            ('assets',10_733_168_737_455,'absolute',0.9,'statement_label',11_352_254_039_576),
            ('equity',669_982_543_256,'absolute',0.9,'statement_label',890_234_066_308),
        ]
        db.replace_observations(path,'VNG','Technology',2026,'2026-03-31',obs)
        roa=series('VNG','roa')[-1]['value']; roe=series('VNG','roe')[-1]['value']
        self.assertAlmostEqual(roa, 1.649, places=2)
        self.assertAlmostEqual(roe, 23.34, places=2)

    def test_same_period_growth_rejects_ytd_comparator(self):
        path='/tmp/pnj_q2.pdf'
        db.replace_document(path,'PNJ','Retail',2026,'2026-06-30','consolidated','13.1.0','pnj','synthetic',100,'verified',[],0)
        obs=[('revenue',8_483_734_481_474,'absolute',0.995,'reconciled_income_statement',25_728_965_480_762)]
        db.replace_observations(path,'PNJ','Retail',2026,'2026-06-30',obs)
        self.assertIsNone(growth('PNJ','revenue'))

    def test_legal_name_resolves_to_market_alias(self):
        path='/tmp/vng_name.pdf'
        db.replace_document(path,'CÔNG TY CỔ PHẦN TẬP ĐOÀN VNG','Technology',2026,'2026-03-31','consolidated','13.1.0','name','synthetic',100,'verified',[],0)
        db.replace_observations(path,'CÔNG TY CỔ PHẦN TẬP ĐOÀN VNG','Technology',2026,'2026-03-31',[('revenue',100,'absolute',0.9,'statement_label',90)])
        self.assertEqual(series('VNG','revenue')[-1]['value'],100)


class V13_2RegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = Path(self.tmp.name) / 'test.sqlite3'
        db.init_db()

    def tearDown(self):
        self.tmp.cleanup()

    def test_reconciled_metric_survives_document_quality_review(self):
        path='/tmp/review_quality.pdf'
        db.replace_document(path,'REVIEWCO','Technology',2026,'2026-06-30','consolidated','13.2.0','reviewq','synthetic',60,'review',[],0)
        db.replace_observations(path,'REVIEWCO','Technology',2026,'2026-06-30',[
            ('revenue',100,'absolute',0.99,'reconciled_income_statement',80),
            ('net_income_parent',10,'absolute',0.98,'statement_parent_profit',8),
            ('assets',120,'absolute',0.95,'reconciled_balance_sheet',110),
            ('equity',70,'absolute',0.95,'reconciled_balance_sheet',65),
        ])
        self.assertEqual(series('REVIEWCO','revenue')[-1]['value'],100)
        self.assertTrue(series('REVIEWCO','roa'))
        self.assertTrue(series('REVIEWCO','roe'))

    def test_market_ttm_ratios_require_four_quarters(self):
        for q,period in enumerate(['2025-09-30','2025-12-31','2026-03-31','2026-06-30'], start=1):
            path=f'/tmp/ttm_{q}.pdf'
            db.replace_document(path,'TTMCO','Technology',int(period[:4]),period,'consolidated','13.2.0',str(q),'synthetic',100,'verified',[],0)
            rev=100*q; ni=10*q; assets=1000+20*q; equity=500+10*q; op=ni+2; dep=3
            db.replace_observations(path,'TTMCO','Technology',int(period[:4]),period,[
                ('revenue',rev,'absolute',0.99,'statement_label',None),
                ('net_income_parent',ni,'absolute',0.98,'statement_parent_profit',None),
                ('assets',assets,'absolute',0.95,'reconciled_balance_sheet',None),
                ('equity',equity,'absolute',0.95,'reconciled_balance_sheet',None),
                ('operating_profit',op,'absolute',0.95,'statement_label',None),
                ('depreciation',dep,'absolute',0.95,'statement_cashflow_ytd',None),
            ])
        from engine.analysis import _ttm_ratio_series
        ttm_margin=_ttm_ratio_series('TTMCO','net_margin_ttm')
        self.assertIsNotNone(ttm_margin)
        self.assertAlmostEqual(ttm_margin['value'],10.0,places=6)
        self.assertEqual(ttm_margin['basis'],'TTM')
