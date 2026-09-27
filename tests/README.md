# SolvAI 45.0 — Economic and System Foundation

Current local-testing release: **45.0.0**. It preserves the accepted SolvAI39 dashboard and original login background while separating long-term Investment Research from short-term Trade Planning, centralizing duplicated calculations, batching repeated market requests, and adding cadence-aware persistent caches.

Investment Research now contains only Accounting Quality and Core Value. Trade Planner separately owns historical downside, stops, R-multiple targets, and the three single-company sizing modes: Fixed Fractional, capped Kelly, and Half-Kelly. Volatility Targeting and Risk Parity remain portfolio methods. Beneish output is an investigative screen—not a fraud probability; Bear/Base/Bull percentages are research weights; dashboard retail momentum is inflation-adjusted; labor deterioration uses a Sahm-style signal; and gasoline is half-weighted because headline CPI already includes energy.

For local setup, read **README_FIRST.txt** and run `update.bat` once, then `run.bat`. For safe future upgrades, read **UPDATE_AND_RUN.md**. The complete concept ownership, refresh policy, and extension rules are in **SYSTEM_ENHANCEMENT.md**.

## Previous 44.7 release notes

Current local-testing release: **44.7.2**. It preserves the accepted SolvAI39 dashboard and original login background while making Core Value automatic by default, adding an explainable long-holding outlook, and turning the position-sizing library into a real calculator selector.

Patch 44.7.2 closes the method-switch interaction gap. The method-aware loader now owns both the Calculate button and every method-card change, prevents the older request from overwriting the selected result, disables browser caching for recalculations, and verifies that the server returned the requested method. Allocation percentages are now comparable even when account equity is blank; account equity is needed only to convert the percentage into currency and units. The result shows raw versus applied allocation and explains when two applied results match because both reached the 100% cash cap.

Patch 44.7.1 connects Fixed Fractional, Kelly, Half-Kelly, and Volatility Targeting to the position-sizing API. Changing an active mode now recalculates capital allocation, units, position value, and planned stop loss. Kelly combines training and holdout paths, shrinks thin evidence toward a neutral 50% prior, and withholds a position when the adjusted fraction is not positive. Volatility Targeting blends 20-day and 60-day realized volatility. Every method is cash-only and capped at 100% of available account equity; SolvAI never introduces leverage automatically. R-multiple is correctly separated as the reward-target rule, while Risk Parity remains in the multi-holding Portfolio Risk workspace.

Release 44.7.0 resolves price, shares outstanding, cash flow, EPS, dividend, book value, currency, historical growth, margins, leverage, and ROE from provider data or verified reports wherever available. Most users now enter only a company and, optionally, their shares held, average cost, holding period, and dividend-reinvestment preference. Technical assumptions remain available in one collapsed expert section and are never silently invented when evidence is missing.

The long-holding model uses three bear/base/bull paths. Near-term growth is blended from independent provider and filing evidence, winsorized, quality-shrunk toward a stable rate, and faded year by year rather than held constant. Terminal value blends earnings and free-cash-flow methods when both are available; a clearly labelled fallback is used only when the underlying per-share evidence is unavailable. Results show annualized return, terminal value, modeled dividends, the user's estimated portfolio value, the inputs used, and limitations. Scenario weights express research evidence fit—not calibrated probabilities, promises, or investment advice.

## New in SolvAI 44.7

- Replaces the long manual valuation form with an automatic evidence-first workspace.
- Keeps only understandable portfolio context in the main path: shares held, average cost, holding period, and optional modeled dividend reinvestment.
- Shows exactly which inputs were resolved automatically, manually overridden, or unavailable.
- Adds three long-holding paths with a year-by-year projection chart and a research-weighted expected range.
- Improves growth normalization with multiple evidence sources, outlier caps, data-quality shrinkage, and convergence toward a stable long-run rate.
- Projects EPS, free cash flow, and dividends independently, avoiding a single-multiple shortcut when richer evidence exists.
- Preserves every previous Risk Assessment calculation, its progressive Review → Value → Plan flow, the accepted dashboard, and the original login background.

