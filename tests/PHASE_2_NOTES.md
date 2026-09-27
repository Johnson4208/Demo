# SolvAI 26.2 — Phase 2 handoff

Release 30.0.0 adds an account-private valuation monitor while preserving the SolvAI29 Decision Center, Phase 2 privacy controls, and the stable shared navigation shell. Users can track companies, edit alert thresholds, review explainable changes, and compare saved evidence-backed valuations over time. Manual-input valuation runs remain calculation-only and are not stored.

## Included now

- Forecast Lab rows are owned by a user and workspace. History, saved state, notes, observed outcomes, comparisons and calibration cannot be read or changed through another account.
- Pre-Phase-2 forecasts remain in the database but are hidden because they have no authenticated owner. No potentially shared legacy row is assigned automatically.
- Recent-company and pinned-company browser preferences use user/workspace-specific keys.
- The dashboard and every existing feature keep the established SolvAI26 layout. Inline click/submit handlers were replaced with delegated actions so a strict script policy can run safely.
- A nonce-based Content Security Policy blocks inline event attributes, framing and object content. Research source links are restricted to HTTP(S).
- Every response carries an `X-Request-ID`; application requests produce structured JSON logs without email addresses, passwords, queries, client IP addresses or report content.
- `/api/health` remains a lightweight liveness endpoint. `/api/ready` verifies that account and forecast storage can answer before the service is considered ready.
- `requirements.lock` resolves all production dependencies with SHA-256 hashes. Docker and CI install with `--require-hashes`.
- GitHub Actions compiles Python, syntax-checks browser JavaScript, checks release privacy and runs the test suite. Dependabot is configured for Python, Docker and workflow actions.
- Backup format v2 inventories and hashes every file. Verification rejects path traversal, symlinks, duplicate/unexpected members, oversized expanded archives and modified files. Phase 1 v1 archives remain accepted with an explicit database-only verification level.
- `restore-preview` restores only into a brand-new directory and never overwrites active data.
- Risk Assessment now includes Equity DCF, P/E, two-stage DDM, Gordon Growth, and asset/book-value calculations with visible assumptions and sensitivity ranges.
- Company Overview exposes the same valuation summary on demand without slowing the first dashboard render.
- Dividend timing is inferred only from historical payments and is labelled as an estimate rather than a declared event.
- Watchlists, valuation snapshots, alert settings, alert status, and history are isolated by authenticated user and workspace.
- Smart alerts explain the observed price, saved threshold, fair-value change, or new source dates that triggered them; they do not issue automatic orders.
- The dashboard assistant uses a contained conversation surface and unified composer that stays aligned with the neighboring dashboard panels.

## Upgrade and Docker behavior

Your normal workflow is unchanged:

```powershell
docker compose up -d --build
docker compose ps
```

Keep the existing `solvai_financial_data` volume. On first startup, the forecast table receives additive owner/workspace columns and indexes. Account and report data are not reset. Docker/VPN proxy configuration lives outside this code release and is not modified.

## Verification commands

```powershell
docker compose exec web python -m unittest discover -s tests -v
docker compose exec web python scripts/check_release_privacy.py
```

For a recovery rehearsal, create and verify a backup, then restore it to a path that does not exist:

```powershell
docker compose exec web python manage_backups.py create
docker compose exec web python manage_backups.py verify /data/backups/<backup-file>.zip
docker compose exec web python manage_backups.py restore-preview /data/backups/<backup-file>.zip --target-dir /tmp/solvai-restore-check
```

## Still deferred

- Verified-email delivery and self-service password recovery.
- Full PostgreSQL migration for accounts, indexed reports, jobs and every research table.
- Multi-workspace report-library isolation and organization administration.
- External alert delivery/on-call routing and a formal incident-response process.

Keep public self-registration disabled until the first two items are implemented and reviewed.
