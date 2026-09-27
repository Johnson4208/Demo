# Run and update SolvAI 45

## First run on Windows

1. Extract the ZIP completely. Do not run it from inside the ZIP preview.
2. Double-click `update.bat`. This creates `.venv`, installs the application dependencies, and runs `diagnose.py`.
3. Double-click `run.bat`. It opens `http://127.0.0.1:5000` and starts the local server.
4. Keep the command window open while using SolvAI. Closing it stops the server.

Later starts need only `run.bat`. Use `update.bat` again after changing `requirements.txt`, changing Python, or receiving a newer SolvAI release.

## macOS or Linux

From Terminal in the extracted folder:

```bash
chmod +x run.sh
./run.sh
```

Then open `http://127.0.0.1:5000`.

## Update to a future ZIP safely

SolvAI ZIP releases do not update themselves. Use this repeatable process:

1. Stop the old SolvAI window.
2. Make a backup copy of these private items from the old folder:
   - `storage/` — database, uploads, sessions, caches, watchlists, and private history.
   - `reports/` — company source reports.
   - `company_symbols.json` — local symbol mappings, when present.
   - `.env` or the environment values used by Docker, when present.
3. Extract the new ZIP to a new folder.
4. Copy only the private items above into the new folder. Allow your private data to replace the new empty/default copies.
5. Do **not** copy old `engine/`, `static/`, `templates/`, `data/`, `tests/`, `app.py`, or `config.py` over the new release. Those are the upgraded product and formula files.
6. Run `update.bat`, then `run.bat`.
7. Open Data Sources & Reports and choose **Scan all reports** after a parser-version upgrade or after adding reports.

The application runs additive database initialization at startup. It does not require deleting the current database.

## Keep data outside the code folder (advanced)

For a permanent installation, define `SOLVAI_DATA_DIR` before starting SolvAI. Example in Command Prompt:

```bat
set SOLVAI_DATA_DIR=C:\SolvAI-Private-Data
run.bat
```

That directory will contain durable `storage/`, `reports/Companies_reports/`, and `company_symbols.json` locations. Use the same value for every future release. Docker already uses this pattern through the persistent `/data` volume.

## Update different kinds of information

| What changed | What to do |
|---|---|
| A new company report | Put it in the correct company folder, then run **Scan all reports**. |
| Company symbol mapping | Edit `company_symbols.json`, restart SolvAI, then refresh the company. |
| Python packages | Run `update.bat`. |
| Application code / formulas / UI | Install the newer release using the safe ZIP process above. |
| FRED or market readings | Use the visible **Refresh** control; normal requests also refresh automatically according to source cadence. |
| Docker image | Keep the data volume, then run `docker compose up -d --build`. |

## Useful checks

```bat
diagnose.bat
.venv\Scripts\python.exe -m unittest discover -s tests -q
```

If a provider is temporarily unavailable, SolvAI uses a recent cached or packaged official observation only when it can label that fallback honestly. It does not manufacture chart readings.