## New in SolvAI 44.6

Release 44.6.0 turns Risk Assessment into a progressive three-step workspace. Only the current step is shown; risk review unlocks Core Value, valuation unlocks Position Plan, and the persistent tracker makes active, completed, and locked states explicit.

## New in SolvAI 44.4

- Rebuilds Risk Assessment as a three-step workflow: review filing-based financial risk, test core value, then define downside and position size.
- Uses one company search across the financial-risk, valuation, and trading-risk steps so the user does not have to re-enter the same company.
- Reorganizes the financial-risk result into a decision header, four essential KPIs, rule-based warnings, the eight Beneish-style inputs, same-period movements, missing-data notices, and expandable model limitations.
- Adds keyboard-focusable circular information controls for unfamiliar terms and inputs. Hover or focus explains M-score, the relative CDF proxy, every Beneish component, valuation assumptions, drawdown P75, forward MAE P80, ATR14, expectancy, position sizing, and other risk concepts.
- Adds a six-method guide for Fixed Fractional, Fixed Risk / R-multiple, Kelly Criterion, Half-Kelly / Fractional Kelly, Volatility Targeting, and Risk Parity.
- Clearly labels which methods the current single-company planner calculates. Kelly variants remain reference-only; Volatility Targeting routes to Indicators & VSA; Risk Parity routes to Portfolio Risk.
- Rebuilds the trade output around entry, stop, target, historical outcome evidence, Fixed Fractional position size, market-structure references, holdout evidence, and a visible limitations warning.
- Keeps every existing risk API, valuation calculation, historical trading-risk calculation, dashboard feature, permission, route, and the original login background intact.

## Patch 44.3.1

- Replaces the long stacked scenario section with a compact two-pane workspace: ranked scenarios on the left and the selected scenario's evidence, consequence, transmission path, and confirmation signals on the right.
- Removes the duplicated market-outlook paragraph from the peak-comparison box so each section has one clear job.
- Increases scenario and comparison text sizes, improves spacing and hierarchy, and keeps all warnings readable instead of truncating them into one-line chips.
- Updates only the scenario workspace when a row is selected. The five charts are no longer reconstructed, so hover, focus, and chart state remain stable.
- Adds stronger keyboard focus treatments and preserves a clean stacked layout on tablet and mobile widths.

## New in SolvAI 44.3

- Adds a five-row scenario outlook directly below the CPI, Fed rate, retail sales, unemployment, and gasoline charts.
- Ranks **higher for longer**, **soft landing**, **inflation re-acceleration**, **consumer slowdown**, and **disinflation with rate cuts** from fixed, visible rules applied to the latest official observations.
- Shows signal strength on a 1–5 scale with half steps. The score describes current evidence fit; it is not presented as a probability or forecast.
- Lets the user select any scenario to inspect all five contributing readings, the transmission path, the likely market consequence, and the releases that would confirm the path.
- Re-ranks deterministically when refreshed official data changes and keeps missing inputs visible rather than inventing evidence.
- Preserves the offline official FRED snapshot, chart range controls, comparisons, peaks, warnings, login background, and every existing feature.

### Patch 44.2.1

- Fixes all five macro charts appearing as **Unavailable** when a local machine, VPN, firewall, DNS service, or temporary provider outage prevents a live FRED request.
- Continues to prefer and automatically retry live official releases.
- Falls back to a packaged official FRED snapshot captured on September 20, 2026, with 320 published observations per series.
- Clearly labels cached snapshot mode in the dashboard instead of presenting it as live data.
- Keeps the original observation dates, FRED links, previous-reading comparison, selected-period peaks, warnings, and conditional outlook working offline.
- Never generates replacement values. A series becomes Unavailable only when both its live source and packaged official snapshot are absent.

## New in SolvAI 44.2

