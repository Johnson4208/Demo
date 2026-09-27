# SolvAI V15 Professional — Complete Docker + Persistent Data Setup

## What this setup does

This Compose file is complete; `docker-compose.persistence.example.yml` is only an add-on snippet and is NOT the file to run directly.

SolvAI uses SQLite for its research library. The Docker configuration stores all durable application data in a dedicated named Docker volume:

    solvai_financial_data

The volume is independent of the application container/image. Rebuilding the image or replacing the container does not remove it.

Persistent data layout inside the volume:

    /data/
      reports/
        Companies_reports/
      storage/
        financial_ai.sqlite3
        ocr_cache/
        uploads/
        event_probability_cache/

The application also keeps scan snapshots keyed by source-path + SHA-256 + parser version. That allows an existing scanned report to be reused after a version change when the report itself is unchanged.

## Why there is only a web service

This edition's research database is SQLite, not PostgreSQL. A separate `db` container is therefore not required for this application. Adding a PostgreSQL container would not make the current code persistent and could create unnecessary conflicts with another Docker project.

## First run

Open PowerShell in this directory:

    C:\...\Financial_AI_V15_Professional

Confirm the real Compose file exists:

    Get-Item .\docker-compose.yml

Validate it:

    docker compose config

Build and start:

    docker compose up -d --build

Check status:

    docker compose ps

Check logs:

    docker compose logs -f web

Open:

    http://127.0.0.1:8080

The host port is configurable. For example, to avoid an existing project using 8080:

    $env:SOLVAI_PORT=8081
    docker compose up -d

Then open:

    http://127.0.0.1:8081

## First-start data migration

The application is configured with:

    SOLVAI_DATA_DIR=/data

On the first start of an empty persistence volume, the application migrates the bundled project-local database and report library into `/data`.

After the migration, later container rebuilds use the persistent copy.

## Adding a new report

Use the Scan & Learn UI, or place the report in:

    /data/reports/Companies_reports/<Industry>/<Company>/

and run the scanner.

The upload endpoint triggers a re-index. Unchanged reports are skipped. New/changed reports are scanned. A successful scan is stored in `scan_snapshots`.

## Changing SolvAI versions

Do NOT create a new persistent volume for every version.

Keep:

    solvai_financial_data

the same.

Replace/rebuild only the application code, then:

    docker compose up -d --build

Previously scanned values remain in the volume and can be reused.

## Safe commands

Restart:

    docker compose restart

Rebuild after code changes:

    docker compose up -d --build

Stop containers but KEEP data:

    docker compose down

Do NOT use this unless you intentionally want to delete SolvAI's volumes:

    docker compose down -v

## Back up the persistent data

PowerShell:

    docker run --rm -v solvai_financial_data:/data -v "${PWD}:/backup" alpine sh -c "tar -czf /backup/solvai-data-backup.tar.gz -C /data ."

Restore to the same volume (only while SolvAI is stopped):

    docker compose down
    docker run --rm -v solvai_financial_data:/data -v "${PWD}:/backup" alpine sh -c "rm -rf /data/* /data/.[!.]* 2>/dev/null || true; tar -xzf /backup/solvai-data-backup.tar.gz -C /data"
    docker compose up -d

## If 8080 is already used

Do not stop the other project. Use another host port:

    $env:SOLVAI_PORT=8081
    docker compose up -d

The container still listens on port 5000 internally.

## Docker project isolation

This Compose project uses:

    name: solvai_v15_persistent

and the explicit volume:

    solvai_financial_data

The other Docker project's containers, networks, images, and volumes do not need to be changed.

## Ollama

The Compose file points Ollama at:

    http://host.docker.internal:11434

That allows the container to reach an Ollama server running on the Windows host. Ollama is optional for the quantitative report scanner.

## Troubleshooting

If `docker compose config` says no configuration file was provided, you are not in this directory or the file is missing.

If it says `web has neither an image nor a build context`, you accidentally replaced the real Compose file with the old persistence snippet. This package includes a complete Compose file with `build: .`.

If port 8080 is already allocated, use:

    $env:SOLVAI_PORT=8081
    docker compose up -d

If a persistent volume already exists from a failed experiment and contains no useful data, inspect it first:

    docker volume ls
    docker volume inspect solvai_financial_data

Only remove that volume if you are certain it contains no data you need.

## Recommended workflow

1. Start this Compose project.
2. Verify `/api/health`.
3. Verify existing companies/reports appear.
4. Run Scan & Learn.
5. Add one new report.
6. Confirm the new report is indexed.
7. Run `docker compose down`.
8. Run `docker compose up -d`.
9. Confirm the same scanned values remain.
10. Rebuild with a newer SolvAI version and confirm the volume remains unchanged.

