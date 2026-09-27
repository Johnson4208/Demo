# Indicators & VSA guide

## What this feature does

The workspace combines daily OHLCV history with indexed financial-statement evidence. It keeps four layers separate:

1. **Observation** — indicator values, volume ratio, spread ratio, and close location.
2. **Interpretation** — recent VSA events, trap risks, and a heuristic Wyckoff phase.
3. **Confirmation** — the price and volume conditions that must occur next.
4. **Risk plan** — conditional entry, invalidation, targets, wait/holding windows, and exposure caps.

No result places an order. A high research score means “review first,” not “buy first.”

## Using the workspace

1. Open **Indicators & VSA** from the Analytics group.
2. Enter a report-library company such as `FPT`, or an exact market symbol.
3. Choose a profile:
   - **Conservative:** maximum modeled risk 0.5%, position cap 7.5%, same-industry cap 20%.
   - **Balanced:** maximum modeled risk 1.0%, position cap 10%, same-industry cap 30%.
   - **Active:** maximum modeled risk 1.5%, position cap 15%, same-industry cap 40%.
4. Select whether you are researching a new entry or already holding it.
5. Account value, entry price, and current same-industry exposure are optional. They improve sizing and holding guidance but are not stored by this feature.
6. Run the analysis and read the action headline together with its confirmation and invalidation rules.

The requested risk percentage is always capped by the selected profile. Position size is also capped by the remaining same-industry allowance.

## Updating companies and statements

Financial statements continue to use the existing report workflow:

1. Upload the report in **Data Sources & Reports**, or put it inside `reports/Companies_reports/<Industry>/<Company>/`.
2. Run **Scan / re-index** and wait for completion.
3. Return to **Indicators & VSA** and rerun the company or universe screen.

The newest indexed report date, coverage, research-health score, and current risk flags will feed the next result. The application never invents statement values when no report is available.

For a new Vietnam ticker, the company folder can use the exchange ticker and the market symbol will default to `.VN`. For a long legal company name or a symbol that differs from its report folder, add a row to `data/company_symbols.json`. In Docker production, set `SOLVAI_SYMBOL_REGISTRY=/data/company_symbols.json` to maintain the mapping in the persistent volume.

For international markets, enter the exact Yahoo symbol with `YF:` to prevent the Vietnam default—for example `YF:AAPL`, `YF:MSFT`, or `YF:^GSPC`.

## Trap detection

- **Bull-trap risk:** price trades above 20-session resistance but closes back below it.
- **Bear-trap risk:** price trades below 20-session support but closes back above it.
- **Low-volume breakout/breakdown:** price closes through a boundary without normal participation.

These are rule-based warnings, not proof of manipulation. News gaps, auctions, low liquidity, and exchange-specific volume reporting can create similar patterns.

## Correct interpretation

- VSA “spread” means the candle’s high-to-low range, not the bid–ask spread.
- High volume is neither automatically bullish nor bearish.
- Wyckoff phase labels are heuristic classifications.
- Entry and target levels use recent structure and ATR; they can fail or gap.
- The wait and holding windows are review windows. Invalidation and new evidence take priority over elapsed time.
- Recalculate after a new statement, material company event, abnormal-volume shock, or market-regime change.