- Replaces the lower **Market Performance** and **Research Activity** cards with five synchronized interactive graphs: Consumer Price Index, effective federal funds rate, Retail Sales Index, unemployment rate, and regular gasoline price.
- Uses official FRED series `CPIAUCSL`, `FEDFUNDS`, `RSXFS`, `UNRATE`, and `GASREGW`. Retail sales is transparently normalized to January 2020 = 100; source values and release dates remain traceable from each graph.
- Adds shared 12-month, 24-month, and 5-year periods, selected-period peak markers, pointer tooltips, and keyboard chart inspection.
- Adds a full-width summary comparing every latest observation with its immediately previous release and reporting the selected-period peak.
- Adds deterministic warning thresholds and a conditional long-run market scenario based only on published observations. The scenario is explicitly not a forecast or investment recommendation.
- Keeps missing provider data unavailable instead of inserting demo, random, or substitute readings.
- Keeps Company Overview, Market & Economic News, Quick Access, every research feature, and the original login background intact.

Patch 40.0.2 keeps every Summary detail reachable in a dedicated scroll area and lets Metrics expand across the space released when the Financial AI assistant is hidden. Market news remains in its original right-hand position on wide screens and follows the expanded panel on narrower screens.

Patch 40.0.1 initializes Dashboard styling before the first paint so the Financial AI assistant has the same complete layout immediately after sign-in and after returning from another feature. It also restores the original photographic background on the sign-in page.

## New in SolvAI40

- Leaves the SolvAI39 dashboard markup, dashboard styles, quantitative styles, shared dashboard refresh layer, and application JavaScript unchanged.
- Rebuilds Compare Companies, Stock Analytics, Indicators & VSA, Risk Assessment, Macro Regime Monitor, Event Probability, Company News, Reports, Portfolio Risk, Watchlist, Model Guardian, and Data Health around a consistent task-first layout.
- Separates primary inputs from optional or advanced evidence so common research tasks require fewer decisions.
- Rebuilds sign-in and access requests with clearer language, larger controls, and a simpler security explanation.
- Rebuilds Account Security and the administrator Access Center, including an explicit Viewer / Editor / Administrator permission guide.
- Adds regression locks for the accepted dashboard, feature hooks, account hooks, stylesheet order, and the corrected pending-registration status flow.

## Access approval preserved from SolvAI37

## New in SolvAI37

- Public registration now creates a **pending access request**, not an active user account or signed-in session.
- Access requests are stored in the persistent SQLite database and appear automatically in **Account → Access Center**.
- Administrators can inspect the requester name, email, reason, request time, privacy-safe network identifier, and device description; passwords and password hashes are never displayed.
- Approval creates an active Viewer or Editor account using the requester’s existing one-way password hash. Administrator access remains available only through controlled manual account creation.
- Rejection removes the temporary credential hash while retaining an auditable decision record. Reviewed requests are pruned with the existing security-retention policy.
- Approval and rejection are CSRF-protected, administrator-only, workspace-scoped, transaction-safe, and included in the administrator audit trail.

Read **ACCESS_APPROVAL.md** for the exact administrator workflow.

## Preserved from SolvAI36

- Adds a dedicated **Indicators & VSA** workspace for RSI, MACD, ADX, MFI, Chaikin Money Flow, ATR, Bollinger Bands, moving-average structure, relative volume, and price-volume context.
- Detects recent VSA conditions such as no supply, no demand, stopping volume, supply entering, possible climaxes, and effort-versus-result divergence. Every event includes a separate confirmation requirement.
- Adds a **Trap Radar** for failed breakouts, failed breakdowns, low-volume breakouts, bull-trap risk, and bear-trap risk.
- Estimates an explainable Wyckoff context—Accumulation, Markup, Distribution, Markdown, or Trading Range—while labeling the result as a heuristic rather than proof of institutional positioning.
- Produces a conditional entry zone, breakout trigger, invalidation, two reward/risk references, a wait window, a holding window, and explicit sell/review rules. Output is a research plan, never an automatic order or guaranteed target.
- Adds Conservative, Balanced, and Active guardrail profiles. Optional account value and same-industry exposure calculate a capped position size with three staged entries.
- Ranks up to ten companies as research priorities. Newly uploaded and indexed company statements automatically feed the next analysis; missing statements lower confidence and remain visible.
- Adds an editable `data/company_symbols.json` mapping. Vietnam tickers default to `.VN`; exact international Yahoo symbols can use `YF:`, for example `YF:AAPL`.
- Adds deterministic VSA/trap/position-sizing tests, route and CSRF tests, responsive CSS checks, and versioned deployment health reporting.

