(function () {
  "use strict";

  const riskRoot = document.getElementById("tradePlanner");
  const output = document.getElementById("tradingRiskOut");
  if (!riskRoot || !output) return;

  const baseRender = window.renderTradingRisk;
  let requestSequence = 0;
  const methodCopy = {
    "fixed-fractional": {
      title: "Fixed Fractional", eyebrow: "ACTIVE CALCULATION MODE",
      summary: "Limits planned stop loss to a chosen percentage of account equity.",
      best: "Consistent single-trade risk control", needs: "Equity, risk %, entry, and stop",
      caution: "Gaps and slippage can exceed the planned loss."
    },
    "kelly": {
      title: "Capped Kelly", eyebrow: "ADVANCED CALCULATION MODE",
      summary: "Uses evidence-adjusted resolved paths and target payoff, capped at 25% cash allocation.",
      best: "Well-sampled repeatable setups", needs: "At least 40 resolved paths and target R",
      caution: "Disabled when evidence is thin; historical odds may not persist."
    },
    "half-kelly": {
      title: "Half-Kelly", eyebrow: "ADVANCED CALCULATION MODE",
      summary: "Uses half of the positive Kelly fraction, capped at 12.5% cash allocation.",
      best: "Reducing sensitivity to estimation error", needs: "At least 40 resolved paths and target R",
      caution: "Still depends on stable historical win-rate and payoff evidence."
    },
    "r-multiple": {
      title: "R-multiple", eyebrow: "TARGET RULE · NOT POSITION SIZING",
      summary: "Sets the reward target as a multiple of the entry-to-stop distance.",
      best: "Comparing reward with planned risk", needs: "Entry, stop, and target R",
      caution: "It changes the target, not the number of units."
    },
    "volatility-targeting": {
      title: "Volatility Targeting", eyebrow: "PORTFOLIO EXPOSURE OVERLAY",
      summary: "Scales portfolio exposure as observed volatility changes.",
      best: "Portfolio-level exposure control", needs: "Portfolio volatility and exposure constraints",
      caution: "Backward-looking volatility can react late; use Portfolio Risk."
    },
    "risk-parity": {
      title: "Risk Parity", eyebrow: "PORTFOLIO ALLOCATION METHOD",
      summary: "Allocates across several holdings by estimated risk contribution.",
      best: "Multi-holding portfolios", needs: "Volatility, correlations, and holdings",
      caution: "It cannot size a single company by itself."
    }
  };

  function byId(id) {
    return document.getElementById(id);
  }

  function escapeHtml(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (character) {
      return {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[character];
    });
  }

  function numeric(value, digits) {
    if (value == null || value === "") return "Unavailable";
    const number = Number(value);
    return Number.isFinite(number)
      ? number.toLocaleString(undefined, {minimumFractionDigits: digits || 0, maximumFractionDigits: digits || 0})
      : "Unavailable";
  }

  function percent(value, digits) {
    if (value == null || value === "") return "Unavailable";
    const number = Number(value);
    return Number.isFinite(number) ? `${numeric(number, digits == null ? 2 : digits)}%` : "Unavailable";
  }

  function money(value) {
    if (value == null || value === "") return "Unavailable";
    const number = Number(value);
    if (!Number.isFinite(number)) return "Unavailable";
    const absolute = Math.abs(number);
    if (absolute >= 1e12) return `${(number / 1e12).toFixed(3)}T VND`;
    if (absolute >= 1e9) return `${(number / 1e9).toFixed(3)}B VND`;
    if (absolute >= 1e6) return `${(number / 1e6).toFixed(1)}M VND`;
    return `${number.toLocaleString(undefined, {maximumFractionDigits: 0})} VND`;
  }

  function renderMethodDetail(key) {
    const method = methodCopy[key] || methodCopy["fixed-fractional"];
    const mount = byId("riskMethodDetail");
    if (!mount) return;
    const action = key === "risk-parity"
      ? '<button type="button" class="risk-method-action" data-action="view" data-view="portfolio">Open Portfolio Risk →</button>'
      : key === "r-multiple"
        ? '<button type="button" class="risk-method-action" data-method-focus="tradeTargetR">Edit reward target →</button>'
        : key === "volatility-targeting"
          ? '<button type="button" class="risk-method-action" data-action="view" data-view="portfolio">Open Portfolio Risk →</button>'
          : '<button type="button" class="risk-method-action" data-method-recalculate="true">Recalculate with this mode →</button>';
    mount.innerHTML = `<span>${escapeHtml(method.eyebrow)}</span><h4>${escapeHtml(method.title)}</h4><p>${escapeHtml(method.summary)}</p>
      <div class="risk-method-facts"><div><span>Best used for</span><b>${escapeHtml(method.best)}</b></div><div><span>Inputs needed</span><b>${escapeHtml(method.needs)}</b></div><div><span>Main caution</span><b>${escapeHtml(method.caution)}</b></div></div>${action}`;
  }

  function selectActiveMethod(button) {
    const key = button.dataset.sizingMode;
    if (!methodCopy[key]) return;
    riskRoot.querySelectorAll("[data-sizing-mode]").forEach(function (item) {
      const selected = item === button;
      item.classList.toggle("selected", selected);
      item.classList.toggle("active", selected);
      item.setAttribute("aria-checked", String(selected));
      const badge = item.querySelector("em");
      if (badge) badge.textContent = selected ? "Selected" : "Calculates";
    });
    riskRoot.querySelectorAll("[data-risk-reference-method]").forEach(item => item.classList.remove("active"));
    byId("tradeSizingMethod").value = key;
    if (byId("riskActiveMethodName")) byId("riskActiveMethodName").textContent = methodCopy[key].title;
    if (byId("riskActiveMethodDescription")) byId("riskActiveMethodDescription").textContent = methodCopy[key].summary;
    if (byId("tradeRiskPctField")) byId("tradeRiskPctField").hidden = key !== "fixed-fractional";
    renderMethodDetail(key);
    loadTradingRiskWithSizing();
  }

  function methodEvidence(sizing, stopPlan) {
    const common = `<div><span>Applied cash allocation</span><b>${percent(sizing.allocation_pct)}</b></div>
      <div><span>Raw method allocation</span><b>${percent(sizing.raw_allocation_pct)}</b></div>
      <div><span>Planned stop loss</span><b>${percent(sizing.planned_loss_pct_equity)} of equity</b></div>`;
    if (sizing.key === "kelly" || sizing.key === "half-kelly") {
      return `${common}
        <div><span>Evidence-adjusted win rate</span><b>${percent(sizing.evidence_win_probability_pct)}</b></div>
        <div><span>Target payoff</span><b>${numeric(stopPlan.target_r_multiple, 1)}R</b></div>
        <div><span>Raw Kelly fraction</span><b>${percent(sizing.kelly_fraction_pct)}</b></div>
        <div><span>Applied fraction</span><b>${percent(sizing.applied_kelly_fraction_pct)}</b></div>`;
    }
    return `${common}
      <div><span>Requested risk</span><b>${percent(sizing.requested_risk_pct, 2)} of equity</b></div>
      <div><span>Cash cap</span><b>${sizing.cash_cap_applied ? "Applied" : "Not needed"}</b></div>`;
  }

  function renderTradingRiskWithSizing(data) {
    if (typeof baseRender !== "function") {
      return `<section class="risk-trade-result"><div class="risk-plan-warning"><h4>Position result unavailable</h4><p>The base trading-risk renderer could not be loaded.</p></div></section>`;
    }
    const template = document.createElement("template");
    template.innerHTML = baseRender(data).trim();
    const result = template.content.firstElementChild;
    if (!result || data.status !== "ok") return template.innerHTML;

    const sizing = data.position_sizing || {};
    const riskBudget = data.risk_budget || {};
    const stopPlan = data.stop_plan || {};
    result.dataset.sizingMethod = sizing.key || "fixed-fractional";

    const kicker = result.querySelector(".risk-trade-hero-main .feature-kicker");
    if (kicker) kicker.textContent += ` · ${String(sizing.label || "Fixed Fractional").toUpperCase()} SIZE`;

    const sectionHeads = Array.from(result.querySelectorAll(".risk-trade-section-head"));
    const sizingHead = sectionHeads.find(function (head) {
      return /position size/i.test(head.querySelector("h4")?.textContent || "");
    });
    if (sizingHead) {
      const heading = sizingHead.querySelector("h4");
      const description = sizingHead.querySelector("p");
      if (heading) heading.textContent = `${sizing.label || "Selected method"} position size`;
      if (description) description.textContent = sizing.normalized_only
        ? "The allocation percentage is calculated now. Add account equity only if you want currency and unit estimates."
        : "The selected mode changes exposure and unit count; the stop and R target remain shared research inputs.";
    }

    const sizingKpis = result.querySelector(".risk-sizing-kpis");
    if (sizingKpis) {
      const amountHint = sizing.normalized_only ? "add account equity to calculate" : "before fees and slippage";
      sizingKpis.innerHTML = `<article><span>Capital allocation</span><b>${percent(sizing.allocation_pct)}</b><small>${sizing.cash_cap_applied ? "capped at available cash" : "of account equity"}</small></article>
        <article><span>Position units</span><b>${riskBudget.position_units == null ? "Add equity" : `${numeric(riskBudget.position_units, 0)} units`}</b><small>${sizing.normalized_only ? "percentage already calculated" : "exchange-lot rounded"}</small></article>
        <article><span>Position value</span><b>${money(riskBudget.position_value)}</b><small>${amountHint}</small></article>
        <article><span>Planned stop loss</span><b>${riskBudget.risk_amount == null ? percent(sizing.planned_loss_pct_equity) : money(riskBudget.risk_amount)}</b><small>${sizing.normalized_only ? "of normalized equity" : `${percent(sizing.planned_loss_pct_equity)} of equity`}</small></article>`;

      const methodNote = document.createElement("section");
      methodNote.className = `risk-sizing-method-note ${escapeHtml(sizing.status || "ok")}`;
      const capExplanation = sizing.cash_cap_applied
        ? `<p><b>Why applied results can match:</b> this method requested ${percent(sizing.raw_allocation_pct)}, but the cash-only safety cap limited it to 100%. Another method can therefore show the same applied amount even when its raw result is different.</p>`
        : "";
      methodNote.innerHTML = `<div class="risk-sizing-method-copy"><span>CALCULATED WITH</span><h4>${escapeHtml(sizing.label || "Selected method")}</h4><p>${escapeHtml(sizing.methodology || "Sizing methodology unavailable.")}</p>${capExplanation}<small>${escapeHtml(sizing.limitation || "")}</small></div>
        <div class="risk-sizing-method-evidence">${methodEvidence(sizing, stopPlan)}</div>`;
      sizingKpis.insertAdjacentElement("afterend", methodNote);
    }
    return template.innerHTML;
  }

  async function requestJson(url) {
    const response = await fetch(url, {
      credentials: "same-origin",
      headers: {Accept: "application/json"},
      cache: "no-store",
    });
    const data = await response.json().catch(function () { return {}; });
    if (!response.ok) throw new Error(data.error || data.status || `Request failed (${response.status})`);
    return data;
  }

  async function loadTradingRiskWithSizing() {
    const company = (byId("tradeCompany")?.value || byId("riskCompany")?.value || "").trim().toUpperCase();
    if (!company) return;
    const query = new URLSearchParams();
    const entry = byId("tradeEntry")?.value;
    const equity = byId("tradeEquity")?.value;
    if (entry) query.set("entry", entry);
    if (equity) query.set("equity", equity);
    query.set("risk_pct", byId("tradeRiskPct")?.value || "1");
    query.set("target_r", byId("tradeTargetR")?.value || "2");
    query.set("horizon", byId("tradeHorizon")?.value || "20");
    query.set("side", byId("tradeSide")?.value || "long");
    const requestedMethod = byId("tradeSizingMethod")?.value || "fixed-fractional";
    query.set("sizing_method", requestedMethod);

    const selectedName = byId("riskActiveMethodName")?.textContent || "selected method";
    output.innerHTML = `<section class="risk-empty-state compact"><span>CALCULATING ${escapeHtml(selectedName.toUpperCase())}</span><h3>Testing stop, target, and position size…</h3><p>Comparing historical paths, then applying the selected exposure formula.</p></section>`;
    const sequence = ++requestSequence;
    try {
      const data = await requestJson(`/api/risk/trading/${encodeURIComponent(company)}?${query.toString()}`);
      if (sequence !== requestSequence) return;
      const returnedMethod = data.position_sizing?.key;
      if (data.status === "ok" && returnedMethod !== requestedMethod) {
        throw new Error(`The server returned ${returnedMethod || "no sizing method"} instead of ${requestedMethod}. Please recalculate.`);
      }
      output.innerHTML = renderTradingRiskWithSizing(data);
      output.dataset.hasSizingResult = data.status === "ok" ? "true" : "false";
      output.dataset.sizingMethod = returnedMethod || "";
    } catch (error) {
      if (sequence !== requestSequence) return;
      output.dataset.hasSizingResult = "false";
      output.innerHTML = `<section class="risk-trade-result"><div class="risk-plan-warning"><h4>Trading-risk plan unavailable</h4><p>${escapeHtml(error.message)}</p></div></section>`;
    }
  }

  window.SolvAIControllers = window.SolvAIControllers || Object.create(null);
  window.SolvAIControllers.tradePlanner = Object.freeze({
    load: loadTradingRiskWithSizing,
    render: renderTradingRiskWithSizing,
  });

  // Own the calculate action before the legacy document-level action router.
  // This prevents the older request (which has no sizing_method parameter)
  // from replacing the method-aware result.
  riskRoot.addEventListener("click", function (event) {
    const methodButton = event.target.closest?.("[data-sizing-mode]");
    if (methodButton) {
      event.preventDefault();
      selectActiveMethod(methodButton);
      return;
    }
    const referenceButton = event.target.closest?.("[data-risk-reference-method]");
    if (referenceButton) {
      riskRoot.querySelectorAll("[data-risk-reference-method]").forEach(item => item.classList.toggle("active", item === referenceButton));
      renderMethodDetail(referenceButton.dataset.riskReferenceMethod);
      return;
    }
    const focusButton = event.target.closest?.("[data-method-focus]");
    if (focusButton) {
      byId(focusButton.dataset.methodFocus)?.focus();
      return;
    }
    if (event.target.closest?.("[data-method-recalculate]")) {
      loadTradingRiskWithSizing();
      return;
    }
    const infoTip = event.target.closest?.(".risk-info-tip");
    if (infoTip) {
      event.preventDefault();
      const open = !infoTip.classList.contains("is-open");
      riskRoot.querySelectorAll(".risk-info-tip.is-open").forEach(item => item.classList.remove("is-open"));
      infoTip.classList.toggle("is-open", open);
      return;
    }
    const calculateButton = event.target.closest?.('[data-action="trading-risk"]');
    if (!calculateButton) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    loadTradingRiskWithSizing();
  }, true);

  renderMethodDetail("fixed-fractional");
})();
