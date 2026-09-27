(function () {
  "use strict";

  const mount = document.getElementById("dashboardMacroMount");
  if (!mount) return;

  const SERIES_ORDER = ["cpi", "fed_rate", "retail_sales", "unemployment", "gasoline"];
  const RANGE_MONTHS = {"12m": 12, "24m": 24, "5y": 60};
  const state = {
    range: "24m",
    data: null,
    inFlight: null,
    timer: null,
    chartModels: {},
    scenarioKey: null,
  };
  window.SolvAIDashboardMacro = state;

  function html(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (character) {
      return {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[character];
    });
  }

  function safeUrl(value) {
    try {
      const url = new URL(String(value || ""), window.location.origin);
      return ["http:", "https:"].includes(url.protocol) ? url.href : "#";
    } catch (_error) {
      return "#";
    }
  }

  function asDate(value) {
    if (!value) return null;
    const date = new Date(String(value).length === 10 ? `${value}T00:00:00Z` : value);
    return Number.isNaN(date.getTime()) ? null : date;
  }

  function dateLabel(value, short) {
    const date = asDate(value);
    if (!date) return "Date unavailable";
    return new Intl.DateTimeFormat("en-US", short
      ? {month: "short", year: "numeric", timeZone: "UTC"}
      : {month: "short", day: "numeric", year: "numeric", timeZone: "UTC"}
    ).format(date);
  }

  function finite(value) {
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
  }

  function formatValue(item, value) {
    const number = finite(value);
    if (number == null) return "Unavailable";
    const decimals = Math.max(0, Number(item.decimals || 0));
    if (item.key === "gasoline") return `$${number.toFixed(decimals)}`;
    if (item.key === "fed_rate" || item.key === "unemployment") return `${number.toFixed(decimals)}%`;
    return number.toLocaleString("en-US", {minimumFractionDigits: decimals, maximumFractionDigits: decimals});
  }

  function formatDelta(item, value) {
    const number = finite(value);
    if (number == null) return "no comparison";
    const sign = number > 0 ? "+" : "";
    if (item.key === "gasoline") return `${sign}$${number.toFixed(3)}`;
    if (item.key === "fed_rate" || item.key === "unemployment") return `${sign}${number.toFixed(2)} pp`;
    return `${sign}${number.toFixed(1)}`;
  }

  function rangePoints(item) {
    const all = (Array.isArray(item && item.points) ? item.points : [])
      .map(function (point) { return {date: point.date, value: finite(point.value)}; })
      .filter(function (point) { return point.value != null && asDate(point.date); });
    if (!all.length) return [];
    const months = RANGE_MONTHS[state.range] || 24;
    const latestDate = asDate(all[all.length - 1].date);
    const cutoff = new Date(latestDate.getTime());
    cutoff.setUTCMonth(cutoff.getUTCMonth() - months);
    const selected = all.filter(function (point) { return asDate(point.date) >= cutoff; });
    return selected.length >= 2 ? selected : all.slice(-2);
  }

  function selectedPeak(item) {
    const points = rangePoints(item);
    if (!points.length) return null;
    return points.reduce(function (best, point) {
      return point.value > best.value ? point : best;
    }, points[0]);
  }

  function chartModel(item) {
    const points = rangePoints(item);
    if (points.length < 2) return null;
    const values = points.map(function (point) { return point.value; });
    let minimum = Math.min.apply(null, values);
    let maximum = Math.max.apply(null, values);
    const rawSpan = maximum - minimum;
    const padding = rawSpan > 0 ? rawSpan * .12 : Math.max(Math.abs(maximum) * .02, .5);
    minimum -= padding;
    maximum += padding;
    const left = 5;
    const right = 235;
    const top = 9;
    const bottom = 67;
    const span = maximum - minimum || 1;
    const coordinates = points.map(function (point, index) {
      const x = left + (index / (points.length - 1)) * (right - left);
      const y = bottom - ((point.value - minimum) / span) * (bottom - top);
      return {x: x, y: y, date: point.date, value: point.value};
    });
    const peakIndex = values.indexOf(Math.max.apply(null, values));
    return {points: points, coordinates: coordinates, peakIndex: peakIndex, left: left, right: right, top: top, bottom: bottom};
  }

  function chartMarkup(item) {
    const model = chartModel(item);
    if (!model) return '<div class="macro-card-empty">Not enough published observations to draw this period.</div>';
    state.chartModels[item.key] = model;
    const linePath = model.coordinates.map(function (point, index) {
      return `${index ? "L" : "M"}${point.x.toFixed(2)},${point.y.toFixed(2)}`;
    }).join(" ");
    const first = model.coordinates[0];
    const last = model.coordinates[model.coordinates.length - 1];
    const peak = model.coordinates[model.peakIndex];
    const areaPath = `${linePath} L${last.x.toFixed(2)},${model.bottom} L${first.x.toFixed(2)},${model.bottom} Z`;
    const peakAnchor = peak.x < 35 ? "start" : peak.x > 205 ? "end" : "middle";
    const peakX = peak.x < 35 ? peak.x + 3 : peak.x > 205 ? peak.x - 3 : peak.x;
    return `<div class="macro-chart-stage" data-macro-chart="${html(item.key)}" tabindex="0" role="group" aria-label="${html(item.label)} chart. Use the left and right arrow keys to inspect published values.">
      <svg class="macro-mini-chart" viewBox="0 0 240 82" preserveAspectRatio="none" role="img" aria-label="${html(item.label)} from ${html(dateLabel(first.date, true))} to ${html(dateLabel(last.date, true))}">
        <line class="macro-chart-grid" x1="5" y1="20" x2="235" y2="20"></line>
        <line class="macro-chart-grid" x1="5" y1="39" x2="235" y2="39"></line>
        <line class="macro-chart-grid" x1="5" y1="58" x2="235" y2="58"></line>
        <path class="macro-chart-area" d="${areaPath}"></path>
        <path class="macro-chart-line" d="${linePath}"></path>
        <circle class="macro-chart-peak" cx="${peak.x.toFixed(2)}" cy="${peak.y.toFixed(2)}" r="2.6"></circle>
        <text class="macro-chart-peak-label" x="${peakX.toFixed(2)}" y="${Math.max(7, peak.y - 4).toFixed(2)}" text-anchor="${peakAnchor}">Peak</text>
        <circle class="macro-chart-current" cx="${last.x.toFixed(2)}" cy="${last.y.toFixed(2)}" r="2.8"></circle>
        <line class="macro-chart-cursor" x1="0" y1="7" x2="0" y2="68"></line>
        <circle class="macro-chart-hover-point" cx="0" cy="0" r="3"></circle>
        <text class="macro-chart-label" x="5" y="79">${html(dateLabel(first.date, true))}</text>
        <text class="macro-chart-label" x="235" y="79" text-anchor="end">${html(dateLabel(last.date, true))}</text>
      </svg>
      <div class="macro-chart-tooltip" hidden></div>
    </div>`;
  }

  function changeChip(item) {
    const comparison = item.comparison || {};
    const direction = ["up", "down", "flat"].includes(comparison.direction) ? comparison.direction : "flat";
    const arrow = direction === "up" ? "↑" : direction === "down" ? "↓" : "→";
    return `<span class="macro-change-chip ${direction}" title="Compared with the immediately previous published observation">${arrow} ${html(formatDelta(item, comparison.absolute))}</span>`;
  }

  function cardMarkup(item) {
    const url = html(safeUrl(item.url));
    if (!item.success) {
      return `<article class="macro-signal-card unavailable">
        <div class="macro-signal-head"><div><h4>${html(item.label)}</h4><small>${html(item.frequency || "Official release")}</small></div><a class="macro-series-source" href="${url}" target="_blank" rel="noopener noreferrer">FRED ↗</a></div>
        <div class="macro-card-empty">This official series is temporarily unavailable. No substitute value has been inserted.</div>
        <div class="macro-signal-foot"><span>${html(item.source_agency || "Official source")}</span><b>Unavailable</b></div>
      </article>`;
    }
    const latest = item.latest || {};
    const peak = selectedPeak(item);
    const releaseMode = item.stale_fallback ? "Official snapshot" : "Live official release";
    return `<article class="macro-signal-card" data-source-mode="${item.stale_fallback ? "snapshot" : "live"}">
      <div class="macro-signal-head"><div><h4>${html(item.label)}</h4><small title="${html(item.provider_note || "")}">${html(releaseMode)} · ${html(item.frequency || "Official release")}</small></div><a class="macro-series-source" href="${url}" target="_blank" rel="noopener noreferrer">FRED ↗</a></div>
      <div class="macro-signal-value-row"><div class="macro-signal-value"><strong>${html(formatValue(item, latest.value))}</strong><span>${html(item.unit || "Published value")}</span></div>${changeChip(item)}</div>
      ${chartMarkup(item)}
      <div class="macro-signal-foot"><span>${item.stale_fallback ? "Snapshot" : "Latest"} · ${html(dateLabel(latest.date, false))}</span><b>${peak ? `Peak ${html(formatValue(item, peak.value))}` : "Peak unavailable"}</b></div>
    </article>`;
  }

  function summaryCell(item) {
    if (!item || !item.success) {
      return `<div class="macro-summary-cell"><span>${html(item ? item.short_label : "Series")}</span><b>Comparison unavailable</b><small>Peak unavailable</small></div>`;
    }
    const comparison = item.comparison || {};
    const direction = ["up", "down", "flat"].includes(comparison.direction) ? comparison.direction : "flat";
    const peak = selectedPeak(item);
    return `<div class="macro-summary-cell">
      <span>${html(item.short_label || item.label)}</span>
      <b class="${direction}">${html(comparison.label || "Prior unavailable")} · ${html(formatDelta(item, comparison.absolute))}</b>
      <small>${peak ? `Peak ${html(formatValue(item, peak.value))} · ${html(dateLabel(peak.date, true))}` : "Selected-period peak unavailable"}</small>
    </div>`;
  }

  function warningMarkup(outlook) {
    const warnings = Array.isArray(outlook.warnings) ? outlook.warnings : [];
    const rows = warnings.length ? warnings.slice(0, 3) : ["No fixed-threshold warning is currently triggered by the available observations."];
    return `<div class="macro-warning-list" aria-label="Macro warnings">${rows.map(function (warning) {
      return `<span title="${html(warning)}">${html(warning)}</span>`;
    }).join("")}</div>`;
  }

  function firstSentence(value) {
    const copy = String(value || "Scenario consequence unavailable.").trim();
    const match = copy.match(/^.*?[.!?](?:\s|$)/);
    return match ? match[0].trim() : copy;
  }

  function signalMeter(scenario) {
    const score = Math.max(0, Math.min(5, finite(scenario && scenario.signal_score) || 0));
    const segments = Array.from({length: 5}, function (_unused, index) {
      const threshold = index + 1;
      const fill = score >= threshold ? "full" : score >= threshold - .5 ? "half" : "empty";
      return `<i class="${fill}" aria-hidden="true"></i>`;
    }).join("");
    return `<span class="macro-scenario-meter" role="img" aria-label="${html(score.toFixed(1))} out of 5 signal strength">${segments}</span>`;
  }

  function scenarioEvidenceMarkup(scenario) {
    const evidence = Array.isArray(scenario && scenario.evidence) ? scenario.evidence : [];
    const stanceLabels = {supporting: "Supports", partial: "Partial", contrary: "Opposes", unavailable: "Missing"};
    return `<div class="macro-scenario-evidence" aria-label="Evidence from the five charts">${evidence.map(function (item) {
      const stance = ["supporting", "partial", "contrary", "unavailable"].includes(item.stance) ? item.stance : "unavailable";
      return `<div class="macro-evidence-chip ${stance}"><span>${html(item.label || item.key || "Indicator")}</span><b>${html(item.value || "Unavailable")}</b><small>${html(stanceLabels[stance])}</small></div>`;
    }).join("")}</div>`;
  }

  function scenarioBoardMarkup(outlook, data) {
    const scenarios = Array.isArray(outlook && outlook.scenarios) ? outlook.scenarios : [];
    if (!scenarios.length) {
      return `<section class="macro-scenario-board unavailable" aria-label="Ranked macro scenarios"><div><b>Ranked scenarios need at least three official series</b><p>${html(outlook && outlook.methodology ? outlook.methodology : "The dashboard will wait for enough published evidence rather than infer missing releases.")}</p></div></section>`;
    }
    if (!state.scenarioKey || !scenarios.some(function (scenario) { return scenario.key === state.scenarioKey; })) {
      state.scenarioKey = outlook.leading_scenario_key || scenarios[0].key;
    }
    const selected = scenarios.find(function (scenario) { return scenario.key === state.scenarioKey; }) || scenarios[0];
    const selectedTone = ["positive", "caution", "risk", "mixed"].includes(selected.tone) ? selected.tone : "mixed";
    const coverage = Math.max(0, Math.min(5, Number(selected.coverage || 0)));
    const snapshotMode = data && Number(data.snapshot_series || 0) > 0;
    const sourceDate = data && (snapshotMode ? data.snapshot_captured_at : data.updated_at);
    const sourceLabel = sourceDate
      ? `${snapshotMode ? "Official snapshot" : "Updated"} · ${dateLabel(sourceDate, false)}`
      : "Latest official releases";
    const rows = scenarios.map(function (scenario) {
      const active = scenario.key === selected.key;
      const score = Math.max(0, Math.min(5, finite(scenario.signal_score) || 0));
      return `<button type="button" class="macro-scenario-row ${active ? "active" : ""}" data-dashboard-macro-action="scenario" data-scenario-key="${html(scenario.key)}" aria-pressed="${active}" aria-controls="macroScenarioDetail">
        <span class="macro-scenario-rank">${String(Number(scenario.rank || 0)).padStart(2, "0")}</span>
        <span class="macro-scenario-name"><b>${html(scenario.title || "Scenario")}</b><small>${html(firstSentence(scenario.consequence))}</small></span>
        <span class="macro-scenario-signal">${signalMeter(scenario)}<small>${html(score.toFixed(1))} / 5 · ${html(scenario.signal_label || "Signal")}</small></span>
        <span class="macro-scenario-open" aria-hidden="true">${active ? "Selected" : "→"}</span>
      </button>`;
    }).join("");
    const transmission = Array.isArray(selected.transmission) ? selected.transmission : [];
    return `<section class="macro-scenario-board" aria-label="Scenarios ranked by current signal">
      <div class="macro-scenario-board-head"><div><span>CURRENT MACRO PLAYBOOK</span><h4>Ranked scenarios from the five charts</h4></div><div><b>${coverage}/5 indicators</b><small>${html(sourceLabel)}</small></div></div>
      <div class="macro-scenario-workspace">
        <div class="macro-scenario-ranking">
          <div class="macro-scenario-table-head" aria-hidden="true"><span>Rank</span><span>Scenario &amp; likely consequence</span><span>Signal fit</span><span></span></div>
          <div class="macro-scenario-list">${rows}</div>
          <p class="macro-scenario-ranking-note">Select a row to inspect its evidence. Scores show evidence fit, not the probability that an outcome will occur.</p>
        </div>
        <article class="macro-scenario-detail ${selectedTone}" id="macroScenarioDetail" aria-live="polite">
          <div class="macro-scenario-detail-head"><div><span>${selected.is_leading ? "LEADING SCENARIO" : "SELECTED SCENARIO"} · RANK ${html(selected.rank)}</span><h4>${html(selected.title)}</h4><small>${html(outlook.status || "Current macro conditions")}</small></div><div>${signalMeter(selected)}<b>${html(Number(selected.signal_score || 0).toFixed(1))} / 5</b></div></div>
          <div class="macro-scenario-thesis"><span>Why it ranks here</span><p>${html(selected.thesis || "The available indicators do not yet provide a complete explanation.")}</p></div>
          <div class="macro-scenario-evidence-head"><span>Evidence from the five charts</span><small>Supports · partial · opposes</small></div>
          ${scenarioEvidenceMarkup(selected)}
          <div class="macro-scenario-impact"><span>What may happen if this persists</span><p>${html(selected.consequence || "Outcome unavailable.")}</p></div>
          <div class="macro-scenario-detail-grid">
            <div class="macro-scenario-path"><span>Transmission path</span><ol>${transmission.map(function (step) { return `<li>${html(step)}</li>`; }).join("")}</ol></div>
            <div class="macro-scenario-watch"><span>What would confirm or weaken it</span><p>${html(selected.watch_for || "Watch the next official releases.")}</p></div>
          </div>
          ${warningMarkup(outlook)}
          <p class="macro-scenario-method">${html(outlook.methodology || "This is a conditional scenario, not a forecast.")}</p>
        </article>
      </div>
    </section>`;
  }

  function renderScenarioBoard() {
    const board = mount.querySelector(".macro-scenario-board");
    if (!board || !state.data) return;
    const outlook = state.data.outlook || {};
    board.outerHTML = scenarioBoardMarkup(outlook, state.data);
  }

  function render() {
    const data = state.data || {};
    const series = data.series || {};
    state.chartModels = {};
    const available = Math.max(0, Number(data.available_series || 0));
    const total = Math.max(1, Number(data.total_series || 5));
    const liveCount = Math.max(0, Number(data.live_series || 0));
    const snapshotCount = Math.max(0, Number(data.snapshot_series || 0));
    const sourceMode = data.data_mode || (snapshotCount ? "mixed" : "live");
    const statusClass = available < total ? "partial" : sourceMode === "live" ? "" : "snapshot";
    const statusText = snapshotCount
      ? `${available}/${total} official · ${snapshotCount} cached`
      : `${available}/${total} official · ${liveCount} live`;
    const dashboardCopy = snapshotCount
      ? `Live FRED is unreachable for ${snapshotCount} series; showing the packaged official snapshot captured ${dateLabel(data.snapshot_captured_at, false)}. Refresh retries live data.`
      : "Five indicators, one synchronized period. Hover a graph—or use arrow keys—to inspect each published observation.";
    const outlook = data.outlook || {status: "Outlook unavailable", tone: "mixed", warnings: [], conclusion: "A long-term scenario needs more published observations."};
    const rangeLabel = {"12m": "12 months", "24m": "24 months", "5y": "5 years"}[state.range] || "selected period";
    const items = SERIES_ORDER.map(function (key) {
      return series[key] || {key: key, label: key, short_label: key, success: false};
    });
    mount.innerHTML = `<div class="dashboard-macro-head">
      <div><div class="assistant-kicker">U.S. MACRO PULSE · OFFICIAL RELEASES</div><div class="dashboard-macro-title-row"><h3>Prices, policy &amp; consumer demand</h3><span class="macro-official-status ${statusClass}"><i></i>${html(statusText)}</span></div><p class="dashboard-macro-copy">${html(dashboardCopy)}</p></div>
      <div class="dashboard-macro-controls"><div class="macro-range-switch" role="group" aria-label="Chart period">${["12m", "24m", "5y"].map(function (range) { return `<button type="button" class="${state.range === range ? "active" : ""}" data-dashboard-macro-action="range" data-range="${range}" aria-pressed="${state.range === range}">${range.toUpperCase()}</button>`; }).join("")}</div><button type="button" class="macro-dashboard-refresh" data-dashboard-macro-action="refresh" title="Refresh official releases"><span aria-hidden="true">↻</span> Refresh</button></div>
    </div>
    <div class="macro-signal-grid">${items.map(cardMarkup).join("")}</div>
    <section class="macro-dashboard-summary" aria-label="Latest movement and selected-period peaks">
      <div class="macro-summary-head"><b>Latest movement &amp; selected-period peaks</b><span>Latest vs previous release · peak over ${html(rangeLabel)}</span></div>
      <div class="macro-summary-cells">${items.map(summaryCell).join("")}</div>
    </section>
    ${scenarioBoardMarkup(outlook, data)}`;
    bindChartInteractions();
  }

  function hideTooltip(stage) {
    const tooltip = stage.querySelector(".macro-chart-tooltip");
    const cursor = stage.querySelector(".macro-chart-cursor");
    const point = stage.querySelector(".macro-chart-hover-point");
    if (tooltip) tooltip.hidden = true;
    if (cursor) cursor.style.opacity = "0";
    if (point) point.style.opacity = "0";
  }

  function showTooltip(stage, index) {
    const key = stage.dataset.macroChart;
    const model = state.chartModels[key];
    const item = state.data && state.data.series ? state.data.series[key] : null;
    if (!model || !item) return;
    const safeIndex = Math.max(0, Math.min(model.coordinates.length - 1, Number(index) || 0));
    const coordinate = model.coordinates[safeIndex];
    const cursor = stage.querySelector(".macro-chart-cursor");
    const point = stage.querySelector(".macro-chart-hover-point");
    const tooltip = stage.querySelector(".macro-chart-tooltip");
    if (!cursor || !point || !tooltip) return;
    cursor.setAttribute("x1", coordinate.x.toFixed(2));
    cursor.setAttribute("x2", coordinate.x.toFixed(2));
    point.setAttribute("cx", coordinate.x.toFixed(2));
    point.setAttribute("cy", coordinate.y.toFixed(2));
    cursor.style.opacity = "1";
    point.style.opacity = "1";
    tooltip.innerHTML = `<b>${html(formatValue(item, coordinate.value))}</b>${html(dateLabel(coordinate.date, false))}`;
    tooltip.hidden = false;
    const width = stage.getBoundingClientRect().width;
    const pixelX = (coordinate.x / 240) * width;
    tooltip.style.left = `${Math.max(3, Math.min(width - 91, pixelX < width * .62 ? pixelX + 7 : pixelX - 91))}px`;
    stage.dataset.pointIndex = String(safeIndex);
  }

  function bindChartInteractions() {
    mount.querySelectorAll("[data-macro-chart]").forEach(function (stage) {
      const key = stage.dataset.macroChart;
      const model = state.chartModels[key];
      if (!model) return;
      stage.addEventListener("pointermove", function (event) {
        const rectangle = stage.getBoundingClientRect();
        const ratio = Math.max(0, Math.min(1, (event.clientX - rectangle.left) / Math.max(1, rectangle.width)));
        showTooltip(stage, Math.round(ratio * (model.coordinates.length - 1)));
      });
      stage.addEventListener("pointerleave", function () { hideTooltip(stage); });
      stage.addEventListener("focus", function () { showTooltip(stage, model.coordinates.length - 1); });
      stage.addEventListener("blur", function () { hideTooltip(stage); });
      stage.addEventListener("keydown", function (event) {
        if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
        event.preventDefault();
        let index = Number(stage.dataset.pointIndex || model.coordinates.length - 1);
        if (event.key === "ArrowLeft") index -= 1;
        if (event.key === "ArrowRight") index += 1;
        if (event.key === "Home") index = 0;
        if (event.key === "End") index = model.coordinates.length - 1;
        showTooltip(stage, index);
      });
    });
  }

  function scheduleRefresh(seconds) {
    if (state.timer) window.clearTimeout(state.timer);
    const delay = Math.max(300, Number(seconds || 1800)) * 1000;
    state.timer = window.setTimeout(function () {
      if (document.getElementById("overview") && document.getElementById("overview").classList.contains("active")) load(false);
      else scheduleRefresh(seconds);
    }, delay);
  }

  async function load(force) {
    if (state.inFlight) return state.inFlight;
    const refresh = mount.querySelector('[data-dashboard-macro-action="refresh"]');
    if (refresh) refresh.disabled = true;
    if (!state.data) {
      mount.innerHTML = '<div class="dashboard-macro-loading"><span class="dashboard-macro-loading-mark" aria-hidden="true"></span><div><b>Loading official macro indicators…</b><span>CPI, Fed rate, retail sales, unemployment, and gasoline.</span></div></div>';
    }
    state.inFlight = (async function () {
      try {
        const url = force ? "/api/dashboard-macro?force=1" : "/api/dashboard-macro";
        const data = await getJSON(url, {cacheMs: force ? 0 : 600000, dedupe: true});
        if (!data || !data.series) throw new Error("The macro response did not include published series.");
        state.data = data;
        render();
        scheduleRefresh(data.refresh_seconds);
      } catch (error) {
        if (state.data) {
          render();
        } else {
          mount.innerHTML = `<div class="dashboard-macro-error"><div><b>Official macro data is temporarily unavailable</b><p>${html(error && error.message ? error.message : "The data provider could not be reached.")} The dashboard will not invent substitute readings.</p><button type="button" class="macro-dashboard-refresh" data-dashboard-macro-action="refresh">Try again</button></div></div>`;
        }
      } finally {
        state.inFlight = null;
        const button = mount.querySelector('[data-dashboard-macro-action="refresh"]');
        if (button) button.disabled = false;
      }
    })();
    return state.inFlight;
  }

  mount.addEventListener("click", function (event) {
    const target = event.target.closest("[data-dashboard-macro-action]");
    if (!target) return;
    const action = target.dataset.dashboardMacroAction;
    if (action === "range" && RANGE_MONTHS[target.dataset.range]) {
      state.range = target.dataset.range;
      if (state.data) render();
    }
    if (action === "refresh") load(true);
    if (action === "scenario") {
      state.scenarioKey = target.dataset.scenarioKey || state.scenarioKey;
      renderScenarioBoard();
      const selected = mount.querySelector(`[data-scenario-key="${state.scenarioKey}"]`);
      if (selected) selected.focus();
    }
  });

  window.SolvAIDashboardMacro = Object.freeze({load: load});
  load(false);
})();