Read **INDICATORS_VSA.md** for interpretation and company-update instructions.

## Preserved from SolvAI33.2 and SolvAI35

The corrected sidebar keeps the Financial AI identity stationary while navigation and company entries scroll in their own region. The complete feature layout, valuation engine, private watchlists, Event Probability, account controls, and calibrated Stock Analytics remain available.

Patch 33.2.2 separates the fixed sidebar identity header from its scrollable navigation and company library. Active features remain visible inside that dedicated region without allowing navigation rows to overlap the Financial AI brand.

Patch 33.2.1 prevents long automatic news feeds from stretching the complete dashboard row, restores internal news scrolling, removes nested borders from wrapped search/chat inputs, and keeps the Company Overview mode selector stable at narrow card widths.

## New in SolvAI33.2

- Keeps the complete feature-based navigation and every existing research action while improving hierarchy, spacing, and reading width across the workspace.
- Enlarges sidebar labels and targets, clarifies the Company Overview modes as **Summary**, **Metrics**, and **Full**, and prevents dashboard cards from clipping longer results.
- Protects checkboxes, radio buttons, icon buttons, filters, and compact tabs from broad legacy input/button rules.
- Replaces viewport-width shell calculations with scrollbar-safe widths and adds a labeled, horizontally scrollable navigation strip on phones.
- Applies consistent field sizing, keyboard focus, responsive overflow, and readable text to sign-in, account-security, and administrator pages.
- Adds CSS regression checks for stylesheet structure, cascade order, feature/action retention, control protection, and responsive shell safeguards.

## New in SolvAI32 Quant Part 2

- Risk Assessment now evaluates five traceable business drivers: forward revenue growth, forward EPS growth, operating-margin change, net debt/EBITDA, and return on equity.
- Available provider or local-report evidence is used automatically. Optional user assumptions are visibly labelled as unverified and are not presented as provider facts.
- Bear/Base/Bull cases begin at a 25%/50%/25% research prior. Driver direction, coverage, and valuation-data quality produce a bounded tilt; low evidence shrinks the result back toward the prior.
- The interface shows scenario weights, a probability-weighted fair value and entry threshold, Bear/Bull returns versus market, and an upside/downside ratio.
- A forward revenue index and one-year EPS projection are shown only when their inputs exist. Missing data remains **Unavailable**.
- These percentages are explicitly described as transparent heuristic research weights. They are not options-implied, analyst-consensus, or historically calibrated probabilities.

## New in SolvAI32 Quant Part 1

- Stock Analytics now evaluates 1-week, 1-month, 3-month and 12-month horizons separately instead of presenting one five-day model as a general outlook.
- Each horizon uses three expanding walk-forward validation windows with a horizon-length gap between training and validation, preventing training labels from reaching into the following test period.
- Logistic Regression and Random Forest probabilities are combined, then sigmoid-calibrated using out-of-sample predictions only. Calibration is trained on the earlier half and scored on the untouched later half.
- Results expose accuracy, historical base-rate accuracy, Brier score, baseline Brier score, Brier skill, log loss, validation sample counts and fold stability.
- A directional signal is automatically suppressed when it does not clear held-out probability-skill and effective-history checks. An unsupported result is shown as **Uncertain**, not forced into Up or Down.
- The interface displays relative feature importance with an explicit reminder that importance is historical and non-causal.
- The existing DCF/P-E/DDM/Gordon/asset valuation, valuation monitor, Event Probability, portfolio risk and trading-risk planner remain available.

Options-implied distributions and analyst-consensus curves remain deferred. They require trusted additional data and must not be fabricated for securities without sufficiently liquid or licensed coverage.

# SolvAI 30 — Private Valuation Monitor

