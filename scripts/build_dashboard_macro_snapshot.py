"""Refresh the packaged offline fallback from official FRED CSV series."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.dashboard_macro import SERIES_SPECS, SNAPSHOT_PATH  # noqa: E402
from engine.macro import _fred  # noqa: E402


def main() -> None:
    payload = {
        "schema_version": 1,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source": "FRED · Federal Reserve Bank of St. Louis",
        "source_url": "https://fred.stlouisfed.org/",
        "series": {},
    }
    for spec in SERIES_SPECS:
        series = spec["series"]
        frame = _fred(series, force=True)
        rows = []
        for date_value, numeric_value in zip(frame["observation_date"], frame[series]):
            rows.append({
                "date": date_value.strftime("%Y-%m-%d"),
                "value": float(numeric_value),
            })
        if len(rows) < 2:
            raise RuntimeError(f"FRED returned insufficient data for {series}.")
        payload["series"][series] = rows[-320:]

    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = SNAPSHOT_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(SNAPSHOT_PATH)
    print(f"Wrote {SNAPSHOT_PATH} with {len(payload['series'])} official series.")


if __name__ == "__main__":
    main()
