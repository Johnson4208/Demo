# SolvAI 26.2 Phase 2 closed-beta deployment

This edition is prepared for one private Render web-service instance. It is not yet a public multi-tenant product: authenticated users share the same company report library and research database. Keep registration closed and invite only people who may access that shared workspace.

## 1. Test the production container locally

Local Docker Compose remains unchanged for day-to-day use:

```powershell
docker compose up -d --build
docker compose ps
```

Open `http://localhost:8080`. The container now runs Gunicorn, but local HTTP remains supported because Compose sets `SOLVAI_ENV=development` and secure cookies remain off locally.

Run the tests before publishing the repository:

```powershell
docker compose exec web python -m unittest discover -s tests -v
```

## 2. Publish code privately

Create a private GitHub repository and publish this folder. Before committing, confirm that these remain excluded:

```text
.env
storage/
reports/
*.sqlite3
*.zip
```

Do not commit account databases, user emails, reports, API keys, passwords or session secrets.

## 3. Create the Render service

In Render, choose **New > Blueprint** and connect the private repository. Render reads `render.yaml` and proposes:

- Docker runtime;
- Singapore region;
- one `1c-2g` instance;
- one 5 GB persistent disk mounted at `/data`;
- `/api/ready` readiness checks;
- automatic deploys disabled until you intentionally deploy a revision.

Review the current Render price before applying the Blueprint because the selected compute plan and persistent disk are paid resources.

## 4. Enter first-deploy secrets

The Blueprint asks for the administrator email and temporary password. Use values that are unique to SolvAI. Render generates `SOLVAI_SECRET_KEY`; keep that value stable for the life of the deployment.

Configured production protections include:

```text
SOLVAI_ENV=production
SOLVAI_DATA_DIR=/data
SOLVAI_SECURE_COOKIES=1
SOLVAI_TRUST_PROXY=1
SOLVAI_PROXY_HOPS=1
SOLVAI_ALLOW_REGISTRATION=0
SOLVAI_OLLAMA_ENABLED=0
WEB_CONCURRENCY=1
```

Do not set `SOLVAI_ALLOW_REGISTRATION=1` for an internet-facing service until verified email and password recovery exist. Phase 2 isolates personal Forecast Lab data, but the indexed company report library remains intentionally shared inside one workspace.

## 5. Verify the first deployment

Open the generated HTTPS URL and check:

1. `/api/health` reports version `37.0.0`, environment `production`, and authentication `required`; `/api/ready` reports `ready`.
2. The administrator can sign in and open **Access Center**.
3. A visitor cannot create an account.
4. A normal user cannot access `/admin/users`.
5. A supported non-sensitive test report uploads and survives a manual redeploy.
6. Incorrect passwords are rejected and repeated attempts are limited.
7. The site works from a phone using mobile data.

After the administrator account exists on the persistent disk, remove `SOLVAI_ADMIN_PASSWORD` from Render and redeploy. The account remains; the bootstrap password no longer remains in service configuration.

## 6. Optional language model

The cloud deployment deliberately disables local Ollama. Deterministic company analysis and Event Probability explanations remain available. Do not point hosted SolvAI at `host.docker.internal`; that address refers to the cloud host, not your home computer.

Enable generative explanations only after integrating a supported hosted inference service or deploying a separately secured model endpoint. Store credentials exclusively in Render secret environment variables.

## 7. Back up the workspace

From a Render shell, create a consistent archive:

```bash
python manage_backups.py create
python manage_backups.py list
python manage_backups.py verify /data/backups/<backup-file>.zip
```

Rehearse recovery into a **new** directory. This command refuses to overwrite an existing path or the active `/data` directory:

```bash
python manage_backups.py restore-preview /data/backups/<backup-file>.zip --target-dir /data-restore-check
```

Inspect the restored database and reports before any planned storage switch. Every archived file is size- and SHA-256-verified, unsafe ZIP paths and symlinks are rejected, and the restored SQLite database receives an integrity check.

The archive includes the SQLite database and report library and therefore contains private account metadata and potentially confidential documents. Download it to encrypted off-platform storage, verify it, and remove obsolete copies according to your retention policy. Render disk snapshots are useful, but they should not be the only database recovery method.

## 8. Add a custom domain last

Use the generated Render HTTPS URL during the beta. Connect a custom domain only after login, persistence, backup and mobile-access tests pass. Render provisions and renews TLS after DNS verification.

## Release boundary

SolvAI 26.2 Phase 2 is suitable for a small, trusted, shared-library beta with revocable sessions, role-based access, private personal forecasts, transparent valuation research, locked dependencies, readiness checks and structured service logs. Before open registration, migrate all application data to a production multi-user datastore and add verified email, self-service recovery, privacy terms, alert routing and a documented incident process.
