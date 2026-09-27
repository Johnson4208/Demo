import re
import unittest
from hashlib import sha256
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def assert_balanced_css(test_case, path):
    css = path.read_text(encoding="utf-8")
    stack = []
    quote = None
    comment = False
    escaped = False
    pairs = {")": "(", "]": "[", "}": "{"}

    index = 0
    while index < len(css):
        char = css[index]
        following = css[index + 1] if index + 1 < len(css) else ""
        if comment:
            if char == "*" and following == "/":
                comment = False
                index += 1
        elif quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
        elif char == "/" and following == "*":
            comment = True
            index += 1
        elif char in {'"', "'"}:
            quote = char
        elif char in "([{":
            stack.append(char)
        elif char in ")]}":
            test_case.assertTrue(stack, f"{path.name}: unmatched {char}")
            test_case.assertEqual(stack.pop(), pairs[char], f"{path.name}: mismatched {char}")
        index += 1

    test_case.assertFalse(comment, f"{path.name}: unclosed comment")
    test_case.assertIsNone(quote, f"{path.name}: unclosed string")
    test_case.assertFalse(stack, f"{path.name}: unclosed delimiter")


class InterfaceCSSRegressionTests(unittest.TestCase):
    def test_all_stylesheets_have_balanced_structure(self):
        for stylesheet in sorted((ROOT / "static").glob("*.css")):
            with self.subTest(stylesheet=stylesheet.name):
                assert_balanced_css(self, stylesheet)

    def test_font_shorthand_does_not_mix_inherit_with_components(self):
        invalid = re.compile(r"font\s*:\s*[^;{}]+\s+inherit\s*(?:;|})")
        for stylesheet in sorted((ROOT / "static").glob("*.css")):
            css = stylesheet.read_text(encoding="utf-8")
            with self.subTest(stylesheet=stylesheet.name):
                self.assertIsNone(invalid.search(css))

    def test_refresh_layer_loads_after_feature_styles(self):
        template = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        stylesheets = re.findall(r'href="(/static/[^"]+\.css)[^"]*"', template)
        self.assertIn("/static/quant.css", stylesheets)
        self.assertIn("/static/interface-refresh.css", stylesheets)
        self.assertGreater(
            stylesheets.index("/static/interface-refresh.css"),
            stylesheets.index("/static/quant.css"),
        )

    def test_account_pages_load_shared_refresh_last(self):
        pages = {
            "auth.html": "/static/auth.css",
            "admin_users.html": "/static/admin.css",
            "account_security.html": "/static/security.css",
        }
        for template_name, page_stylesheet in pages.items():
            template = (ROOT / "templates" / template_name).read_text(encoding="utf-8")
            stylesheets = re.findall(r'href="(/static/[^"]+\.css)[^"]*"', template)
            with self.subTest(template=template_name):
                self.assertIn(page_stylesheet, stylesheets)
                self.assertIn("/static/account-refresh.css", stylesheets)
                self.assertGreater(
                    stylesheets.index("/static/account-refresh.css"),
                    stylesheets.index(page_stylesheet),
                )

    def test_feature_views_and_actions_remain_available(self):
        template = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        expected_views = {
            "overview", "compare", "stock", "indicatorsVsa", "risk", "macro", "eventProbability",
            "news", "learn", "portfolio", "watchlist", "guardian", "systemHealth",
        }
        self.assertTrue(expected_views.issubset(set(re.findall(r'data-view="([^"]+)"', template))))
        self.assertIn('data-action="valuation"', template)
        self.assertIn('data-action="event-probability"', template)
        self.assertIn('data-action="portfolio-risk"', template)
        self.assertIn('data-action="vsa-analyze"', template)
        self.assertIn('data-action="vsa-screen"', template)

    def test_vsa_styles_load_after_the_shared_refresh_layer(self):
        template = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        stylesheets = re.findall(r'href="(/static/[^"]+\.css)[^"]*"', template)
        self.assertIn("/static/indicators-vsa.css", stylesheets)
        self.assertGreater(
            stylesheets.index("/static/indicators-vsa.css"),
            stylesheets.index("/static/interface-refresh.css"),
        )

    def test_feature_workspace_and_scoped_risk_layer_stay_off_dashboard(self):
        template = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        stylesheets = re.findall(r'href="(/static/[^"]+\.css)[^"]*"', template)
        self.assertIn("/static/feature-workspace.css", stylesheets)
        self.assertEqual(stylesheets[-1], "/static/risk-workspace.css")
        self.assertGreater(
            stylesheets.index("/static/risk-workspace.css"),
            stylesheets.index("/static/feature-workspace.css"),
        )
        css = (ROOT / "static" / "feature-workspace.css").read_text(encoding="utf-8")
        self.assertNotIn("#overview", css)
        self.assertNotIn(".dashboard-view", css)
        risk_css = (ROOT / "static" / "risk-workspace.css").read_text(encoding="utf-8")
        self.assertIn(".feature-view-risk", risk_css)
        self.assertNotIn("#overview", risk_css)
        self.assertNotIn(".dashboard-view", risk_css)
        for view_id in (
            "compare", "stock", "indicatorsVsa", "risk", "macro", "eventProbability",
            "news", "learn", "portfolio", "watchlist", "guardian", "systemHealth",
        ):
            opening_tag = re.search(rf'<section id="{view_id}"[^>]*>', template)
            self.assertIsNotNone(opening_tag, view_id)
            self.assertIn("feature-view", opening_tag.group(0), view_id)

    def test_company_overview_mode_fixes_load_after_the_refresh_layer(self):
        template = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        stylesheets = re.findall(r'href="(/static/[^"]+\.css)[^"]*"', template)
        self.assertIn("/static/dashboard-mode-fixes.css", stylesheets)
        self.assertGreater(
            stylesheets.index("/static/dashboard-mode-fixes.css"),
            stylesheets.index("/static/interface-refresh.css"),
        )

    def test_full_research_layer_loads_after_dashboard_fixes_and_after_app_javascript(self):
        template = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        stylesheets = re.findall(r'href="(/static/[^"]+\.css)[^"]*"', template)
        scripts = re.findall(r'src="(/static/[^"]+\.js)[^"]*"', template)
        self.assertIn("/static/company-full-workspace.css", stylesheets)
        self.assertGreater(
            stylesheets.index("/static/company-full-workspace.css"),
            stylesheets.index("/static/dashboard-mode-fixes.css"),
        )
        self.assertIn("/static/company-full-workspace.js", scripts)
        self.assertGreater(
            scripts.index("/static/company-full-workspace.js"),
            scripts.index("/static/app.js"),
        )

    def test_macro_dashboard_replaces_only_the_two_lower_dashboard_cards(self):
        template = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        stylesheets = re.findall(r'href="(/static/[^"]+\.css)[^"]*"', template)
        scripts = re.findall(r'src="(/static/[^"]+\.js)[^"]*"', template)
        self.assertIn('id="dashboardMacroMount"', template)
        self.assertNotIn('id="marketPerformanceMount"', template)
        self.assertNotIn('id="researchActivityMount"', template)
        self.assertIn('id="quickAccessMount"', template)
        self.assertIn("/static/dashboard-macro.css", stylesheets)
        self.assertGreater(
            stylesheets.index("/static/dashboard-macro.css"),
            stylesheets.index("/static/dashboard-mode-fixes.css"),
        )
        self.assertIn("/static/dashboard-macro.js", scripts)
        self.assertGreater(
            scripts.index("/static/dashboard-macro.js"),
            scripts.index("/static/app.js"),
        )

    def test_macro_dashboard_has_five_responsive_interactive_graphs_and_summary(self):
        css = (ROOT / "static" / "dashboard-macro.css").read_text(encoding="utf-8")
        javascript = (ROOT / "static" / "dashboard-macro.js").read_text(encoding="utf-8")
        self.assertIn("grid-template-columns: repeat(5, minmax(0, 1fr))", css)
        self.assertIn("@media (max-width: 1160px)", css)
        self.assertIn("@media (max-width: 820px)", css)
        self.assertIn("@media (max-width: 620px)", css)
        for key in ("cpi", "fed_rate", "retail_sales", "unemployment", "gasoline"):
            self.assertIn(f'"{key}"', javascript)
        for contract in (
            "macro-chart-tooltip", "macro-chart-peak", "selectedPeak", "comparison.label",
            "Latest movement &amp; selected-period peaks", "ArrowLeft",
            "packaged official snapshot", "snapshot_captured_at", "Refresh retries live data",
            "CURRENT MACRO PLAYBOOK", "Ranked scenarios from the five charts",
            "Scores show evidence fit, not the probability", "macro-scenario-detail", "scenarioEvidenceMarkup",
            "renderScenarioBoard", "What would confirm or weaken it",
            'data-dashboard-macro-action="scenario"',
        ):
            self.assertIn(contract, javascript)
        for selector in (
            ".macro-scenario-board",
            ".macro-scenario-row",
            ".macro-scenario-meter",
            ".macro-scenario-workspace",
            ".macro-scenario-ranking-note",
            ".macro-scenario-detail-grid",
            ".macro-scenario-evidence",
        ):
            self.assertIn(selector, css)
        scenario_handler = javascript.split('if (action === "scenario") {', 1)[1].split("\n    }", 1)[0]
        self.assertIn("renderScenarioBoard();", scenario_handler)
        self.assertNotIn("render();", scenario_handler)
        self.assertNotIn("Math.random", javascript)

    def test_full_research_workspace_matches_the_selected_visual_contract(self):
        css = (ROOT / "static" / "company-full-workspace.css").read_text(encoding="utf-8")
        javascript = (ROOT / "static" / "company-full-workspace.js").read_text(encoding="utf-8")
        for selector in (
            ".full-research-layout",
            ".full-company-rail",
            ".full-tabs",
            ".full-primary-grid",
            ".full-metric-table",
            ".full-chart-column",
            ".full-details-panel",
        ):
            self.assertIn(selector, css)
        for label in (
            "Financial strength",
            "Growth",
            "Profitability",
            "Valuation",
            "Cash flow",
            "Peers",
            "Peer position (P/E vs ROE)",
            "Revenue to Free Cash Flow bridge",
            "Key indicators (detailed)",
        ):
            self.assertIn(label, javascript)
        self.assertIn('grid-template-columns: 225px minmax(0, 1fr)', css)
        self.assertIn('COMPANY OVERVIEW · FULL RESEARCH', javascript)

    def test_full_research_adds_indices_without_inventing_random_values(self):
        javascript = (ROOT / "static" / "company-full-workspace.js").read_text(encoding="utf-8")
        self.assertGreaterEqual(javascript.count("detailItem("), 34)
        self.assertNotIn("Math.random", javascript)
        self.assertIn('return "Unavailable"', javascript)
        self.assertIn("capital_expenditure", javascript)
        self.assertIn("free_cash_flow", javascript)
        self.assertIn("operating_cash_flow", javascript)

    def test_full_research_uses_the_complete_scanned_statement_set(self):
        javascript = (ROOT / "static" / "company-full-workspace.js").read_text(encoding="utf-8")
        for metric in (
            "gross_revenue", "revenue_reductions", "cost_of_goods_sold",
            "operating_profit", "net_income_total", "selling_expense",
            "admin_expense", "current_assets", "current_liabilities",
            "receivables", "ppe", "short_term_debt", "long_term_debt",
        ):
            self.assertIn(f'rawMetric(data, "{metric}")', javascript)
        self.assertIn("scan_coverage", javascript)
        self.assertIn("Scanned line coverage", javascript)

    def test_verified_report_dialog_is_isolated_from_dashboard_css(self):
        css = (ROOT / "static" / "company-full-workspace.css").read_text(encoding="utf-8")
        javascript = (ROOT / "static" / "company-full-workspace.js").read_text(encoding="utf-8")
        for selector in (
            ".evidence-modal-backdrop",
            ".evidence-modal-card",
            ".evidence-modal-grid",
            ".evidence-modal-source",
        ):
            self.assertIn(selector, css)
        self.assertIn("position: fixed !important", css)
        self.assertIn("z-index: 1400 !important", css)
        self.assertIn("showEvidence = showIsolatedEvidence", javascript)
        self.assertIn("sourceBasename", javascript)
        self.assertIn("stopImmediatePropagation", javascript)

    def test_summary_scrolls_and_metrics_claims_the_assistant_space(self):
        css = (ROOT / "static" / "dashboard-mode-fixes.css").read_text(encoding="utf-8")
        self.assertIn('[data-overview-mode="1"] #overviewCompactContent', css)
        self.assertIn("overflow-y: auto !important", css)
        self.assertIn('[data-overview-mode="2"] .overview-company-panel', css)
        self.assertIn("grid-column: 1 / span 2 !important", css)
        self.assertIn('[data-overview-mode="2"] .overview-news-panel', css)
        self.assertIn("grid-column: 3 !important", css)

    def test_account_workspace_layer_loads_last(self):
        for template_name in ("auth.html", "admin_users.html", "account_security.html"):
            template = (ROOT / "templates" / template_name).read_text(encoding="utf-8")
            stylesheets = re.findall(r'href="(/static/[^"]+\.css)[^"]*"', template)
            with self.subTest(template=template_name):
                self.assertEqual(stylesheets[-1], "/static/account-workspace.css")

    def test_accepted_dashboard_assets_and_markup_are_locked(self):
        template = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        dashboard = template[
            template.index('<section id="overview"'):
            template.index('<section id="compare"')
        ]
        expected = {
            "dashboard-fragment": "9e15b88e08c5617f5f5e858de64881414ac5b397e7fd75e28aaf1f975c3f0431",
            "dashboard.css": "443380b0d7b7cc95c65721909aa2d2ae84a5516d91c682f06db50321e66a9511",
            "interface-refresh.css": "200201013b8202c5381cc6be4f39469d34b1c0024d062eaca7c6504c86a50dc1",
            "quant.css": "e0fedb44e74fe99349805720b52ae492d729e764dd6f7df9315d26fc7a33840b",
            "app.js": "a5a144bf546c403246d26502e3362361477327122de892e8a567e0ebaebb964c",
        }
        actual = {"dashboard-fragment": sha256(dashboard.encode()).hexdigest()}
        for filename in ("dashboard.css", "interface-refresh.css", "quant.css", "app.js"):
            actual[filename] = sha256((ROOT / "static" / filename).read_bytes()).hexdigest()
        self.assertEqual(actual, expected)

    def test_company_modes_use_clear_labels_with_original_ids(self):
        template = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        for mode, label in (("1", "Summary"), ("2", "Metrics"), ("3", "Full")):
            pattern = rf'data-mode="{mode}"[^>]*data-action="overview-mode"[^>]*>{label}</button>'
            self.assertRegex(template, pattern)

    def test_dashboard_state_is_present_before_first_javascript_paint(self):
        template = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        self.assertIn('<body data-active-view="overview" data-overview-mode="1">', template)

    def test_company_search_menu_is_anchored_inside_its_form(self):
        template = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        form = re.search(r'<form class="company-search-row".*?</form>', template, re.DOTALL)
        self.assertIsNotNone(form)
        self.assertIn('id="companySearchMenu"', form.group(0))
        self.assertEqual(template.count('id="companySearchMenu"'), 1)

    def test_dashboard_row_is_bounded_and_wrapped_inputs_are_reset(self):
        css = (ROOT / "static" / "interface-refresh.css").read_text(encoding="utf-8")
        self.assertIn("grid-auto-rows: clamp(410px, 47vh, 480px)", css)
        self.assertIn(".overview-news-panel .macro-news-items", css)
        self.assertIn(".company-search-row > .company-search-menu", css)
        self.assertIn('.company-search-field input:not([type="checkbox"])', css)
        self.assertIn('.assistant-composer input:not([type="checkbox"])', css)

    def test_sidebar_header_is_separate_from_its_scroll_region(self):
        template = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        css = (ROOT / "static" / "interface-refresh.css").read_text(encoding="utf-8")
        javascript = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        self.assertEqual(template.count('class="sidebar-fixed-header"'), 1)
        self.assertEqual(template.count('id="sidebarScrollRegion"'), 1)
        self.assertLess(template.index('class="sidebar-fixed-header"'), template.index('id="sidebarScrollRegion"'))
        self.assertLess(template.index('id="sidebarScrollRegion"'), template.index('class="grouped-nav"'))
        self.assertIn("body .sidebar .brand", css)
        self.assertIn("position: static !important", css)
        self.assertIn(".sidebar-scroll-region", css)
        self.assertIn("overflow-y: auto", css)
        self.assertIn("function keepSidebarSelectionVisible", javascript)
        self.assertIn("sidebarScroller.scrollTop=0", javascript)

    def test_compact_controls_and_checkboxes_are_protected(self):
        css = (ROOT / "static" / "interface-refresh.css").read_text(encoding="utf-8")
        self.assertNotRegex(css, r"(?m)^button,\s*$")
        self.assertIn('input[type="checkbox"]', css)
        self.assertIn('input[type="radio"]', css)
        self.assertNotIn("calc(100vw", css)
        self.assertIn("body:not(.sidebar-collapsed) main", css)
        self.assertIn('@media (prefers-reduced-motion: reduce)', css)


if __name__ == "__main__":
    unittest.main()