Current phased release: **30.0.0**. It preserves the SolvAI26 dashboard, account/privacy controls, and SolvAI29 Decision Center, then adds account-private watchlists, explainable valuation alerts, saved valuation history, and a more readable dashboard assistant.

### SolvAI30 Private Valuation Monitor

- Adds a personal **Watchlist & Alerts** workspace scoped to the signed-in user and workspace.
- Saves provider/evidence-backed valuation snapshots and compares market price with Bear, Base, and Bull values over time. Manual-input calculations are deliberately not stored.
- Creates explainable alerts when a watched price enters the research range, moves above the modeled range, fair value changes materially, or newer reporting evidence appears.
- Lets each user edit entry, above-range, and material-change thresholds plus the alert types they want to monitor.
- Shows unread alert status in the existing header notification control without removing settings or account access.
- Restyles the Financial AI chat as a contained, readable conversation panel while preserving the dashboard grid height and mobile behavior.

### SolvAI29 Decision Center

- Recalculates DCF, normalized P/E, two-stage DDM, Gordon growth, and asset value under Bear, Base, and Bull assumptions.
- Shows the source and reporting date for every core financial input; user overrides remain calculation-only and are never saved.
- Scores evidence confidence from method coverage, agreement, market freshness, and input traceability, with visible warnings explaining deductions.
- Adds a 3×3 DCF sensitivity table and a visual ladder for deep-value, preferred-entry, fair-value, and above-range thresholds.
- Separates 0–12 month, 1–3 year, and 3–5 year research horizons and lists the events that should trigger recalculation.

## New in 26.2

- Core Value Lab calculates per-share Equity DCF, normalized P/E, two-stage Dividend Discount, Gordon Growth, and asset/book-value references when the required inputs exist.
- Every method exposes its input values and sources, formula, sensitivity range, applied blend weight, interpretation, and limitations. A missing input stays **Unavailable** and is excluded rather than substituted with an unrelated metric.
- The final research summary shows the modeled fair-value range, a configurable margin-of-safety entry level, the gap to current market price, method coverage, and a 3–5 year review framework when sufficient evidence exists.
- Dividend history is used to infer a payment cadence and a broad next-payment window. The interface clearly identifies this as a historical estimate, never a declared date.
- If the market provider is unavailable, users can enter optional verified price, share-count, free-cash-flow, EPS, dividend, and book-value inputs. These overrides are labelled in the calculation and are not saved.
- Company Overview keeps fast initial loading: open Mode 3 or select **Core value** to run the deeper market request only when needed.
- The shared sidebar is 20 px wider on desktop, with larger feature labels and improved vertical spacing. Collapsed and narrow-screen behavior remains intact.

Valuation output is an assumption-sensitive research estimate—not personalized investment advice or a guaranteed target. Verify current prices and declared dividends with the issuer or exchange.

Phase 2 makes Event Probability history, saved forecasts, notes, outcomes, calibration, recent companies, and pinned companies private to each authenticated user. A nonce-based Content Security Policy blocks inline script handlers; research links accept only HTTP(S); each request receives a trace ID and privacy-conscious JSON log; `/api/ready` verifies storage readiness. Production dependencies are fully resolved in `requirements.lock` with hashes and verified in CI.

No database, report, password, session secret, `.env`, cache, or user upload is included in the release. For the closed-beta deployment sequence, read **PRODUCTION_DEPLOYMENT.md** and **PHASE_2_NOTES.md**. Local Docker usage remains `docker compose up -d --build` followed by `docker compose ps`.

SolvAI 21 adds a secure account layer in front of the complete SolvAI20 dashboard. The supplied login template has been redesigned to match the Financial AI workspace, while the dashboard and research systems remain intact.

## New in SolvAI 21

- Sign in and create-account flows lead directly to the SolvAI20 workspace.
- Passwords are salted and one-way hashed with PBKDF2-SHA256; neither the application nor the administrator page can display them.
- Signed HTTP-only cookies, server-side revocable sessions, CSRF checks, and temporary lockout after repeated failures protect account access.
- Self-registration creates a pending database request. An administrator must approve it as Viewer or Editor before the account can sign in.
- Administrators can open **Account → Access Center** to manage roles, active status, lockouts, resets, sessions, and safe activity metadata.
- Every user can open **Account → Account Security** to change their password and sign out unfamiliar devices.
- The dashboard greeting, avatar, account panel, and sign-out action now use the authenticated user's profile.

