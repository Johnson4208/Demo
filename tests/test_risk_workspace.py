import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RiskWorkspaceRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        cls.css = (ROOT / "static" / "risk-workspace.css").read_text(encoding="utf-8")
        cls.app = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        cls.workspace = (ROOT / "static" / "risk-workspace.js").read_text(encoding="utf-8")
        cls.sizing = (ROOT / "static" / "position-sizing-workspace.js").read_text(encoding="utf-8")
        cls.sizing_css = (ROOT / "static" / "position-sizing-workspace.css").read_text(encoding="utf-8")

    def test_risk_assets_load_after_shared_layers_and_application_script(self):
        stylesheets = re.findall(r'href="(/static/[^"]+\.css)[^"]*"', self.template)
        scripts = re.findall(r'src="(/static/[^"]+\.js)[^"]*"', self.template)
        self.assertGreater(
            stylesheets.index("/static/risk-workspace.css"),
            stylesheets.index("/static/feature-workspace.css"),
        )
        self.assertGreater(
            scripts.index("/static/risk-workspace.js"),
            scripts.index("/static/app.js"),
        )

    def test_investment_research_and_trade_planner_are_separate_journeys(self):
        for section_id in ("riskAssessmentPanel", "valuationPanel", "tradePlannerPanel"):
            self.assertIn(f'id="{section_id}"', self.template)
        for element_id in (
            "riskCompany", "riskOut", "valuationCompany", "valuationOut",
            "tradeCompany", "tradeEntry", "tradeEquity", "tradeRiskPct",
            "tradeTargetR", "tradeHorizon", "tradeSide", "tradingRiskOut",
        ):
            self.assertEqual(self.template.count(f'id="{element_id}"'), 1, element_id)
        for action in ("risk", "valuation", "trading-risk"):
            self.assertIn(f'data-action="{action}"', self.template)
        research = self.template[self.template.index('<section id="risk"'):self.template.index('<section id="tradePlanner"')]
        trade = self.template[self.template.index('<section id="tradePlanner"'):self.template.index('<section id="macro"')]
        self.assertIn('id="valuationPanel"', research)
        self.assertNotIn('id="tradePlannerPanel"', research)
        self.assertIn('id="tradePlannerPanel"', trade)

    def test_three_active_modes_and_three_related_frameworks_are_separate(self):
        for method in (
            "Fixed Fractional", "R-multiple", "Kelly Criterion",
            "Half-Kelly / Fractional Kelly", "Volatility Targeting", "Risk Parity",
        ):
            self.assertIn(method, self.template + self.workspace)
        for method in ("fixed-fractional", "kelly", "half-kelly"):
            self.assertIn(f'data-sizing-mode="{method}"', self.template)
        self.assertNotIn('data-sizing-mode="volatility-targeting"', self.template)
        self.assertIn('id="tradeSizingMethod"', self.template)
        self.assertNotIn('id="tradeVolTarget"', self.template)
        self.assertIn("TARGET RULE · NOT POSITION SIZING", self.sizing)
        self.assertIn("RELATED FRAMEWORKS · DO NOT REPLACE THE ACTIVE MODE", self.template)
        self.assertNotIn("Math.random", self.sizing)
        self.assertGreater(
            self.template.index('risk-method-library-disclosure'),
            self.template.index('id="tradePlannerPanel"'),
        )
        self.assertIn("Choose position-sizing mode", self.template)

    def test_method_selection_is_forwarded_and_always_recalculates(self):
        self.assertIn('query.set("sizing_method"', self.sizing)
        self.assertNotIn('query.set("target_volatility"', self.sizing)
        self.assertIn('event.target.closest?.("[data-sizing-mode]")', self.sizing)
        self.assertNotIn('output.dataset.hasSizingResult === "true"', self.sizing)
        self.assertIn('loadTradingRiskWithSizing()', self.sizing)
        self.assertIn('event.stopImmediatePropagation()', self.sizing)
        self.assertIn('cache: "no-store"', self.sizing)
        self.assertIn('if (value == null || value === "") return "Unavailable";', self.sizing)
        self.assertIn("CALCULATED WITH", self.sizing)
        self.assertIn("risk-sizing-method-note", self.sizing + self.sizing_css)

    def test_information_controls_work_on_hover_focus_click_and_touch(self):
        self.assertGreaterEqual(self.template.count('class="risk-info-tip'), 12)
        self.assertIn('data-tooltip=', self.template)
        self.assertIn('tabindex="0"', self.template)
        self.assertIn(".risk-info-tip:hover::after", self.css)
        self.assertIn(".risk-info-tip:focus-visible::after", self.css)
        self.assertIn(".risk-info-tip.is-open::after", self.css)
        self.assertIn("function riskInfoTip", self.app)
        self.assertIn('role="button" aria-expanded="false"', self.app)
        self.assertIn("toggleInfoTip", self.workspace)
        self.assertIn('event.key === "Enter" || event.key === " "', self.workspace)
        self.assertIn("riskMetricLabel('M-score'", self.app)
        self.assertIn("riskMetricLabel('M-score','A weighted combination of eight accounting indices. Higher values warrant more investigation; the score is not an audit conclusion.',true)", self.app)
        self.assertIn("riskMetricLabel('ATR14'", self.app)

    def test_component_tooltips_avoid_the_table_heading_and_screening_copy_agrees(self):
        self.assertIn("side:true", self.app)
        self.assertIn(".risk-info-tip-side::after", self.css)
        self.assertIn("M-score review threshold crossed", self.app)
        self.assertIn("No additional leverage, revenue-growth, or net-margin rule was triggered", self.app)
        self.assertNotIn("No major rule-based warning triggered", self.app)

    def test_live_results_use_the_new_financial_and_trade_structures(self):
        for contract in (
            "risk-financial-result", "risk-decision-hero", "risk-summary-meta",
            "risk-priority-grid", "risk-evidence-disclosure", "risk-evidence-grid",
            "risk-component-table", "risk-change-list", "risk-model-note",
            "risk-trade-result", "risk-trade-hero", "risk-trade-metrics",
            "risk-sizing-kpis", "risk-reference-card", "risk-plan-warning",
        ):
            self.assertIn(contract, self.app)
            self.assertIn(f".{contract}", self.css)
        self.assertIn("rb.per_unit_risk", self.app)
        self.assertIn("hold.resolved_rate", self.app)

    def test_overview_is_decision_first_and_detailed_evidence_starts_collapsed(self):
        self.assertIn('data-risk-target="riskEvidenceDetails"', self.app)
        self.assertIn('data-risk-step-go="2"', self.app)
        self.assertNotIn('data-risk-step-go="3"', self.app)
        self.assertIn('id="riskEvidenceDetails" class="risk-evidence-disclosure"', self.app)
        self.assertNotIn('<details open id="riskEvidenceDetails"', self.app)
        self.assertIn("What matters most", self.app)
        self.assertIn("The three largest visible drivers", self.app)
        self.assertIn("Relative screen signal", self.app)
        self.assertIn("if (target.tagName === \"DETAILS\") target.open = true", self.workspace)

    def test_progressive_workflow_shows_only_the_current_unlocked_step(self):
        self.assertEqual(self.template.count('data-risk-step-tab='), 2)
        self.assertEqual(self.template.count('data-risk-step-panel="1"'), 2)
        self.assertIn('data-risk-step-panel="2" hidden', self.template)
        self.assertNotIn('data-risk-step-panel="3"', self.template)
        for contract in (
            "currentStep", "highestUnlockedStep", "setStep",
            "resetProgress", "risk:review-ready",
            "risk:opened", 'aria-current", "step"',
        ):
            self.assertIn(contract, self.workspace)
        self.assertIn('[data-risk-step-panel][hidden]', self.css)
        self.assertIn('button[data-state="active"]', self.css)
        self.assertIn('button[data-state="complete"]', self.css)
        self.assertIn('button[data-state="locked"]', self.css)
        self.assertNotIn("loadValuation(company);", self.app.split("async function loadRisk()", 1)[1].split("let valuationCache", 1)[0])

    def test_responsive_and_reduced_motion_rules_remain_available(self):
        for breakpoint in ("@media (max-width: 1120px)", "@media (max-width: 900px)", "@media (max-width: 620px)"):
            self.assertIn(breakpoint, self.css)
        self.assertIn("@media (prefers-reduced-motion: reduce)", self.css)


if __name__ == "__main__":
    unittest.main()
