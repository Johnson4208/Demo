# SolvAI32 — Quant Part 1 handoff

## Scope

This part upgrades the existing technical price-direction model. It does not change company-report extraction, core-value calculations, Event Probability percentages, trading position sizing, user accounts or stored research.

## Interpretation

- **Up/Down probability** is the calibrated share of historically comparable positive or negative horizon outcomes. It is not an options-implied probability and not a guaranteed return.
- **Brier score** measures probability error; lower is better.
- **Brier skill** measures improvement over a constant historical base-rate forecast. A non-positive value means the model did not improve upon that baseline.
- **Effective non-overlapping samples** is a conservative history check because long-horizon labels overlap heavily.
- **Uncertain** is intentional whenever the held-out checks are insufficient, even if the raw model probability is far from 50%.

## Next quantitative parts

1. Forward earnings-driver curves with clearly separated actual, guidance, consensus and SolvAI estimates.
2. Evidence-linked Bear/Base/Bull probabilities and a scenario-weighted value, without hiding individual downside cases.
3. Optional risk-neutral options distributions only for chains that pass volume, open-interest, spread and arbitrage checks.

## Upgrade

Keep the same persistent data volume. The normal local workflow remains:

```powershell
docker compose up -d --build
docker compose ps
```

No database migration is required for this part.