For a public deployment, set `SOLVAI_SECRET_KEY`, `SOLVAI_ADMIN_EMAIL`, and `SOLVAI_ADMIN_PASSWORD` before first startup, then set `SOLVAI_ALLOW_REGISTRATION=0` if only invited accounts should be allowed. Set `SOLVAI_SECURE_COOKIES=1` when the site is behind HTTPS. Do not commit real secrets to `.env`.

The built-in account layer is designed for a private or carefully managed self-hosted workspace. Before open public registration, add verified email delivery, self-service recovery, a multi-user production database, privacy terms, and external monitoring.

Account recovery is available without exposing a password:

```bat
python manage_users.py list
python manage_users.py create-admin owner@example.com --name "Workspace Admin"
python manage_users.py reset-password owner@example.com
```

The account database is stored with the rest of the persistent SolvAI data. Deleting `storage/financial_ai.sqlite3` deletes both research indexing and account records, so back it up before any reset.

## SolvAI 20 trust and stability layer

SolvAI 20 keeps the established financial dashboard and analysis features while adding a shared reliability and research-integrity layer.

## New in SolvAI 20

- One coordinated browser state prevents duplicate initialization, combines identical requests and cancels outdated company lookups.
- The company picker supports fuzzy ticker matching, keyboard navigation, recent companies and pinned companies.
- Event Probability includes evidence-quality scoring, source balancing, model-sensitivity ranges and “what would change this?” signals.
- Forecast Lab saves research, stores notes, records observed outcomes and calculates calibration and multiclass Brier scores.
- Data Health reports provider availability, freshness, latency, evidence counts and cached-fallback use.
- Source cards group repeated headlines, prioritize stronger sources and discount cached evidence.
- Shared typography, controls, responsive layouts and account/settings navigation are applied throughout the workspace.

Existing reports and databases are migrated in place. Forecast resolutions never rewrite the original forecast result.

## 0. Button/navigation fix in V6.2

If the sidebar and Analyze buttons appear completely dead, the browser is not the problem: the previous `static/app.js` had a JavaScript syntax error in `renderGuardian()`. Because the browser could not parse the file, **none of the JavaScript ran**, so navigation and all `onclick` actions stopped working.

This V6.2 edition fixes that syntax error and adds a cache-busting version to the script URL so the browser loads the corrected JavaScript.

If you replace files while the app is open, a normal refresh is usually enough; if your browser still shows the old interface, use `Ctrl + F5` once.


## The bug fixed in this version

The previous edition could discover a company and count its PDFs but still show `Not available` for nearly every financial metric. The main reason was the report extractor: it searched almost entirely for English phrases such as `revenue`, `net income`, and `total assets`, while the supplied Vietnamese reports use labels such as `Doanh thu thuần`, `Lợi nhuận sau thuế`, `TỔNG CỘNG TÀI SẢN`, etc. Several FPT/VNZ PDFs are also image-based, so `pypdf` returns little or no text.

This edition changes the ingestion pipeline:

```text
Industry folder
      ↓
Company folder       ← company identity comes from here
      ↓
Any filename.pdf     ← filename no longer needs a special format
      ↓
Native PDF extraction
      ↓
OCR fallback for scanned PDFs (Vietnamese + English)
      ↓
Label-driven financial extraction
      ↓
Derived ratios
      ↓
SQLite research library
      ↓
User-friendly overview / comparison / risk / stock screens
```

## 1. Add reports

You can manually download a report and put it here:

```text
FIAI/
└── reports/
    └── Companies_reports/
        ├── Technology/
        │   ├── FPT/
        │   │   ├── FPT_Q1_2026.pdf
        │   │   └── literally_any_name.pdf
        │   ├── CMG/
        │   └── VNZ/
        └── Retail/
            └── PNJ/
```

