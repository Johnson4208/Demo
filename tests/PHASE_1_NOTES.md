# SolvAI 26.0 — Phase 1 handoff (historical)

This file records the Phase 1 boundary. The current release is Phase 2; see `PHASE_2_NOTES.md` for the completed follow-up work.

## Included now

- Revocable, server-recorded browser sessions with a personal device list.
- Viewer, Editor, and Administrator roles with least-privilege self-registration.
- Access Center controls for activation, roles, lockouts, password-reset requirements, session revocation, and safe removal.
- Privacy-safe security activity: unknown emails are pseudonymized and client network addresses are stored only as keyed hashes.
- Administrator action audit trail and 90-day security-event retention.
- Stronger 12-character password policy and a password-change flow that rotates sessions.
- Report and chart signature validation, PDF page limits, upload quotas, and automatic deletion of temporary chart files.
- Report scans run through one bounded background worker so the web request does not remain open during OCR/indexing.
- Responsive Access Center and Account Security interfaces integrated with the existing dashboard navigation.

## Upgrade behavior

The existing SQLite database and report library are not replaced. On first launch, the authentication schema is upgraded additively. Legacy `user` roles become `viewer`. Existing users must sign in again because older cookie-only sessions do not have a revocable server session token.

For an internet-facing service, create the administrator through `SOLVAI_ADMIN_EMAIL`, `SOLVAI_ADMIN_PASSWORD`, and `SOLVAI_ADMIN_NAME`, then remove `SOLVAI_ADMIN_PASSWORD` from the host configuration after the account has been created. Keep public registration disabled unless you intentionally want Viewer self-registration.

## Existing startup workflow

No VPN- or Docker-specific files need to be replaced outside this project. From this folder:

```powershell
docker compose up -d --build
docker compose ps
```

The named `solvai_financial_data` volume remains the persistent home for user accounts, reports, and research data.

## Deferred to the next phase

- Per-user scoping for saved Event Probability forecasts and local browser preferences.
- Stricter browser Content Security Policy and removal of remaining inline event handlers.
- Dependency lock/hashing, automated CI expansion, external monitoring, and a rehearsed restore workflow.
- Production database migration and verified-email/password-recovery delivery for wider public registration.
