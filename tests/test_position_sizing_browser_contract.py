import json
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("node"), "Node.js is required for the browser event contract")
class PositionSizingBrowserContractTests(unittest.TestCase):
    def test_method_change_and_calculate_click_use_method_aware_loader(self):
        source = (ROOT / "static" / "position-sizing-workspace.js").read_text(encoding="utf-8")
        script = f"""
const source = {json.dumps(source)};
class FakeElement {{
  constructor(value = "") {{
    this.value = value;
    this.textContent = value;
    this.innerHTML = "";
    this.dataset = {{}};
    this.listeners = {{}};
    this.classList = {{toggle: () => {{}}, contains: () => false, remove: () => {{}}}};
  }}
  addEventListener(type, handler, options) {{
    (this.listeners[type] ||= []).push({{handler, options}});
  }}
  querySelectorAll() {{ return []; }}
  querySelector() {{ return null; }}
  setAttribute() {{}}
  focus() {{}}
}}
const root = new FakeElement();
const output = new FakeElement();
const fields = {{
  tradePlanner: root,
  tradingRiskOut: output,
  tradeCompany: new FakeElement("FPT"),
  riskCompany: new FakeElement("FPT"),
  tradeEntry: new FakeElement("100"),
  tradeEquity: new FakeElement(""),
  tradeRiskPct: new FakeElement("1"),
  tradeTargetR: new FakeElement("2"),
  tradeHorizon: new FakeElement("30"),
  tradeSide: new FakeElement("long"),
  tradeSizingMethod: new FakeElement("half-kelly"),
  tradeVolTarget: new FakeElement("15"),
  riskActiveMethodName: new FakeElement("Half-Kelly"),
}};
global.window = {{renderTradingRisk: () => ""}};
global.document = {{
  getElementById: (id) => fields[id] || null,
  createElement: () => {{ throw new Error("rendering should not occur in this request-path test"); }},
}};
const requests = [];
global.fetch = (url, options) => {{
  requests.push({{url: String(url), options}});
  return new Promise(() => {{}});
}};
eval(source);

const click = root.listeners.click?.find((listener) => listener.options === true);
if (!click) throw new Error("missing capture-phase planner listener");
const methodButton = new FakeElement();
methodButton.dataset.sizingMode = "half-kelly";
click.handler({{
  target: {{closest: (selector) => selector === "[data-sizing-mode]" ? methodButton : null}},
  preventDefault: () => {{}},
  stopImmediatePropagation: () => {{}},
}});
if (!requests[0]?.url.includes("sizing_method=half-kelly")) throw new Error("method change did not request half-kelly");
if (requests[0]?.options?.cache !== "no-store") throw new Error("method request can be served from cache");

fields.tradeSizingMethod.value = "kelly";
let prevented = false;
let stopped = false;
click.handler({{
  target: {{closest: (selector) => selector.includes("trading-risk") ? {{}} : null}},
  preventDefault: () => {{ prevented = true; }},
  stopImmediatePropagation: () => {{ stopped = true; }},
}});
if (!prevented || !stopped) throw new Error("legacy calculate handler was not intercepted");
if (!requests[1]?.url.includes("sizing_method=kelly")) throw new Error("calculate click did not request Kelly");
if (!global.window.SolvAIControllers?.tradePlanner) throw new Error("trade planner controller was not registered");
"""
        completed = subprocess.run(
            [shutil.which("node"), "-e", script],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)


if __name__ == "__main__":
    unittest.main()
