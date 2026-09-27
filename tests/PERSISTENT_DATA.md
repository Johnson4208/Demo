# SolvAI persistent scan storage

SolvAI can keep the report library and scanned financial values outside the application version folder. This prevents a Docker image/container upgrade from deleting the indexed values.

## Docker (recommended)

Set this environment variable on the SolvAI `web` service:

```yaml
environment:
  SOLVAI_DATA_DIR: /data
volumes:
  - solvai_financial_data:/data
```

Use the unique named volume `solvai_financial_data`. Docker will keep this volume when you recreate/remove the SolvAI container, and it is separate from volumes belonging to your other projects.

The persistent volume contains:

```text
/data/
  reports/Companies_reports/     # uploaded source reports
  storage/financial_ai.sqlite3  # current indexed values
  storage/                       # scan history, OCR cache, uploads
```

## Version switching

Every successfully indexed report is identified by its SHA-256 file hash and parser version. SolvAI stores a snapshot of its extracted observations.

When a new application version scans the same unchanged PDF:

1. Existing observations are kept in the persistent SQLite database.
2. If that exact file hash + parser version was already scanned, the saved snapshot is restored without OCR/extraction.
3. If a newer parser version is used, the previous version is archived before replacement.
4. Switching back to the older parser version can restore its saved snapshot.

This means changing application versions does **not** require throwing away the previously scanned financial values.

## First migration

On the first startup with `SOLVAI_DATA_DIR`, if the persistent location is empty, SolvAI automatically copies the existing project-local `storage/financial_ai.sqlite3` and `reports/Companies_reports` into the persistent location.

After that, the persistent location is the source of truth. Keep it mounted across upgrades.

## Important Docker rule

Do not bake the `reports/` folder or SQLite database into each new application image and expect it to survive an upgrade. The image contains code; the named volume contains user data.

## Backup

Back up the Docker volume (or use a host bind mount instead of a named volume) before major changes. The most important files are:

- `storage/financial_ai.sqlite3`
- `reports/Companies_reports/`

