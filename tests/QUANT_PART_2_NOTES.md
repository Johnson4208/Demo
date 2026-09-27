# SolvAI32 — Quant Part 2 handoff

Version: **32.1.0**

## What changed

Risk Assessment now includes a forward business-driver model and a scenario-weighted risk/reward panel. The model can use provider fields, comparable local-report revenue growth, or optional user assumptions for:

- forward revenue growth;
- forward EPS growth;
- operating-margin change;
- net debt/EBITDA; and
- return on equity.

Each driver is normalized to a bounded directional score. The visible weights are 25%, 30%, 15%, 15%, and 15%, respectively. Missing drivers are excluded. Available coverage and valuation-data quality shrink the final tilt toward the neutral Bear 25% / Base 50% / Bull 25% prior.

The resulting percentages are **heuristic research weights**. They are not options-implied probabilities, analyst consensus, or a statistically calibrated forecast. The interface and API state this limitation directly.

## New outputs

- scenario weight for each Bear/Base/Bull valuation;
- probability-weighted fair value and entry threshold;
- expected-value gap versus the current market price;
- Bear and Bull returns versus market;
- upside/downside ratio;
- traceable driver values, dates, sources, and interpretations; and
- one-year normalized revenue and EPS projections when inputs exist.

## What remains for Part 3

Options-implied risk-neutral distributions require liquid option chains, reliable bid/ask data, strike and expiry filtering, and volatility-surface validation. Part 2 deliberately returns no options probability rather than inventing one for unsupported securities.

## Run locally

Keep your private `.env` beside `docker-compose.yml`, then run:

```powershell
docker compose up -d --build
docker compose ps
```

Do not commit `.env`, `storage/`, reports, databases, or user uploads.
