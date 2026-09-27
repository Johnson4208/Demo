(function () {
  "use strict";

  const fullState = {
    tab: "strength",
    category: "all",
    peerSnapshots: new Map(),
    peerRequest: 0,
    hydratedCompany: "",
    resizeFrame: 0,
    evidenceReturnFocus: null,
  };

  const tabDefinitions = [
    ["strength", "Financial strength"],
    ["growth", "Growth"],
    ["profitability", "Profitability"],
    ["valuation", "Valuation"],
    ["cashflow", "Cash flow"],
    ["peers", "Peers"],
  ];

  const tabCopy = {
    strength: ["Financial strength", "Key balance-sheet and financial-health metrics, with peer comparison and supporting evidence."],
    growth: ["Growth", "Revenue, earnings, and cash-generation momentum using only the periods supported by available evidence."],
    profitability: ["Profitability", "Margins and capital efficiency, with source labels and peer context where it is available."],
    valuation: ["Valuation", "Market multiples and per-share indicators from the latest available market snapshot."],
    cashflow: ["Cash flow", "Operating cash generation, reinvestment, and free cash flow without filling missing values."],
    peers: ["Peer comparison", "A consistent side-by-side view of companies discovered in the same research library."],
  };

  function finite(value) {
    return value !== null && value !== undefined && value !== "" && Number.isFinite(Number(value));
  }

  function rawMetric(data, key) {
    const item = data?.metrics?.[key];
    return item && typeof item === "object" ? item.value : item;
  }

  function priorMetric(data, key) {
    const item = data?.metrics?.[key];
    return item && typeof item === "object" ? item.comparison_value : null;
  }

  function ratioMetric(data, key) {
    try {
      return selectedRatio(data || {}, key);
    } catch (_) {
      return rawMetric(data, key);
    }
  }

  function derivedRatio(numerator, denominator, scale = 100) {
    if (!finite(numerator) || !finite(denominator) || Number(denominator) === 0) return null;
    return Number(numerator) / Number(denominator) * scale;
  }

  function currency(data) {
    return String(data?.currency || "VND").toUpperCase();
  }

  function formatCompact(value, unit = "VND") {
    if (!finite(value)) return "Unavailable";
    const number = Number(value);
    const absolute = Math.abs(number);
    let result;
    if (absolute >= 1e12) result = `${(number / 1e12).toFixed(2).replace(/\.00$/, "")}T`;
    else if (absolute >= 1e9) result = `${(number / 1e9).toFixed(2).replace(/\.00$/, "")}B`;
    else if (absolute >= 1e6) result = `${(number / 1e6).toFixed(2).replace(/\.00$/, "")}M`;
    else if (absolute >= 1e3) result = `${(number / 1e3).toFixed(2).replace(/\.00$/, "")}K`;
    else result = number.toLocaleString(undefined, { maximumFractionDigits: 2 });
    return unit ? `${result} ${unit}` : result;
  }

  function formatPrice(value, unit = "VND") {
    if (!finite(value)) return "Unavailable";
    const digits = unit === "VND" ? 0 : 2;
    return `${Number(value).toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits })} ${unit}`;
  }

  function displayValue(value, type = "number", unit = "VND") {
    if (!finite(value)) return "Unavailable";
    if (type === "money") return formatCompact(value, unit);
    if (type === "price") return formatPrice(value, unit);
    if (type === "percent") return `${Number(value).toFixed(1)}%`;
    if (type === "multiple") return `${Number(value).toFixed(2).replace(/0+$/, "").replace(/\.$/, "")}×`;
    if (type === "integer") return Number(value).toLocaleString(undefined, { maximumFractionDigits: 0 });
    if (type === "score") return `${Math.round(Number(value))} / 100`;
    return Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 });
  }

  function prettyDate(value, includeTime = false) {
    if (!value) return "Unavailable";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return new Intl.DateTimeFormat("en-GB", {
      day: "2-digit",
      month: "short",
      year: "numeric",
      ...(includeTime ? { hour: "2-digit", minute: "2-digit", hour12: true } : {}),
    }).format(date);
  }

  function sourcePill(source, metricKey = "") {
    const sourceClass = source === "Verified report" ? "report" : source === "Market data" ? "market" : "derived";
    if (source === "Verified report" && metricKey) {
      return `<button type="button" class="full-source-pill ${sourceClass}" data-full-action="evidence" data-metric="${esc(metricKey)}">${esc(source)}</button>`;
    }
    return `<span class="full-source-pill ${sourceClass}">${esc(source)}</span>`;
  }

  function median(values) {
    const clean = values.filter(finite).map(Number).sort((a, b) => a - b);
    if (!clean.length) return null;
    const middle = Math.floor(clean.length / 2);
    return clean.length % 2 ? clean[middle] : (clean[middle - 1] + clean[middle]) / 2;
  }

  function peerMetric(data, key) {
    return median((data?.peers || []).map((peer) => peer?.[key]));
  }

  function peerMarketMetric(key) {
    return median([...fullState.peerSnapshots.values()].map((snapshot) => snapshot?.[key]));
  }

  function metricSpec(label, note, current, options = {}) {
    return {
      label,
      note,
      current,
      prior: options.prior ?? null,
      peer: options.peer ?? null,
      type: options.type || "number",
      source: options.source || "Verified report",
      metricKey: options.metricKey || "",
      preference: options.preference || "higher",
      unit: options.unit || currency(overviewMarketCache),
    };
  }

  function tabMetrics(data, snapshot, tab) {
    const unit = currency(snapshot);
    const revenue = rawMetric(data, "revenue");
    const cashFlow = rawMetric(data, "cash_flow");
    const freeCashFlow = snapshot?.free_cash_flow;
    const fcfMargin = finite(freeCashFlow) && finite(revenue) && Number(revenue) !== 0
      ? Number(freeCashFlow) / Number(revenue) * 100
      : null;
    const localGrossMargin = derivedRatio(rawMetric(data, "gross_profit"), revenue);
    const localOperatingMargin = derivedRatio(rawMetric(data, "operating_profit"), revenue);
    const grossMargin = finite(localGrossMargin) ? localGrossMargin : snapshot?.gross_margin_pct;
    const grossSource = finite(localGrossMargin) ? "Derived" : "Market data";
    const operatingMargin = finite(localOperatingMargin) ? localOperatingMargin : snapshot?.operating_margin_pct;
    const operatingSource = finite(localOperatingMargin) ? "Derived" : "Market data";
    const cashGeneration = finite(cashFlow) ? cashFlow : freeCashFlow;
    const cashGenerationSource = finite(cashFlow) ? "Verified report" : "Market data";

    const groups = {
      strength: [
        metricSpec("Growth", "Revenue growth", ratioMetric(data, "revenue_growth"), { peer: peerMetric(data, "revenue_growth"), type: "percent", metricKey: "revenue_growth" }),
        metricSpec("Profitability", "Operating profit / revenue", operatingMargin, { peer: null, type: "percent", source: operatingSource }),
        metricSpec("Capital efficiency", "ROE", ratioMetric(data, "roe"), { prior: priorMetric(data, "roe"), peer: peerMetric(data, "roe"), type: "percent", metricKey: "roe" }),
        metricSpec("Leverage", "Debt / EBITDA", rawMetric(data, "debt_to_ebitda"), { prior: priorMetric(data, "debt_to_ebitda"), peer: peerMetric(data, "debt_to_ebitda"), type: "multiple", metricKey: "debt_to_ebitda", preference: "lower" }),
        metricSpec("Cash generation", finite(cashFlow) ? "Statement operating cash flow" : "Free cash flow", cashGeneration, { peer: null, type: "money", source: cashGenerationSource, metricKey: finite(cashFlow) ? "cash_flow" : "", unit }),
        metricSpec("Valuation", "P/E", snapshot?.pe, { peer: peerMarketMetric("pe"), type: "multiple", source: "Market data", preference: "lower" }),
        metricSpec("Market behavior", "Beta", snapshot?.beta, { peer: peerMarketMetric("beta"), type: "number", source: "Market data", preference: "lower" }),
      ],
      growth: [
        metricSpec("Revenue", "Latest verified period", revenue, { prior: priorMetric(data, "revenue"), type: "money", metricKey: "revenue", unit }),
        metricSpec("Revenue momentum", "Year on year", ratioMetric(data, "revenue_growth"), { peer: peerMetric(data, "revenue_growth"), type: "percent", metricKey: "revenue_growth" }),
        metricSpec("Earnings momentum", "Provider estimate", snapshot?.earnings_growth_pct, { peer: peerMarketMetric("earnings_growth_pct"), type: "percent", source: "Market data" }),
        metricSpec("EBITDA", "Latest verified period", rawMetric(data, "ebitda"), { prior: priorMetric(data, "ebitda"), type: "money", metricKey: "ebitda", unit }),
        metricSpec("EBITDA margin", "Latest verified period", ratioMetric(data, "ebitda_margin"), { prior: priorMetric(data, "ebitda_margin"), type: "percent", metricKey: "ebitda_margin" }),
        metricSpec("Net income", "Latest verified period", rawMetric(data, "net_income"), { prior: priorMetric(data, "net_income"), type: "money", metricKey: "net_income", unit }),
        metricSpec("Free cash flow", "Latest market snapshot", freeCashFlow, { type: "money", source: "Market data", unit }),
      ],
      profitability: [
        metricSpec("Gross margin", finite(localGrossMargin) ? "Verified gross profit / revenue" : "Market snapshot", grossMargin, { type: "percent", peer: peerMarketMetric("gross_margin_pct"), source: grossSource }),
        metricSpec("Operating margin", finite(localOperatingMargin) ? "Verified operating profit / revenue" : "Market snapshot", operatingMargin, { type: "percent", peer: peerMarketMetric("operating_margin_pct"), source: operatingSource }),
        metricSpec("Net margin", "Latest verified period", ratioMetric(data, "net_margin"), { prior: priorMetric(data, "net_margin"), peer: peerMetric(data, "net_margin"), type: "percent", metricKey: "net_margin" }),
        metricSpec("EBITDA margin", "Latest verified period", ratioMetric(data, "ebitda_margin"), { prior: priorMetric(data, "ebitda_margin"), type: "percent", metricKey: "ebitda_margin" }),
        metricSpec("Return on equity", "ROE", ratioMetric(data, "roe"), { prior: priorMetric(data, "roe"), peer: peerMetric(data, "roe"), type: "percent", metricKey: "roe" }),
        metricSpec("Return on assets", "ROA", ratioMetric(data, "roa"), { prior: priorMetric(data, "roa"), peer: peerMetric(data, "roa"), type: "percent", metricKey: "roa" }),
        metricSpec("Cash flow margin", "Operating cash flow / revenue", rawMetric(data, "cash_flow_margin"), { prior: priorMetric(data, "cash_flow_margin"), type: "percent", metricKey: "cash_flow_margin" }),
      ],
      valuation: [
        metricSpec("Share price", "Latest market snapshot", snapshot?.price, { type: "price", source: "Market data", unit }),
        metricSpec("Market capitalization", "Latest market snapshot", snapshot?.market_cap, { type: "money", source: "Market data", unit }),
        metricSpec("P/E", "Trailing earnings", snapshot?.pe, { peer: peerMarketMetric("pe"), type: "multiple", source: "Market data", preference: "lower" }),
        metricSpec("Forward P/E", "Provider estimate", snapshot?.forward_pe, { peer: peerMarketMetric("forward_pe"), type: "multiple", source: "Market data", preference: "lower" }),
        metricSpec("Price / book", "Latest market snapshot", snapshot?.pb, { peer: peerMarketMetric("pb"), type: "multiple", source: "Market data", preference: "lower" }),
        metricSpec("Earnings per share", "Trailing earnings", snapshot?.eps, { type: "price", source: "Market data", unit }),
        metricSpec("Book value / share", "Latest market snapshot", snapshot?.book_value_per_share, { type: "price", source: "Market data", unit }),
      ],
      cashflow: [
        metricSpec("Statement cash flow", "Latest verified period", cashFlow, { prior: priorMetric(data, "cash_flow"), type: "money", metricKey: "cash_flow", unit }),
        metricSpec("Operating cash flow", "Latest market snapshot", snapshot?.operating_cash_flow, { type: "money", source: "Market data", unit }),
        metricSpec("Free cash flow", "Latest market snapshot", freeCashFlow, { type: "money", source: "Market data", unit }),
        metricSpec("Capital expenditure", "Absolute outflow", finite(snapshot?.capital_expenditure) ? Math.abs(Number(snapshot.capital_expenditure)) : null, { type: "money", source: "Market data", preference: "lower", unit }),
        metricSpec("Cash flow margin", "Statement cash flow / revenue", rawMetric(data, "cash_flow_margin"), { prior: priorMetric(data, "cash_flow_margin"), type: "percent", metricKey: "cash_flow_margin" }),
        metricSpec("Free cash flow margin", "Free cash flow / revenue", fcfMargin, { type: "percent", source: "Derived" }),
        metricSpec("Net debt / EBITDA", "Latest market snapshot", snapshot?.net_debt_to_ebitda, { type: "multiple", source: "Market data", preference: "lower" }),
      ],
    };
    return groups[tab] || groups.strength;
  }

  function trendMarkup(row) {
    if (!finite(row.current) || !finite(row.prior)) return '<span class="full-trend neutral">—</span>';
    const delta = Number(row.current) - Number(row.prior);
    if (Math.abs(delta) < 1e-9) return '<span class="full-trend neutral">→</span>';
    const rising = delta > 0;
    const favorable = row.preference === "lower" ? !rising : rising;
    return `<span class="full-trend ${favorable ? "positive" : "negative"}" aria-label="${rising ? "Increasing" : "Decreasing"}">${rising ? "▲" : "▼"}</span>`;
  }

  function renderMetricMatrix(data, snapshot) {
    if (fullState.tab === "peers") return renderPeerTable(data);
    const rows = tabMetrics(data, snapshot, fullState.tab);
    return `<div class="full-metric-table-wrap"><table class="full-metric-table">
      <thead><tr><th>Metric</th><th>Current</th><th>Prior</th><th>Trend</th><th>Peer median</th><th>Evidence</th></tr></thead>
      <tbody>${rows.map((row) => `<tr>
        <td><b>${esc(row.label)}</b><span>${esc(row.note)}</span></td>
        <td><strong>${esc(displayValue(row.current, row.type, row.unit))}</strong></td>
        <td>${esc(displayValue(row.prior, row.type, row.unit))}</td>
        <td>${trendMarkup(row)}</td>
        <td>${esc(displayValue(row.peer, row.type, row.unit))}</td>
        <td>${sourcePill(row.source, row.metricKey)}</td>
      </tr>`).join("")}</tbody>
    </table></div>`;
  }

  function renderPeerTable(data) {
    const current = {
      company: data?.company,
      revenue_growth: ratioMetric(data, "revenue_growth"),
      net_margin: ratioMetric(data, "net_margin"),
      roe: ratioMetric(data, "roe"),
      debt_to_ebitda: rawMetric(data, "debt_to_ebitda"),
      reports: data?.reports,
    };
    const rows = [current, ...(data?.peers || []).filter((peer) => String(peer.company).toUpperCase() !== String(data?.company).toUpperCase())];
    return `<div class="full-metric-table-wrap"><table class="full-metric-table full-peer-table">
      <thead><tr><th>Company</th><th>Growth</th><th>Net margin</th><th>ROE</th><th>Debt / EBITDA</th><th>Reports</th></tr></thead>
      <tbody>${rows.map((peer, index) => `<tr class="${index === 0 ? "current" : ""}"><td><b>${esc(peer.company || "Unavailable")}</b><span>${index === 0 ? "Selected company" : "Research-library peer"}</span></td><td>${esc(displayValue(peer.revenue_growth, "percent"))}</td><td>${esc(displayValue(peer.net_margin, "percent"))}</td><td>${esc(displayValue(peer.roe, "percent"))}</td><td>${esc(displayValue(peer.debt_to_ebitda, "multiple"))}</td><td>${finite(peer.reports) ? esc(peer.reports) : "—"}</td></tr>`).join("")}</tbody>
    </table></div>`;
  }

  function detailItem(label, value, options = {}) {
    return {
      label,
      value,
      type: options.type || "number",
      source: options.source || "Verified report",
      metricKey: options.metricKey || "",
      unit: options.unit || currency(overviewMarketCache),
    };
  }

  function detailedGroups(data, snapshot) {
    const unit = currency(snapshot);
    const revenue = rawMetric(data, "revenue");
    const grossProfit = rawMetric(data, "gross_profit");
    const operatingProfit = rawMetric(data, "operating_profit");
    const currentAssets = rawMetric(data, "current_assets");
    const currentLiabilities = rawMetric(data, "current_liabilities");
    const equity = rawMetric(data, "equity");
    const debt = rawMetric(data, "debt");
    const receivables = rawMetric(data, "receivables");
    const statementCashFlow = rawMetric(data, "cash_flow");
    const analysisNetIncome = rawMetric(data, "net_income");
    const fcf = snapshot?.free_cash_flow;
    const fcfMargin = finite(fcf) && finite(revenue) && Number(revenue) !== 0 ? Number(fcf) / Number(revenue) * 100 : null;
    const grossMarginLocal = derivedRatio(grossProfit, revenue);
    const operatingMarginLocal = derivedRatio(operatingProfit, revenue);
    const grossMargin = finite(grossMarginLocal) ? grossMarginLocal : snapshot?.gross_margin_pct;
    const operatingMargin = finite(operatingMarginLocal) ? operatingMarginLocal : snapshot?.operating_margin_pct;
    const workingCapital = finite(currentAssets) && finite(currentLiabilities) ? Number(currentAssets) - Number(currentLiabilities) : null;
    const currentRatio = derivedRatio(currentAssets, currentLiabilities, 1);
    const debtToEquity = derivedRatio(debt, equity, 1);
    const receivablesToRevenue = derivedRatio(receivables, revenue);
    const cashConversion = derivedRatio(statementCashFlow, analysisNetIncome);
    const quality = data?.latest_report?.quality_score;
    const coverage = data?.coverage || {};
    const coveragePct = finite(coverage.total_metrics) && Number(coverage.total_metrics) > 0
      ? Number(coverage.available_metrics || 0) / Number(coverage.total_metrics) * 100
      : null;
    const scanCoverage = data?.scan_coverage || {};
    const scanCoveragePct = finite(scanCoverage.total_metrics) && Number(scanCoverage.total_metrics) > 0
      ? Number(scanCoverage.available_metrics || 0) / Number(scanCoverage.total_metrics) * 100
      : null;
    return [
      {
        id: "income",
        title: "Income statement & growth",
        items: [
          detailItem("Gross revenue", rawMetric(data, "gross_revenue"), { type: "money", metricKey: "gross_revenue", unit }),
          detailItem("Revenue deductions", rawMetric(data, "revenue_reductions"), { type: "money", metricKey: "revenue_reductions", unit }),
          detailItem("Net revenue", revenue, { type: "money", metricKey: "revenue", unit }),
          detailItem("Revenue growth (YoY)", ratioMetric(data, "revenue_growth"), { type: "percent", metricKey: "revenue_growth" }),
          detailItem("Cost of goods sold", rawMetric(data, "cost_of_goods_sold"), { type: "money", metricKey: "cost_of_goods_sold", unit }),
          detailItem("Gross profit", grossProfit, { type: "money", metricKey: "gross_profit", unit }),
          detailItem("Gross margin", grossMargin, { type: "percent", source: finite(grossMarginLocal) ? "Derived" : "Market data" }),
          detailItem("Operating profit", operatingProfit, { type: "money", metricKey: "operating_profit", unit }),
          detailItem("Operating margin", operatingMargin, { type: "percent", source: finite(operatingMarginLocal) ? "Derived" : "Market data" }),
          detailItem("EBITDA", rawMetric(data, "ebitda"), { type: "money", metricKey: "ebitda", unit }),
          detailItem("EBITDA margin", ratioMetric(data, "ebitda_margin"), { type: "percent", metricKey: "ebitda_margin" }),
          detailItem("Net income used in analysis", analysisNetIncome, { type: "money", metricKey: "net_income", unit }),
          detailItem("Parent-attributable profit", rawMetric(data, "net_income_parent"), { type: "money", metricKey: "net_income_parent", unit }),
          detailItem("Total consolidated profit", rawMetric(data, "net_income_total"), { type: "money", metricKey: "net_income_total", unit }),
          detailItem("Non-controlling interest profit", rawMetric(data, "nci_profit"), { type: "money", metricKey: "nci_profit", unit }),
          detailItem("Selling expense", rawMetric(data, "selling_expense"), { type: "money", metricKey: "selling_expense", unit }),
          detailItem("Administrative expense", rawMetric(data, "admin_expense"), { type: "money", metricKey: "admin_expense", unit }),
          detailItem("SG&A", rawMetric(data, "sga"), { type: "money", metricKey: "sga", unit }),
          detailItem("Depreciation", rawMetric(data, "depreciation"), { type: "money", metricKey: "depreciation", unit }),
          detailItem("Net margin", ratioMetric(data, "net_margin"), { type: "percent", metricKey: "net_margin" }),
          detailItem("Earnings growth (YoY)", snapshot?.earnings_growth_pct, { type: "percent", source: "Market data" }),
        ],
      },
      {
        id: "capital",
        title: "Capital & efficiency",
        items: [
          detailItem("Total assets", rawMetric(data, "assets"), { type: "money", metricKey: "assets", unit }),
          detailItem("Total liabilities", rawMetric(data, "total_liabilities"), { type: "money", metricKey: "total_liabilities", unit }),
          detailItem("Shareholders’ equity", equity, { type: "money", metricKey: "equity", unit }),
          detailItem("Total liabilities & equity", rawMetric(data, "total_sources"), { type: "money", metricKey: "total_sources", unit }),
          detailItem("Current assets", currentAssets, { type: "money", metricKey: "current_assets", unit }),
          detailItem("Current liabilities", currentLiabilities, { type: "money", metricKey: "current_liabilities", unit }),
          detailItem("Working capital", workingCapital, { type: "money", source: "Derived", unit }),
          detailItem("Current ratio", currentRatio, { type: "multiple", source: "Derived" }),
          detailItem("Receivables", receivables, { type: "money", metricKey: "receivables", unit }),
          detailItem("Receivables / revenue", receivablesToRevenue, { type: "percent", source: "Derived" }),
          detailItem("Property, plant & equipment", rawMetric(data, "ppe"), { type: "money", metricKey: "ppe", unit }),
          detailItem("Short-term debt", rawMetric(data, "short_term_debt"), { type: "money", metricKey: "short_term_debt", unit }),
          detailItem("Long-term debt", rawMetric(data, "long_term_debt"), { type: "money", metricKey: "long_term_debt", unit }),
          detailItem("Total debt", debt, { type: "money", metricKey: "debt", unit }),
          detailItem("Debt / equity", debtToEquity, { type: "multiple", source: "Derived" }),
          detailItem("Return on equity", ratioMetric(data, "roe"), { type: "percent", metricKey: "roe" }),
          detailItem("Return on assets", ratioMetric(data, "roa"), { type: "percent", metricKey: "roa" }),
          detailItem("Debt / EBITDA", rawMetric(data, "debt_to_ebitda"), { type: "multiple", metricKey: "debt_to_ebitda" }),
          detailItem("Net debt / EBITDA", snapshot?.net_debt_to_ebitda, { type: "multiple", source: "Market data" }),
        ],
      },
      {
        id: "cash",
        title: "Cash flow & reinvestment",
        items: [
          detailItem("Statement operating cash flow", statementCashFlow, { type: "money", metricKey: "cash_flow", unit }),
          detailItem("Cash flow margin", rawMetric(data, "cash_flow_margin"), { type: "percent", metricKey: "cash_flow_margin" }),
          detailItem("Statement cash conversion", cashConversion, { type: "percent", source: "Derived" }),
          detailItem("Operating cash flow (market)", snapshot?.operating_cash_flow, { type: "money", source: "Market data", unit }),
          detailItem("Free cash flow", fcf, { type: "money", source: "Market data", unit }),
          detailItem("Capital expenditure", finite(snapshot?.capital_expenditure) ? Math.abs(Number(snapshot.capital_expenditure)) : null, { type: "money", source: "Market data", unit }),
          detailItem("Free cash flow margin", fcfMargin, { type: "percent", source: "Derived" }),
          detailItem("Free cash flow conversion", derivedRatio(fcf, analysisNetIncome), { type: "percent", source: "Derived" }),
        ],
      },
      {
        id: "valuation",
        title: "Valuation & market",
        items: [
          detailItem("Price", snapshot?.price, { type: "price", source: "Market data", unit }),
          detailItem("Market capitalization", snapshot?.market_cap, { type: "money", source: "Market data", unit }),
          detailItem("P/E (trailing)", snapshot?.pe, { type: "multiple", source: "Market data" }),
          detailItem("Forward P/E", snapshot?.forward_pe, { type: "multiple", source: "Market data" }),
          detailItem("Price / book", snapshot?.pb, { type: "multiple", source: "Market data" }),
          detailItem("EPS (trailing)", snapshot?.eps, { type: "price", source: "Market data", unit }),
          detailItem("Book value / share", snapshot?.book_value_per_share, { type: "price", source: "Market data", unit }),
          detailItem("Beta (1Y)", snapshot?.beta, { source: "Market data" }),
          detailItem("Average volume (10D)", snapshot?.avg_volume_10d, { type: "integer", source: "Market data", unit: "" }),
          detailItem("Shares outstanding", snapshot?.shares_outstanding, { type: "integer", source: "Market data", unit: "" }),
        ],
      },
      {
        id: "shareholder",
        title: "Shareholder returns",
        items: [
          detailItem("Dividend / share", snapshot?.dividend_rate, { type: "price", source: "Market data", unit }),
          detailItem("Dividend yield", snapshot?.dividend_yield_pct, { type: "percent", source: "Market data" }),
          detailItem("Payout ratio", snapshot?.payout_ratio_pct, { type: "percent", source: "Market data" }),
          detailItem("Ex-dividend date", null, { source: "Market data" }),
          detailItem("Market state", null, { source: "Market data" }),
        ],
      },
      {
        id: "evidence",
        title: "Evidence & coverage",
        items: [
          detailItem("Research score", data?.health?.score, { type: "score", source: "Derived" }),
          detailItem("Report quality", quality, { type: "score", source: "Verified report" }),
          detailItem("Scanned line coverage", scanCoveragePct, { type: "percent", source: "Derived" }),
          detailItem("Available report lines", scanCoverage.available_metrics, { type: "integer", source: "Derived", unit: "" }),
          detailItem("Tracked report lines", scanCoverage.total_metrics, { type: "integer", source: "Derived", unit: "" }),
          detailItem("Core indicator coverage", coveragePct, { type: "percent", source: "Derived" }),
          detailItem("Available core indicators", coverage.available_metrics, { type: "integer", source: "Derived", unit: "" }),
          detailItem("Indexed reports", data?.reports, { type: "integer", source: "Verified report", unit: "" }),
          detailItem("Peer companies", (data?.peers || []).length, { type: "integer", source: "Derived", unit: "" }),
        ],
      },
    ].map((group) => ({
      ...group,
      items: group.items.map((item) => {
        if (group.id === "shareholder" && item.label === "Ex-dividend date") {
          return { ...item, valueText: snapshot?.ex_dividend_date ? prettyDate(snapshot.ex_dividend_date) : "Unavailable" };
        }
        if (group.id === "shareholder" && item.label === "Market state") {
          return { ...item, valueText: snapshot?.market_state || "Unavailable" };
        }
        return item;
      }),
    }));
  }

  function renderDetails(data, snapshot) {
    const groups = detailedGroups(data, snapshot).filter((group) => fullState.category === "all" || group.id === fullState.category);
    return groups.map((group) => `<section class="full-detail-group" data-category="${esc(group.id)}">
      <h4>${esc(group.title)}</h4>
      <div class="full-detail-rows">${group.items.map((item) => `<div class="full-detail-row"><span>${esc(item.label)}</span><b>${esc(item.valueText || displayValue(item.value, item.type, item.unit))}</b>${sourcePill(item.source, item.metricKey)}</div>`).join("")}</div>
    </section>`).join("");
  }

  function companyThesis(data) {
    const company = data?.company || "This company";
    const industry = data?.industry ? ` in ${data.industry}` : "";
    const signals = (data?.health?.signals || []).filter(Boolean);
    const signalText = signals.length ? `${signals.join(". ")}.` : "The available evidence is not yet sufficient for a directional conclusion.";
    return `${company}${industry} is currently classified as ${String(data?.health?.label || "insufficient evidence").toLowerCase()}. ${signalText} Use the source-linked indicators for the final research judgment.`;
  }

  function statusInfo(data) {
    const direction = data?.health?.direction;
    if (direction === "UP") return ["positive", "Positive evidence"];
    if (direction === "DOWN") return ["negative", "Negative evidence"];
    return ["neutral", "Mixed evidence"];
  }

  function renderHeader(data, snapshot, requested) {
    const bar = document.querySelector("#companyModeOverlay .company-overlay-bar");
    if (!bar) return;
    const cachedCompany = String(data?.company || "").toUpperCase();
    const company = requested && requested !== cachedCompany ? requested : (data?.company || requested || "");
    const updated = snapshot?.updated_at || data?.latest_report?.period_end;
    bar.innerHTML = `<div class="full-overlay-title">COMPANY OVERVIEW · FULL RESEARCH</div>
      <form class="full-overlay-search" id="fullOverlaySearch" role="search">
        <span aria-hidden="true">⌕</span>
        <input id="fullOverlayCompany" value="${esc(company)}" aria-label="Search company or ticker" autocomplete="off" spellcheck="false">
        <button type="submit" aria-label="Search company">↵</button>
      </form>
      <div class="full-overlay-updated"><i></i>${updated ? `Updated ${esc(prettyDate(updated, Boolean(snapshot?.updated_at)))}` : "Update time unavailable"}</div>
      <button type="button" class="company-overlay-close" data-action="close-overview" aria-label="Close full research overview">×</button>`;
  }

  function renderTabs() {
    return `<nav class="full-tabs" aria-label="Full research categories" role="tablist">${tabDefinitions.map(([id, label]) => `<button type="button" role="tab" aria-selected="${fullState.tab === id}" class="${fullState.tab === id ? "active" : ""}" data-full-action="tab" data-tab="${id}">${esc(label)}</button>`).join("")}</nav>`;
  }

  function renderRail(data, snapshot) {
    const [statusClass, statusLabel] = statusInfo(data);
    const company = data?.company || "—";
    const mark = String(company).replace(/[^A-Za-z0-9]/g, "").slice(0, 3) || "—";
    const coverage = data?.coverage || {};
    const available = Number(coverage.available_metrics || 0);
    const total = Number(coverage.total_metrics || 0);
    const completion = total ? Math.round(available / total * 100) : 0;
    const coverageText = completion === 100 ? "Complete" : `${completion}%`;
    return `<aside class="full-company-rail" aria-label="${esc(company)} company summary">
      <div class="full-company-identity"><span>${esc(mark)}</span><div><h2>${esc(company)}</h2><p>${esc(data?.industry || "Industry unavailable")}</p></div></div>
      <div class="full-status ${statusClass}"><i></i>${esc(statusLabel)}</div>
      <div class="full-price"><strong>${esc(formatPrice(snapshot?.price, currency(snapshot)))}</strong>${finite(snapshot?.price) ? `<span>Latest market snapshot</span>` : `<span>Market price unavailable</span>`}</div>
      <div class="full-rail-kpis"><div><span>Market cap</span><b>${esc(formatCompact(snapshot?.market_cap, currency(snapshot)))}</b></div><div><span>Research score</span><b>${finite(data?.health?.score) ? `${Math.round(Number(data.health.score))} / 100` : "Unavailable"}</b></div></div>
      <div class="full-rail-divider"></div>
      <div class="full-thesis"><span>Investment thesis</span><p>${esc(companyThesis(data))}</p></div>
      <dl class="full-rail-facts">
        <div><dt>Report date</dt><dd><span aria-hidden="true">▧</span>${esc(prettyDate(data?.latest_report?.period_end))}</dd></div>
        <div><dt>Coverage</dt><dd><span aria-hidden="true">☑</span>${available}/${total || "—"} indicators <em class="${completion === 100 ? "complete" : ""}"><i></i>${esc(coverageText)}</em></dd></div>
      </dl>
      <button type="button" class="full-core-value" data-action="overview-valuation">Calculate core value <span>→</span></button>
      <div class="full-value-result overview-core-value-mount"><div class="valuation-empty"><b>Not calculated yet</b><span>Run only when deeper valuation is needed.</span></div></div>
      <div class="full-rail-actions">
        <button type="button" data-full-action="report"><span>▧</span>View full report</button>
        <button type="button" data-full-action="watchlist"><span>☆</span>Add to watchlist</button>
        <button type="button" data-full-action="alert"><span>♧</span>Set price alert</button>
        <button type="button" data-full-action="compare"><span>⇄</span>Compare with peers</button>
      </div>
    </aside>`;
  }

  function renderWorkspace(data, snapshot, options = {}) {
    const content = $("companyOverlayContent");
    if (!content || !data) return;
    const previousScroll = options.preserveScroll ? content.querySelector(".full-research-main")?.scrollTop || 0 : 0;
    const copy = tabCopy[fullState.tab] || tabCopy.strength;
    content.innerHTML = `<div class="full-research-layout">
      ${renderRail(data, snapshot)}
      <section class="full-research-main">
        ${renderTabs()}
        <div class="full-primary-grid">
          <section class="full-matrix-panel">
            <header><h3>${esc(copy[0])}</h3><p>${esc(copy[1])}</p></header>
            <div id="fullMetricMatrix">${renderMetricMatrix(data, snapshot)}</div>
          </section>
          <aside class="full-chart-column">
            <section class="full-chart-card"><h4>Peer position (P/E vs ROE)</h4><canvas id="fullPeerChart" aria-label="Peer position chart"></canvas></section>
            <section class="full-chart-card"><h4>Revenue to Free Cash Flow bridge</h4><span class="full-chart-unit">(${esc(currency(snapshot))})</span><canvas id="fullCashBridge" aria-label="Revenue to free cash flow bridge"></canvas></section>
          </aside>
        </div>
        <section class="full-details-panel">
          <header><div><h3>Key indicators (detailed)</h3><p>Underlying financial and market indicators with data provenance.</p></div><div class="full-detail-controls"><label><span class="sr-only">Filter indicator category</span><select id="fullCategoryFilter"><option value="all" ${fullState.category === "all" ? "selected" : ""}>All categories</option><option value="income" ${fullState.category === "income" ? "selected" : ""}>Income & growth</option><option value="capital" ${fullState.category === "capital" ? "selected" : ""}>Capital & efficiency</option><option value="cash" ${fullState.category === "cash" ? "selected" : ""}>Cash flow</option><option value="valuation" ${fullState.category === "valuation" ? "selected" : ""}>Valuation & market</option><option value="shareholder" ${fullState.category === "shareholder" ? "selected" : ""}>Shareholder returns</option><option value="evidence" ${fullState.category === "evidence" ? "selected" : ""}>Evidence & coverage</option></select></label><button type="button" data-full-action="source">View source <span>↗</span></button></div></header>
          <div class="full-details-scroll"><div class="full-detail-grid" id="fullDetailGrid">${renderDetails(data, snapshot)}</div></div>
        </section>
      </section>
    </div>`;
    const main = content.querySelector(".full-research-main");
    if (main) main.scrollTop = previousScroll;
    requestAnimationFrame(drawFullCharts);
    hydratePeerSnapshots(data);
  }

  function renderLoading(requested) {
    const content = $("companyOverlayContent");
    if (!content) return;
    content.innerHTML = `<div class="full-loading"><span></span><b>Building the ${esc(requested)} research workspace</b><small>Loading verified financial evidence and current market context…</small></div>`;
  }

  function renderEmpty() {
    const content = $("companyOverlayContent");
    if (!content) return;
    content.innerHTML = `<div class="full-empty"><span>⌕</span><b>Choose a company first</b><p>Enter a company or ticker above to open the complete research workspace.</p></div>`;
  }

  function setCanvasSize(canvas, minimumHeight) {
    const ratio = Math.max(1, Math.min(2, window.devicePixelRatio || 1));
    const rect = canvas.getBoundingClientRect();
    const width = Math.max(260, rect.width || 360);
    const height = Math.max(minimumHeight, rect.height || minimumHeight);
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
    const context = canvas.getContext("2d");
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    return { context, width, height };
  }

  function drawPeerChart() {
    const canvas = $("fullPeerChart");
    const data = overviewCache;
    const snapshot = overviewMarketCache || {};
    if (!canvas || !data) return;
    const { context: ctx, width: W, height: H } = setCanvasSize(canvas, 190);
    const P = { left: 42, right: 14, top: 20, bottom: 35 };
    const points = [];
    if (finite(snapshot.pe) && finite(ratioMetric(data, "roe"))) points.push({ company: data.company, pe: Number(snapshot.pe), roe: Number(ratioMetric(data, "roe")), current: true });
    (data.peers || []).forEach((peer) => {
      const market = fullState.peerSnapshots.get(String(peer.company || "").toUpperCase());
      if (finite(market?.pe) && finite(peer.roe)) points.push({ company: peer.company, pe: Number(market.pe), roe: Number(peer.roe), current: false });
    });
    const xMax = Math.max(40, Math.ceil(Math.max(0, ...points.map((point) => point.pe)) / 10) * 10);
    const yMax = Math.max(20, Math.ceil(Math.max(0, ...points.map((point) => point.roe)) / 5) * 5);
    const plotW = W - P.left - P.right;
    const plotH = H - P.top - P.bottom;
    const x = (value) => P.left + Math.max(0, Math.min(xMax, value)) / xMax * plotW;
    const y = (value) => P.top + plotH - Math.max(0, Math.min(yMax, value)) / yMax * plotH;
    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = "#fbfdff";
    ctx.fillRect(P.left, P.top, plotW, plotH);
    ctx.fillStyle = "rgba(226, 237, 250, .44)";
    ctx.fillRect(P.left, P.top, plotW / 2, plotH / 2);
    ctx.fillRect(P.left + plotW / 2, P.top + plotH / 2, plotW / 2, plotH / 2);
    ctx.strokeStyle = "#dce6f1";
    ctx.lineWidth = 1;
    ctx.font = "10px Inter, Arial, sans-serif";
    ctx.textAlign = "right";
    ctx.textBaseline = "middle";
    for (let index = 0; index <= 4; index += 1) {
      const yy = P.top + plotH - index / 4 * plotH;
      ctx.beginPath(); ctx.moveTo(P.left, yy); ctx.lineTo(W - P.right, yy); ctx.stroke();
      ctx.fillStyle = "#6f83a1"; ctx.fillText(String(Math.round(yMax * index / 4)), P.left - 8, yy);
    }
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    for (let index = 0; index <= 4; index += 1) {
      const xx = P.left + index / 4 * plotW;
      ctx.beginPath(); ctx.moveTo(xx, P.top); ctx.lineTo(xx, P.top + plotH); ctx.stroke();
      ctx.fillStyle = "#6f83a1"; ctx.fillText(String(Math.round(xMax * index / 4)), xx, P.top + plotH + 8);
    }
    ctx.fillStyle = "#667b9b";
    ctx.font = "9px Inter, Arial, sans-serif";
    ctx.textBaseline = "top";
    ctx.textAlign = "left";
    ctx.fillText("High ROE", P.left + 8, P.top + 7); ctx.fillText("Low P/E", P.left + 8, P.top + 18);
    ctx.textAlign = "right";
    ctx.fillText("High ROE", W - P.right - 8, P.top + 7); ctx.fillText("High P/E", W - P.right - 8, P.top + 18);
    ctx.textBaseline = "bottom";
    ctx.textAlign = "left";
    ctx.fillText("Low P/E", P.left + 8, P.top + plotH - 7); ctx.fillText("Low ROE", P.left + 8, P.top + plotH - 18);
    ctx.textAlign = "right";
    ctx.fillText("High P/E", W - P.right - 8, P.top + plotH - 7); ctx.fillText("Low ROE", W - P.right - 8, P.top + plotH - 18);
    points.forEach((point) => {
      const px = x(point.pe), py = y(point.roe);
      ctx.beginPath(); ctx.arc(px, py, point.current ? 6 : 4.5, 0, Math.PI * 2);
      ctx.fillStyle = point.current ? "#0b63ce" : "#aac4e6";
      ctx.fill();
      if (point.current) {
        ctx.strokeStyle = "#ffffff"; ctx.lineWidth = 2; ctx.stroke();
        ctx.fillStyle = "#0c2d5a"; ctx.font = "700 10px Inter, Arial, sans-serif"; ctx.textAlign = "center"; ctx.textBaseline = "bottom"; ctx.fillText(String(point.company), px, py - 9);
      }
    });
    if (!points.length) {
      ctx.fillStyle = "#8292a8"; ctx.font = "11px Inter, Arial, sans-serif"; ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText("Peer P/E and ROE data unavailable", P.left + plotW / 2, P.top + plotH / 2);
    }
    ctx.save(); ctx.translate(12, P.top + plotH / 2); ctx.rotate(-Math.PI / 2); ctx.fillStyle = "#607797"; ctx.font = "10px Inter, Arial, sans-serif"; ctx.textAlign = "center"; ctx.fillText("ROE (%)", 0, 0); ctx.restore();
    ctx.fillStyle = "#607797"; ctx.font = "10px Inter, Arial, sans-serif"; ctx.textAlign = "center"; ctx.textBaseline = "bottom"; ctx.fillText("P/E (x)", P.left + plotW / 2, H - 1);
  }

  function drawCashBridge() {
    const canvas = $("fullCashBridge");
    const data = overviewCache;
    const snapshot = overviewMarketCache || {};
    if (!canvas || !data) return;
    const { context: ctx, width: W, height: H } = setCanvasSize(canvas, 155);
    const P = { left: 38, right: 10, top: 19, bottom: 39 };
    const revenue = rawMetric(data, "revenue");
    const operatingCash = finite(snapshot.operating_cash_flow) ? Number(snapshot.operating_cash_flow) : rawMetric(data, "cash_flow");
    const freeCash = snapshot.free_cash_flow;
    const reportedCapex = snapshot.capital_expenditure;
    ctx.clearRect(0, 0, W, H);
    if (![revenue, operatingCash, freeCash].every(finite)) {
      ctx.fillStyle = "#8292a8"; ctx.font = "11px Inter, Arial, sans-serif"; ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText("Revenue-to-free-cash-flow bridge unavailable", W / 2, H / 2);
      return;
    }
    const rev = Number(revenue), ocf = Number(operatingCash), fcf = Number(freeCash);
    const totalReinvestment = ocf - fcf;
    const capex = finite(reportedCapex) ? Math.min(Math.abs(Number(reportedCapex)), Math.abs(totalReinvestment)) : null;
    const afterCapex = finite(capex) ? ocf - capex : ocf;
    const other = finite(capex) ? afterCapex - fcf : null;
    const bars = [
      { label: "Revenue", from: 0, to: rev, value: rev, kind: "total" },
      { label: "Operating\ncosts", from: rev, to: ocf, value: ocf - rev, kind: "delta" },
      { label: finite(capex) ? "Capital\nexpenditure" : "Capex\nunavailable", from: ocf, to: finite(capex) ? afterCapex : ocf, value: finite(capex) ? -capex : null, kind: "delta" },
      { label: "Other", from: afterCapex, to: fcf, value: finite(other) ? -other : null, kind: "delta" },
      { label: "Free cash\nflow", from: 0, to: fcf, value: fcf, kind: "final" },
    ];
    const levels = bars.flatMap((bar) => [bar.from, bar.to]).filter(finite).map(Number);
    const min = Math.min(0, ...levels);
    const max = Math.max(1, ...levels);
    const span = max - min || 1;
    const plotW = W - P.left - P.right;
    const plotH = H - P.top - P.bottom;
    const y = (value) => P.top + (max - Number(value)) / span * plotH;
    ctx.strokeStyle = "#e0e8f1"; ctx.lineWidth = 1;
    ctx.font = "9px Inter, Arial, sans-serif"; ctx.textAlign = "right"; ctx.textBaseline = "middle";
    for (let index = 0; index <= 4; index += 1) {
      const value = min + span * index / 4;
      const yy = y(value);
      ctx.beginPath(); ctx.moveTo(P.left, yy); ctx.lineTo(W - P.right, yy); ctx.stroke();
      ctx.fillStyle = "#7385a0"; ctx.fillText(formatCompact(value, "").replace(/\.0$/, ""), P.left - 6, yy);
    }
    const gap = 11;
    const barWidth = Math.max(22, (plotW - gap * 4) / 5);
    const totalWidth = barWidth * 5 + gap * 4;
    const startX = P.left + (plotW - totalWidth) / 2;
    bars.forEach((bar, index) => {
      const left = startX + index * (barWidth + gap);
      const top = y(Math.max(bar.from, bar.to));
      const bottom = y(Math.min(bar.from, bar.to));
      const height = Math.max(2, bottom - top);
      ctx.fillStyle = bar.kind === "total" ? "#2e75d6" : bar.kind === "final" ? "#2fb57c" : "#a9b7ca";
      if (finite(bar.value)) ctx.fillRect(left, top, barWidth, height);
      else { ctx.strokeStyle = "#a9b7ca"; ctx.setLineDash([3, 3]); ctx.strokeRect(left, y(bar.from) - 1, barWidth, 2); ctx.setLineDash([]); }
      if (index < bars.length - 1) {
        ctx.strokeStyle = "#aebac9"; ctx.setLineDash([2, 2]); ctx.beginPath(); ctx.moveTo(left + barWidth, y(bar.to)); ctx.lineTo(left + barWidth + gap, y(bar.to)); ctx.stroke(); ctx.setLineDash([]);
      }
      ctx.fillStyle = "#17365f"; ctx.font = "700 9px Inter, Arial, sans-serif"; ctx.textAlign = "center"; ctx.textBaseline = "bottom";
      const valueText = finite(bar.value) ? `${Number(bar.value) < 0 ? "(" : ""}${formatCompact(Math.abs(Number(bar.value)), "")}${Number(bar.value) < 0 ? ")" : ""}` : "—";
      ctx.fillText(valueText, left + barWidth / 2, Math.max(11, top - 4));
      ctx.fillStyle = "#637894"; ctx.font = "9px Inter, Arial, sans-serif"; ctx.textBaseline = "top";
      const labelLines = bar.label.split("\n");
      labelLines.forEach((line, lineIndex) => ctx.fillText(line, left + barWidth / 2, P.top + plotH + 8 + lineIndex * 10));
    });
  }

  function drawFullCharts() {
    drawPeerChart();
    drawCashBridge();
  }

  async function hydratePeerSnapshots(data) {
    const company = String(data?.company || "").toUpperCase();
    if (!company || fullState.hydratedCompany === company) return;
    fullState.hydratedCompany = company;
    fullState.peerSnapshots.clear();
    const request = ++fullState.peerRequest;
    const peers = (data?.peers || []).filter((peer) => peer?.company).slice(0, 10);
    try {
      const payload = await getJSON("/api/market-snapshots", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({companies: peers.map(peer => peer.company)}),
        dedupe: false,
      });
      if (request === fullState.peerRequest) {
        Object.entries(payload?.snapshots || {}).forEach(([peerCompany, snapshot]) => {
          if (snapshot?.success !== false) fullState.peerSnapshots.set(String(peerCompany).toUpperCase(), snapshot);
        });
      }
    } catch (_) {
      // Missing peer quotes remain visibly unavailable; no synthetic value is inserted.
    }
    if (request !== fullState.peerRequest || $("companyModeOverlay")?.hidden) return;
    renderWorkspace(overviewCache, overviewMarketCache || {}, { preserveScroll: true });
  }

  function openSelectedFullWorkspace() {
    const overlay = $("companyModeOverlay");
    const requested = $("overviewCompany")?.value.trim().toUpperCase() || "";
    const cached = String(overviewCache?.company || "").trim().toUpperCase();
    if (!overlay) return;
    overlay.hidden = false;
    overlay.classList.add("full-research-open");
    document.body.classList.add("research-overlay-open");
    document.querySelectorAll(".company-mode-btn").forEach((button) => {
      const active = Number(button.dataset.mode) === 3;
      button.classList.toggle("active", active);
      button.setAttribute("aria-selected", String(active));
    });
    renderHeader(cached === requested ? overviewCache : null, cached === requested ? (overviewMarketCache || {}) : {}, requested);
    if (!requested) {
      renderEmpty();
      return;
    }
    if (!overviewCache || requested !== cached) {
      renderLoading(requested);
      loadOverview();
      return;
    }
    renderWorkspace(overviewCache, overviewMarketCache || {});
  }

  const originalOpenOverviewMode3 = openOverviewMode3;
  const originalCloseOverviewMode3 = closeOverviewMode3;
  const originalRenderOverviewMode1 = renderOverviewMode1;
  const originalShowEvidence = showEvidence;

  function sourceBasename(value) {
    const parts = String(value || "").replaceAll("\\", "/").split("/").filter(Boolean);
    return parts.at(-1) || "Unavailable";
  }

  function evidenceMetricLabel(metric) {
    const text = String(metric || "Metric").replaceAll("_", " ");
    return text.charAt(0).toUpperCase() + text.slice(1);
  }

  function evidenceValue(data, metric) {
    if (!finite(data?.value)) return "Unavailable";
    if (["debt_to_ebitda"].includes(metric)) return displayValue(data.value, "multiple", "");
    if (/margin|growth|^roe$|^roa$/.test(metric)) return displayValue(data.value, "percent", "");
    return displayValue(data.value, "money", currency(overviewMarketCache));
  }

  function closeEvidenceDialog(restoreFocus = true) {
    document.querySelectorAll(".evidence-modal-backdrop").forEach((dialog) => dialog.remove());
    document.body.classList.remove("evidence-dialog-open");
    const returnFocus = fullState.evidenceReturnFocus;
    fullState.evidenceReturnFocus = null;
    if (restoreFocus && returnFocus?.isConnected) requestAnimationFrame(() => returnFocus.focus());
  }

  async function showIsolatedEvidence(company, metric) {
    const normalizedCompany = String(company || "").trim();
    const normalizedMetric = String(metric || "").trim();
    if (!normalizedCompany || !normalizedMetric) return;
    const returnFocus = document.activeElement;
    try {
      const data = await getJSON(`/api/evidence/${encodeURIComponent(normalizedCompany)}?metric=${encodeURIComponent(normalizedMetric)}&basis=${encodeURIComponent(currentRatioBasis)}`);
      if (data?.success === false) throw new Error(data.error || "Evidence is unavailable.");
      closeEvidenceDialog(false);
      fullState.evidenceReturnFocus = returnFocus;
      const dialog = document.createElement("div");
      dialog.className = "evidence-modal-backdrop";
      dialog.dataset.fullDismiss = "evidence";
      dialog.innerHTML = `<section class="evidence-modal-card" role="dialog" aria-modal="true" aria-labelledby="evidenceDialogTitle">
        <header class="evidence-modal-head">
          <div><span>EVIDENCE TRACE</span><h2 id="evidenceDialogTitle">${esc(normalizedCompany)} · ${esc(evidenceMetricLabel(normalizedMetric))}</h2></div>
          <button type="button" class="evidence-modal-close" data-full-action="close-evidence" aria-label="Close evidence trace">×</button>
        </header>
        <div class="evidence-modal-grid">
          <div class="evidence-modal-stat"><span>Value</span><strong>${esc(evidenceValue(data, normalizedMetric))}</strong></div>
          <div class="evidence-modal-stat"><span>Period</span><strong>${esc(data.period_end || "Unavailable")}</strong></div>
          <div class="evidence-modal-stat"><span>Confidence</span><strong>${data.confidence == null ? "Unavailable" : esc(displayValue(Number(data.confidence) * 100, "percent", ""))}</strong></div>
          <div class="evidence-modal-stat"><span>Scope</span><strong>${esc(data.document_scope || "Unavailable")}</strong></div>
        </div>
        <div class="evidence-modal-formula"><span>Formula / basis</span><p>${esc(data.formula || "Verified library observation.")}</p></div>
        <dl class="evidence-modal-source">
          <div><dt>Source file</dt><dd title="${esc(sourceBasename(data.source_path))}">${esc(sourceBasename(data.source_path))}</dd></div>
          <div><dt>Source type</dt><dd>${esc(String(data.source_type || "Unavailable").replaceAll("_", " "))}</dd></div>
          <div><dt>Document quality</dt><dd>${data.document_quality == null ? "Unavailable" : `${Math.round(Number(data.document_quality))} / 100`}</dd></div>
        </dl>
      </section>`;
      document.body.appendChild(dialog);
      document.body.classList.add("evidence-dialog-open");
      dialog.querySelector(".evidence-modal-close")?.focus();
    } catch (error) {
      window.alert(error.message || "Evidence is unavailable.");
    }
  }

  // app.css is intentionally disabled on Dashboard. Replace the legacy generic
  // modal with a self-contained dialog whose styles live with this workspace.
  showEvidence = showIsolatedEvidence;

  openOverviewMode3 = function () {
    openSelectedFullWorkspace();
  };

  closeOverviewMode3 = function () {
    $("companyModeOverlay")?.classList.remove("full-research-open");
    originalCloseOverviewMode3();
  };

  renderOverviewMode1 = function () {
    originalRenderOverviewMode1();
    const overlay = $("companyModeOverlay");
    if (overviewMode === 3 && overlay && !overlay.hidden && overviewCache) {
      renderHeader(overviewCache, overviewMarketCache || {}, overviewCache.company);
      renderWorkspace(overviewCache, overviewMarketCache || {}, { preserveScroll: true });
    }
  };

  function updateTab(tab) {
    if (!tabDefinitions.some(([id]) => id === tab)) return;
    fullState.tab = tab;
    renderWorkspace(overviewCache, overviewMarketCache || {}, { preserveScroll: true });
  }

  function openComparison() {
    const firstPeer = overviewCache?.peers?.find((peer) => peer?.company && String(peer.company).toUpperCase() !== String(overviewCache.company).toUpperCase());
    if (!firstPeer) {
      window.alert("No peer company is available in the current research library.");
      return;
    }
    const a = $("compareA"), b = $("compareB");
    if (a) a.value = overviewCache.company;
    if (b) b.value = firstPeer.company;
    closeOverviewMode3();
    showView("compare");
  }

  document.addEventListener("click", (event) => {
    if (event.target?.matches?.('[data-full-dismiss="evidence"]')) {
      event.preventDefault();
      closeEvidenceDialog();
      return;
    }
    const control = event.target.closest?.("[data-full-action]");
    if (!control) return;
    event.preventDefault();
    const action = control.dataset.fullAction;
    if (action === "tab") updateTab(control.dataset.tab || "strength");
    else if (action === "evidence") showEvidence(overviewCache?.company || "", control.dataset.metric || "");
    else if (action === "close-evidence") closeEvidenceDialog();
    else if (action === "source" || action === "report") {
      closeOverviewMode3();
      showView("learn");
    } else if (action === "watchlist" || action === "alert") {
      const company = overviewCache?.company || $("overviewCompany")?.value || "";
      closeOverviewMode3();
      saveWatchlist(company);
    } else if (action === "compare") openComparison();
  });

  document.addEventListener("change", (event) => {
    if (event.target?.id !== "fullCategoryFilter") return;
    fullState.category = event.target.value || "all";
    const grid = $("fullDetailGrid");
    if (grid && overviewCache) grid.innerHTML = renderDetails(overviewCache, overviewMarketCache || {});
  });

  document.addEventListener("submit", (event) => {
    if (event.target?.id !== "fullOverlaySearch") return;
    event.preventDefault();
    const value = $("fullOverlayCompany")?.value.trim().toUpperCase();
    if (!value) return;
    const dashboardSearch = $("overviewCompany");
    if (dashboardSearch) dashboardSearch.value = value;
    renderLoading(value);
    loadOverview();
  });

  document.addEventListener("keydown", (event) => {
    const dialog = document.querySelector(".evidence-modal-backdrop");
    if (!dialog) return;
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopImmediatePropagation();
      closeEvidenceDialog();
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = [...dialog.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])')]
      .filter((element) => !element.disabled && element.getClientRects().length);
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable.at(-1);
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }, true);

  window.addEventListener("resize", () => {
    cancelAnimationFrame(fullState.resizeFrame);
    fullState.resizeFrame = requestAnimationFrame(drawFullCharts);
  }, { passive: true });

  // Retain a reference for diagnostics without changing the accepted app bundle.
  window.SolvAIFullResearch = { render: openSelectedFullWorkspace, draw: drawFullCharts, originalOpen: originalOpenOverviewMode3, originalEvidence: originalShowEvidence };
})();
