# SolvAI 45 system enhancement map

## Economic concepts and their correct product stage

| Concept | Correct feature | Stage | Correct use |
|---|---|---|---|
| Beneish eight-component M-score | Investment Research | Accounting quality | Investigative accounting-quality screen. It is not a fraud probability, audit conclusion, or trade signal. |
| Rule-based leverage, growth, and margin warnings | Investment Research | Accounting quality | Additional review flags beside the filing screen. |
| DCF, earnings value, dividend value, asset reference | Investment Research | Core value | Long-term company value under visible assumptions. |
| Bear / Base / Bull weights | Investment Research | Core value | Heuristic research weights used to combine scenarios; not calibrated probabilities. |
| Long-holding projection | Investment Research | Core value | Fading growth, value range, and dividend-aware holding scenarios. Not a short-term price forecast. |
| ATR and historical adverse excursion | Trade Planner | Stop research | Historical downside and market-structure references. |
| Fixed Fractional | Trade Planner | Position size | Units from equity risk budget divided by entry-to-stop risk. |
| Kelly / Half-Kelly | Trade Planner | Position size | Advanced cash-only sizing from evidence-adjusted resolved paths and payoff, with sample gates and hard caps. |
| R-multiple | Trade Planner | Reward target | Defines target distance after the stop; never calculates exposure by itself. |
| Volatility Targeting | Portfolio Risk | Exposure overlay | Scales portfolio exposure using portfolio volatility. |
| Risk Parity | Portfolio Risk | Allocation | Allocates across multiple holdings by risk contribution. |
| Technical indicators and VSA | Indicators & VSA | Market timing research | Conditional price/volume interpretation and invalidation levels. |
| CPI, policy rate, real retail momentum, labor deterioration, gasoline | Dashboard Macro / Macro Regime | Current macro context | Transparent current-fit scenarios with official dates and no probability claim. |
| Event evidence shares | Event Scenarios | Outcome comparison | Normalized evidence shares. Probability language should be used only after validation and calibration. |
| VaR / Expected Shortfall / drawdown / correlation | Portfolio Risk | Portfolio measurement | Historical portfolio loss and concentration diagnostics. |

## Duplications removed

- Position sizing now has one implementation in `engine/position_sizing.py`.
- Technical indicators now have one implementation in `engine/technical.py`.
- Market-history retrieval and batching now live in `engine/market_data.py`.
- Provider and evidence caching use `engine/provider_cache.py`.
- The macro meaning and feature ownership rules are centralized in `engine/economic_semantics.py`.
- Valuation and Trade Planner front-end controllers register explicitly instead of replacing global functions.
- Peer snapshots and world-market histories are requested in batches rather than repeated browser calls.

## Accuracy and smoothness changes

- Nominal retail sales are deflated by aligned CPI before the scenario engine interprets consumer momentum.
- Labor deterioration uses a Sahm-style three-month-average signal; a plain three-month change is only a labelled fallback when a full window is unavailable.
- Gasoline is half-weighted in the five-signal macro score because headline CPI already includes energy.
- The Beneish TATA component divides accruals by current-period total assets, matching the published model basis.
- Kelly modes require at least 40 resolved historical paths and are capped at 25% / 12.5% cash allocation.
- Missing provider or report data stays unavailable. Manual overrides are visibly labelled and are not saved as provider facts.
- Market, report-evidence, and FRED results use persistent stale-aware caches. Refresh intervals follow source cadence instead of constant high-frequency polling.
- Portfolio returns use overlapping observations only; VaR, Expected Shortfall, drawdown, correlation, and contribution are kept together in Portfolio Risk.

## Architecture decision

The application remains Python + Flask. Rewriting it in a new language would add migration risk without fixing the actual bottlenecks, which were repeated downloads, duplicated calculations, and uncoordinated front-end requests. The enhancement therefore keeps the stable platform and improves boundaries, batching, caching, and contracts.

The next justified scale step is not a language rewrite. It is to move slow scans and large backfills to a background worker while keeping the current HTTP API. A separate time-series store becomes useful only when the number of users, instruments, or intraday observations makes SQLite and local caches measurably insufficient.

## Refresh policy

| Data | Normal behavior |
|---|---|
| Daily / intraday market snapshots | Shared short-lived cache; batch route for groups; explicit refresh remains available. |
| Company fundamentals | Five-minute live cache with a one-day stale fallback during provider failure. |
| FRED monthly / weekly releases | Six-hour cadence cache; the policy-rate daily series can refresh every 15 minutes. |
| Company and macro news | Ten-to-fifteen-minute evidence cache; dashboard polling is ten minutes. |
| Local reports | Updated by **Scan all reports**; parser-version changes force a reparse. |

## Rule for adding a feature

1. Name the user decision and horizon first: accounting quality, long-term value, trade planning, portfolio risk, macro context, or event comparison.
2. Reuse the canonical market, indicator, sizing, and cache modules. Do not copy formulas into a route or JavaScript file.
3. State the unit, observation date, source, transformation, and missing-data rule for every input.
4. Distinguish a score, research weight, evidence share, historical frequency, and calibrated probability in both the API and UI.
5. Add contract tests for the formula, feature placement, method switching, unavailable state, and provider fallback.
6. Batch independent requests and assign a refresh interval that matches the source cadence.
