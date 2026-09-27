(function () {
  "use strict";
  if (!document.getElementById("valuationPanel")) return;

  const baseRenderValuation = renderValuation;

  function holdingInputs() {
    return {
      shares_held: $("valuationSharesHeld")?.value,
      average_cost_per_share: $("valuationAverageCost")?.value,
      horizon_years: $("valuationHoldingYears")?.value || 5,
      reinvest_dividends: Boolean($("valuationReinvestDividends")?.checked)
    };
  }

  function inputValue(row, currency) {
    if (row?.value == null || !Number.isFinite(Number(row.value))) return "Unavailable";
    const unit = String(row.unit || "");
    if (unit.includes("/share") || unit === currency) return valuationMoney(row.value, currency);
    if (unit === "%") return pct(row.value);
    if (unit === "shares") return Number(row.value).toLocaleString(undefined, {maximumFractionDigits: 0});
    return `${num(row.value, 2)}${unit ? ` ${esc(unit)}` : ""}`;
  }

  function renderAutomaticInputs(data) {
    const automatic = data.automatic_inputs || {};
    const rows = automatic.rows || data.source_evidence || [];
    return `<section class="valuation-auto-evidence">
      <div class="valuation-auto-evidence-head"><div><div class="assistant-kicker">AUTOMATIC DATA CHECK</div><h3>The model filled ${num(automatic.available_count ?? rows.filter(row => row.value != null).length, 0)} of ${num(automatic.total_count ?? rows.length, 0)} core inputs</h3><p>${esc(automatic.message || "Technical company inputs were resolved from available evidence.")}</p></div><span class="valuation-auto-score">${automatic.manual_count ? `${num(automatic.manual_count, 0)} override${automatic.manual_count === 1 ? "" : "s"}` : "No manual data needed"}</span></div>
      <div class="valuation-auto-grid">${rows.map(row => `<article class="valuation-auto-item ${esc(row.status || (row.value == null ? "unavailable" : "automatic"))}"><span>${esc(row.field)}</span><b>${inputValue(row, data.currency || "VND")}</b><small>${esc(row.value == null ? "No verified value returned" : row.source || "Automatic evidence")}</small></article>`).join("")}</div>
    </section>`;
  }

  function chartMarkup(outlook) {
    const rows = outlook.scenarios || [];
    const horizon = Number(outlook.horizon_years || 5);
    const series = rows.map(row => ({key: row.key, values: [Number(outlook.current_price), ...(row.path || []).map(point => Number(point.modeled_price))]}));
    const values = series.flatMap(row => row.values).filter(Number.isFinite);
    if (values.length < 4) return "";
    const width = 760, height = 155, pad = 12;
    const min = Math.min(...values), max = Math.max(...values), span = max - min || 1;
    const points = valuesFor => valuesFor.map((value, index) => `${(pad + index / horizon * (width - pad * 2)).toFixed(1)},${(height - pad - (value - min) / span * (height - pad * 2)).toFixed(1)}`).join(" ");
    return `<div class="valuation-long-chart"><div class="valuation-long-legend"><span><i class="bear"></i>Bear</span><span><i class="base"></i>Base</span><span><i class="bull"></i>Bull</span></div><svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" aria-label="Modeled Bear, Base, and Bull price paths"><line class="grid" x1="${pad}" y1="${height / 2}" x2="${width - pad}" y2="${height / 2}"></line>${series.map(row => `<polyline class="${esc(row.key)}" points="${points(row.values)}"></polyline><circle class="${esc(row.key)}" cx="${width - pad}" cy="${(height - pad - (row.values.at(-1) - min) / span * (height - pad * 2)).toFixed(1)}" r="4"></circle>`).join("")}</svg><div class="valuation-long-axis"><span>Today · ${valuationMoney(outlook.current_price, outlook.currency)}</span><span>Year ${horizon}</span></div></div>`;
  }

  function renderLongHoldingOutlook(data) {
    const outlook = data.long_holding_outlook || {};
    if (outlook.status !== "available") return `<section class="valuation-long-outlook"><div class="valuation-long-head"><div><div class="assistant-kicker">LONG-HOLDING OUTLOOK</div><h3>Holding scenarios unavailable</h3><p>${esc(outlook.reason || "More verified market and company evidence is required.")}</p></div></div></section>`;
    const weighted = outlook.weighted || {}, holding = outlook.user_inputs || {}, growth = outlook.growth_model || {};
    const hasHolding = holding.shares_held != null;
    return `<section class="valuation-long-outlook">
      <div class="valuation-long-head"><div><div class="assistant-kicker">${num(outlook.horizon_years, 0)}-YEAR LONG-HOLDING OUTLOOK</div><h3>What the holding could look like if the evidence persists</h3><p>Growth fades toward a stable rate each year; EPS, free cash flow, dividends, and terminal valuation are modeled separately.</p></div><div class="valuation-long-highlight"><span>${hasHolding ? "Weighted modeled holding" : "Weighted modeled value / share"}</span><b>${valuationMoney(hasHolding ? weighted.portfolio_value : weighted.terminal_wealth_per_starting_share, outlook.currency)}</b><small>${pct(weighted.annualized_return_pct)} annualized · scenario weighted</small></div></div>
      ${chartMarkup(outlook)}
      <div class="valuation-long-scenarios">${(outlook.scenarios || []).map(row => `<article class="valuation-long-scenario ${esc(row.key)}"><div><div><span>${esc(row.label)} · ${pct(row.research_weight_pct)}</span><h4>${pct(row.annualized_return_pct)} annualized</h4></div><span>${pct(row.total_return_pct)} total</span></div><strong>${valuationMoney(hasHolding ? row.portfolio_value : row.terminal_wealth_per_starting_share, outlook.currency)}</strong><small>${hasHolding ? `${num(holding.shares_held, 0)} starting shares` : "modeled wealth per starting share"}${holding.reinvest_dividends ? " · dividends reinvested" : " · cash dividends included"}</small><dl><div><dt>Year ${num(outlook.horizon_years, 0)} price</dt><dd>${valuationMoney(row.terminal_price_per_share, outlook.currency)}</dd></div><div><dt>Starting growth</dt><dd>${pct(row.starting_growth_pct)}</dd></div>${row.gain_on_cost_pct == null ? "" : `<div><dt>Vs. your cost</dt><dd>${pct(row.gain_on_cost_pct)}</dd></div>`}<div><dt>Ending growth</dt><dd>${pct(row.stable_growth_pct)}</dd></div></dl></article>`).join("")}</div>
      <div class="valuation-growth-evidence"><div><span>Normalized starting growth</span><b>${pct(growth.base_growth_pct)}</b><small>${num(growth.evidence_strength_pct, 0)}% evidence strength; fades toward ${pct(growth.stable_growth_pct)}</small></div><div class="valuation-growth-tags">${(growth.evidence || []).map(row => `<span>${esc(row.label)} · ${pct(row.normalized_pct)}</span>`).join("")}</div></div>
      <div class="valuation-long-warning">${esc(outlook.warning || "Scenario estimates are not guaranteed outcomes.")}</div>
    </section>`;
  }

  const enhancedRenderValuation = function (data) {
    const markup = baseRenderValuation(data);
    const addition = `${renderAutomaticInputs(data)}${renderLongHoldingOutlook(data)}`;
    const marker = '<section class="valuation-risk-reward">';
    return markup.includes(marker) ? markup.replace(marker, `${addition}${marker}`) : `${markup}${addition}`;
  };

  const loadValuationWorkspace = async function (companyOverride = null) {
    const company = String(companyOverride || $("valuationCompany")?.value || "").trim().toUpperCase();
    if (!company) return;
    if ($("valuationCompany")) $("valuationCompany").value = company;
    const out = $("valuationOut");
    if (out) out.innerHTML = '<div class="valuation-loading"><span></span><div><b>Building the long-holding outlook</b><small>Resolving company inputs, normalizing growth, and testing Bear, Base, and Bull paths…</small></div></div>';
    try {
      const data = await getJSON(`/api/valuation/${encodeURIComponent(company)}`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          assumptions: valuationAssumptions(),
          inputs: valuationInputs(),
          drivers: valuationDrivers(),
          holding: holdingInputs()
        }),
        cancelKey: "company-valuation",
        dedupe: false
      });
      valuationCache = data;
      if (out) out.innerHTML = enhancedRenderValuation(data);
      $("risk")?.dispatchEvent(new CustomEvent("risk:valuation-ready"));
      document.querySelectorAll(".overview-core-value-mount").forEach(mount => mount.innerHTML = renderOverviewValuation(data));
      loadAlertSummary();
    } catch (error) {
      if (error?.name !== "AbortError" && out) out.innerHTML = `<div class="notice bad">${esc(error.message)}</div>`;
    }
  };

  window.SolvAIControllers = window.SolvAIControllers || Object.create(null);
  window.SolvAIControllers.valuation = Object.freeze({
    load: loadValuationWorkspace,
    render: enhancedRenderValuation,
  });
})();