**The filename does not need to contain the ticker.** The folder name is authoritative.

## 2. Install

Windows CMD:

```bat
cd C:\path\to\FIAI
python -m pip install -r requirements.txt
```

Make sure Ollama is optional. The quantitative report engine works without it.

## 3. Run

```bat
python app.py
```

Then open:

`http://127.0.0.1:5000`

The application opens without performing an expensive full scan. Use **Scan / re-index** after adding or changing reports.

## 4. If you add a new report later

Either:

1. put it in the correct `Industry/Company` folder and click **Scan / re-index**, or
2. use **Scan & Learn → Add a report**.

No Python code changes are required.

## 5. Why this version can read the supplied PDFs

The supplied archive contains both text PDFs and image/scanned PDFs. The reader now uses `pypdf` first. When a PDF contains too little extractable text, it falls back to PyMuPDF + Tesseract using `vie+eng` when available.

The extractor also recognizes common Vietnamese financial-statement labels and derives:

- revenue
- net income
- operating profit
- operating cash flow
- assets
- equity
- receivables
- current assets
- current liabilities
- short/long-term debt
- depreciation
- selling + administrative expense
- EBITDA when operating profit + depreciation are available
- revenue growth
- EBITDA margin
- net margin
- cash-flow margin
- debt / EBITDA
- ROA / ROE when reported or safely derivable

## 6. Important limitation

OCR and financial-statement extraction are not accounting software. A report can contain unusual layouts, multiple columns, restatements, or OCR errors. The application therefore keeps a data-coverage indicator and displays missing values as `Unavailable` rather than silently inventing them.

## 7. Old database

The database is automatically migrated when possible. If you want a completely clean rebuild, stop the app and delete:

```text
storage/financial_ai.sqlite3
```

Then run `python app.py` again.

## SolvAI 44.1 scan coverage and evidence dialog

Company Overview now receives the complete verified statement set produced by
the report scanner: revenue bridge, profit lines, expenses, depreciation,
balance-sheet totals, working-capital inputs, debt, receivables, PPE, and
operating cash flow. The Full workspace presents 72 report, derived, and market
indicators, with scanned values taking priority over market fallbacks.

The parser version is now 13.5.0. Run **Data Sources & Reports -> Scan all
reports** once after upgrading; the version change makes that scan bypass older
cached parser results and rebuild the observations from the source reports.

Verified Report uses an isolated, responsive dialog that remains bounded above
the Dashboard and Full overlay even though the Dashboard does not load app.css.
The dialog supports outside-click and Escape dismissal, restores focus, wraps
long content, and displays only the source filename rather than a local path.

## SolvAI 40.1 Full Research workspace

Company Overview -> Full now uses the selected option 2 design with a fixed
company summary rail, category tabs, a source-labelled comparison matrix, peer
position and revenue-to-free-cash-flow charts, and an expanded set of detailed
financial, market, cash-flow, shareholder, and evidence indicators. The layer
is additive: the accepted Dashboard, Summary, Metrics, and sign-in background
remain unchanged.

### OCR troubleshooting (Windows)
Financial AI now prefers the real Tesseract installation discovered from PATH or the standard `C:\Program Files\Tesseract-OCR\tesseract.exe` location. It then resolves `tessdata` beside that executable and verifies both `eng` and `vie` before OCR.

Run `diagnose.bat` before scanning. A healthy installation should show a configured Tesseract path, a resolved `tessdata` directory, and `Required languages: True` for `eng` and `vie`.

Run `scan.bat` after upgrading the parser. Failed or empty parses are not considered valid cached scans.

## V15 Professional Research Layer

This build keeps the V14 financial extraction/scanner and trade-risk engine intact and adds a presentation/decision layer:

- Evidence trace for displayed KPIs.
- Latest / TTM / Annual ratio views.
- Research timeline and anomaly highlights.
- Report-health panel.
- Portfolio risk analysis with volatility, drawdown, concentration, correlation and risk contribution.
- Research brief endpoint and dashboard action.
- Conversational assistant remains local/evidence-backed with optional Ollama.
