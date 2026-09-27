SolvAI 45.0 — Foundation Normal Test
====================================

This is the full private/local testing build. It is not the share-safe demo.
The accepted SolvAI39 dashboard and the original login background are preserved.

FASTEST WINDOWS START

1. Extract the entire ZIP to a normal folder.
2. Double-click update.bat once. It creates an isolated .venv, installs the
   required Python packages, and runs the environment diagnostic.
3. Double-click run.bat.
4. Open http://127.0.0.1:5000 if the browser does not open automatically.

WHAT CHANGED IN 45.0

- Investment Research is now a focused two-stage journey:
  Accounting quality -> Core value / long-holding outlook.
- Trade Planner is a separate short-horizon journey. It no longer appears as
  a valuation stage or mixes position sizing with company value.
- Fixed Fractional, capped Kelly, and Half-Kelly use one canonical sizing
  engine. Changing the selected method always triggers a new calculation.
- R-multiple is only a reward-target rule. Volatility Targeting and Risk Parity
  are portfolio tools, not single-company sizing methods.
- Beneish-style output is correctly labelled an accounting-quality screen,
  not a fraud probability. Its TATA denominator uses current-period assets.
- Bear / Base / Bull percentages are research weights, not probabilities.
- Event results are presented as evidence shares unless a future model is
  explicitly calibrated and validated as a probability model.
- Dashboard macro scenarios use inflation-adjusted retail momentum, a
  Sahm-style labor-deterioration signal, and half weight for gasoline because
  headline CPI already contains energy.
- Shared market history, indicator, position-sizing, evidence, and provider
  caches remove repeated work. Peer and world-market requests are batched.
- Official data uses cadence-aware refresh intervals and stale official
  snapshots during temporary provider outages. Missing data is never invented.

UPDATING LATER WITHOUT LOSING YOUR WORK

Read UPDATE_AND_RUN.md before replacing a version. The short rule is:

- Close SolvAI.
- Back up storage, reports, company_symbols.json, and your environment settings.
- Put the new code in a new folder, then copy those private data items into it.
- Run update.bat, then run.bat.
- Do not replace new engine, static, templates, data, or tests folders with old
  versions; doing so would restore old formulas or interface code.

For Docker, keep the existing solvai_financial_data volume and run:

    docker compose up -d --build
    docker compose ps

The database initialization is additive. Existing account, watchlist, report,
and forecast data remain in the preserved storage location.

VERIFICATION

This release passes the complete automated suite: 189 tests, with 9 optional
environment-dependent tests skipped. See SYSTEM_ENHANCEMENT.md for the economic
concept map, architecture decisions, refresh policy, and extension rules.

IMPORTANT RESEARCH BOUNDARY

SolvAI produces evidence-led research scenarios and historical risk estimates.
It does not place orders, guarantee prices, or provide a personalized investment
recommendation. Provider and report dates remain visible so the user can judge
freshness and coverage.
