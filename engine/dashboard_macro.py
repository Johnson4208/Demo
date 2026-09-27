from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from functools import lru_cache
import json
from pathlib import Path
from typing import Any

import pandas as pd

from .macro import _fred


SNAPSHOT_PATH = Path(__file__).resolve().parents[1] / "data" / "us_macro_snapshot.json"


SERIES_SPECS = (
    {
        "key": "cpi",
        "series": "CPIAUCSL",
        "label": "Consumer Price Index",
        "short_label": "CPI",
        "unit": "Index 1982–84=100",
        "frequency": "Monthly · seasonally adjusted",
        "source_agency": "U.S. Bureau of Labor Statistics",
        "decimals": 1,
    },
    {
        "key": "fed_rate",
        "series": "FEDFUNDS",
        "label": "Fed Interest Rate",
        "short_label": "Fed rate",
        "unit": "%",
        "frequency": "Monthly average",
        "source_agency": "Federal Reserve Board",
        "decimals": 2,
    },
    {
        "key": "retail_sales",
        "series": "RSXFS",
        "label": "Retail Sales Index",
        "short_label": "Retail sales",
        "unit": "Index · Jan 2020=100",
        "frequency": "Monthly · seasonally adjusted · nominal chart",
        "source_agency": "U.S. Census Bureau",
        "decimals": 1,
        "transform": "jan_2020_index",
    },
    {
        "key": "unemployment",
        "series": "UNRATE",
        "label": "Unemployment Rate",
        "short_label": "Unemployment",
        "unit": "%",
        "frequency": "Monthly · seasonally adjusted",
        "source_agency": "U.S. Bureau of Labor Statistics",
        "decimals": 1,
    },
    {
        "key": "gasoline",
        "series": "GASREGW",
        "label": "Gasoline Price",
        "short_label": "Gasoline",
        "unit": "USD / gallon",
        "frequency": "Weekly · ending Monday",
        "source_agency": "U.S. Energy Information Administration",
        "decimals": 3,
    },
)


def _normalise_retail_sales(frame: pd.DataFrame, series: str) -> pd.Series:
    dates = pd.to_datetime(frame["observation_date"], errors="coerce")
    values = pd.to_numeric(frame[series], errors="coerce")
    base_rows = values[(dates.dt.year == 2020) & (dates.dt.month == 1)].dropna()
    if base_rows.empty:
        base_rows = values.dropna().head(1)
    if base_rows.empty or float(base_rows.iloc[0]) == 0:
        return values * float("nan")
    return values / float(base_rows.iloc[0]) * 100.0


def _points(frame: pd.DataFrame, spec: dict[str, Any]) -> list[dict[str, Any]]:
    series = spec["series"]
    values = (
        _normalise_retail_sales(frame, series)
        if spec.get("transform") == "jan_2020_index"
        else pd.to_numeric(frame[series], errors="coerce")
    )
    dates = pd.to_datetime(frame["observation_date"], errors="coerce")
    rows = []
    for date_value, numeric_value in zip(dates, values):
        if pd.isna(date_value) or pd.isna(numeric_value):
            continue
        rows.append({"date": date_value.strftime("%Y-%m-%d"), "value": float(numeric_value)})
    return rows[-320:]


@lru_cache(maxsize=1)
def _read_packaged_snapshot() -> dict[str, Any]:
    payload = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    if int(payload.get("schema_version") or 0) != 1:
        raise RuntimeError("Unsupported packaged macro snapshot schema.")
    if not isinstance(payload.get("series"), dict):
        raise RuntimeError("Packaged macro snapshot does not contain series data.")
    return payload


def _snapshot_frame(series: str) -> tuple[pd.DataFrame, str | None]:
    payload = _read_packaged_snapshot()
    rows = payload.get("series", {}).get(series)
    if not isinstance(rows, list) or len(rows) < 2:
        raise RuntimeError(f"Packaged macro snapshot is missing {series}.")
    frame = pd.DataFrame({
        "observation_date": [row.get("date") for row in rows if isinstance(row, dict)],
        series: [row.get("value") for row in rows if isinstance(row, dict)],
    })
    frame["observation_date"] = pd.to_datetime(frame["observation_date"], errors="coerce")
    frame[series] = pd.to_numeric(frame[series], errors="coerce")
    frame = frame.dropna(subset=["observation_date", series]).tail(320)
    if len(frame) < 2:
        raise RuntimeError(f"Packaged macro snapshot has insufficient {series} observations.")
    return frame, payload.get("captured_at")


def _slice_months(points: list[dict[str, Any]], months: int) -> list[dict[str, Any]]:
    if not points:
        return []
    latest = pd.Timestamp(points[-1]["date"])
    cutoff = latest - pd.DateOffset(months=months)
    return [row for row in points if pd.Timestamp(row["date"]) >= cutoff]


def _peak(points: list[dict[str, Any]], months: int) -> dict[str, Any] | None:
    rows = _slice_months(points, months)
    if not rows:
        return None
    return max(rows, key=lambda row: float(row["value"]))


def _change(points: list[dict[str, Any]]) -> dict[str, Any]:
    if len(points) < 2:
        return {
            "previous": None,
            "absolute": None,
            "percent": None,
            "direction": "unavailable",
            "exceeds_previous": None,
            "label": "Prior reading unavailable",
        }
    previous = float(points[-2]["value"])
    current = float(points[-1]["value"])
    absolute = current - previous
    tolerance = max(abs(previous) * 0.00005, 1e-9)
    direction = "up" if absolute > tolerance else "down" if absolute < -tolerance else "flat"
    percent = (absolute / previous * 100.0) if previous else None
    return {
        "previous": previous,
        "previous_date": points[-2]["date"],
        "absolute": absolute,
        "percent": percent,
        "direction": direction,
        "exceeds_previous": current > previous + tolerance,
        "label": "Above previous" if direction == "up" else "Below previous" if direction == "down" else "Matches previous",
    }


def _series_payload(spec: dict[str, Any], force: bool = False) -> dict[str, Any]:
    series = spec["series"]
    base = {
        **spec,
        "source": "FRED · Federal Reserve Bank of St. Louis",
        "url": f"https://fred.stlouisfed.org/series/{series}",
    }
    data_mode = "live"
    snapshot_captured_at = None
    live_error = None
    try:
        frame = _fred(series, force=force)
        points = _points(frame, spec)
        if len(points) < 2:
            raise RuntimeError("Fewer than two published observations were returned.")
    except Exception as exc:
        live_error = exc
        try:
            frame, snapshot_captured_at = _snapshot_frame(series)
            points = _points(frame, spec)
            if len(points) < 2:
                raise RuntimeError("Fewer than two packaged official observations were returned.")
            data_mode = "snapshot"
        except Exception as snapshot_exc:
            return {
                **base,
                "success": False,
                "points": [],
                "latest": {"date": None, "value": None},
                "comparison": _change([]),
                "peaks": {"12m": None, "24m": None, "5y": None},
                "data_mode": "unavailable",
                "live": False,
                "stale_fallback": False,
                "error": (
                    f"Live provider failed ({type(live_error).__name__}); "
                    f"packaged official snapshot failed ({type(snapshot_exc).__name__})."
                ),
            }
    return {
        **base,
        "success": True,
        "points": points,
        "latest": points[-1],
        "comparison": _change(points),
        "peaks": {
            "12m": _peak(points, 12),
            "24m": _peak(points, 24),
            "5y": _peak(points, 60),
        },
        "data_mode": data_mode,
        "live": data_mode == "live",
        "stale_fallback": data_mode == "snapshot",
        "snapshot_captured_at": snapshot_captured_at,
        "provider_note": (
            "Live FRED update is available."
            if data_mode == "live"
            else "Live FRED could not be reached; showing the packaged official FRED snapshot."
        ),
    }


def _period_change(item: dict[str, Any], periods: int, percent: bool = False) -> float | None:
    points = item.get("points") or []
    if len(points) <= periods:
        return None
    latest = float(points[-1]["value"])
    prior = float(points[-1 - periods]["value"])
    if percent:
        return ((latest / prior) - 1.0) * 100.0 if prior else None
    return latest - prior


def _aligned_real_retail_change(
    retail: dict[str, Any], cpi: dict[str, Any], periods: int = 3,
) -> float | None:
    """Inflation-adjust nominal retail sales with aligned monthly CPI observations.

    RSXFS is a nominal dollar series.  Dividing each aligned observation by CPI
    produces a compact real-demand proxy that is more appropriate for the
    scenario engine than nominal retail growth alone.
    """
    retail_rows = {
        str(row.get("date", ""))[:7]: float(row["value"])
        for row in retail.get("points") or [] if row.get("value") is not None
    }
    cpi_rows = {
        str(row.get("date", ""))[:7]: float(row["value"])
        for row in cpi.get("points") or [] if row.get("value") is not None
    }
    months = sorted(set(retail_rows).intersection(cpi_rows))
    if len(months) <= periods:
        return None
    current_month, prior_month = months[-1], months[-1 - periods]
    current = retail_rows[current_month] / cpi_rows[current_month]
    prior = retail_rows[prior_month] / cpi_rows[prior_month]
    return ((current / prior) - 1.0) * 100.0 if prior else None


def _sahm_indicator(item: dict[str, Any]) -> float | None:
    """Return the Sahm-rule style labor deterioration indicator in pp.

    This is the latest three-month unemployment average minus the minimum
    three-month average over the preceding twelve months.  It is used as a
    deterioration signal, not as a recession declaration.
    """
    values = [
        float(row["value"])
        for row in item.get("points") or [] if row.get("value") is not None
    ]
    if len(values) < 15:
        return None
    averages = [sum(values[index - 2:index + 1]) / 3.0 for index in range(2, len(values))]
    current = averages[-1]
    preceding_year = averages[-13:-1]
    return current - min(preceding_year) if preceding_year else None


def _tier(value: float | None, strong, partial) -> float | None:
    """Return transparent 0 / .5 / 1 support for one published indicator."""
    if value is None:
        return None
    if strong(float(value)):
        return 1.0
    if partial(float(value)):
        return 0.5
    return 0.0


def _signed(value: float | None, decimals: int = 1, suffix: str = "") -> str | None:
    if value is None:
        return None
    return f"{float(value):+.{decimals}f}{suffix}"


def _scenario_rankings(measures: dict[str, float | None]) -> list[dict[str, Any]]:
    """Rank five macro paths with visible fixed rules, never random probabilities.

    Each scenario starts at 1.0 because it remains a possible path. Every one of
    the five official indicators can then add 0, 0.5, or 1 support point. The
    total is compressed to a 1–5 signal-strength scale and rounded to a half
    point. It is deliberately a fit score, not a calibrated probability.
    """
    cpi_yoy = measures.get("cpi_yoy_pct")
    cpi_1m = measures.get("cpi_1m_pct")
    fed_rate = measures.get("fed_rate_pct")
    fed_3m = measures.get("fed_rate_3m_pp")
    retail_3m = measures.get("retail_3m_pct")
    unemployment_rate = measures.get("unemployment_rate_pct")
    unemployment_3m = measures.get("unemployment_3m_pp")
    sahm_indicator = measures.get("sahm_indicator_pp")
    labor_deterioration = sahm_indicator if sahm_indicator is not None else unemployment_3m
    gasoline_4w = measures.get("gasoline_4w_pct")

    def combined_tier(values, strong, partial) -> float | None:
        if any(value is None for value in values):
            return None
        numeric = tuple(float(value) for value in values)
        if strong(*numeric):
            return 1.0
        if partial(*numeric):
            return 0.5
        return 0.0

    indicator_values = {
        "cpi": " · ".join(part for part in (
            f"{cpi_yoy:.1f}% YoY" if cpi_yoy is not None else None,
            f"{_signed(cpi_1m, 1, '%')} latest" if cpi_1m is not None else None,
        ) if part) or "Unavailable",
        "fed_rate": " · ".join(part for part in (
            f"{fed_rate:.2f}%" if fed_rate is not None else None,
            f"{_signed(fed_3m, 2, ' pp')} / 3m" if fed_3m is not None else None,
        ) if part) or "Unavailable",
        "retail_sales": f"{_signed(retail_3m, 1, '%')} real / 3m" if retail_3m is not None else "Unavailable",
        "unemployment": " · ".join(part for part in (
            f"{unemployment_rate:.1f}% latest" if unemployment_rate is not None else None,
            f"Sahm {_signed(sahm_indicator, 2, ' pp')}" if sahm_indicator is not None
            else f"{_signed(unemployment_3m, 2, ' pp')} / 3m" if unemployment_3m is not None else None,
        ) if part) or "Unavailable",
        "gasoline": f"{_signed(gasoline_4w, 1, '%')} / 4w" if gasoline_4w is not None else "Unavailable",
    }
    indicator_names = {
        "cpi": "CPI",
        "fed_rate": "Fed rate",
        "retail_sales": "Retail sales",
        "unemployment": "Unemployment",
        "gasoline": "Gasoline",
    }

    scenario_specs = [
        {
            "key": "higher_for_longer",
            "title": "Rates stay high while inflation persists",
            "status": "Higher-for-longer risk",
            "tone": "caution",
            "thesis": "Price pressure remains elevated while consumer demand and employment still look resilient enough to delay rapid policy easing.",
            "consequence": "If this mix persists, the Fed has less reason to ease quickly. Borrowing costs can stay restrictive, leaving housing, leveraged businesses, and long-duration equity valuations under pressure.",
            "transmission": [
                "Inflation and fuel pressure remain firm",
                "Demand and labor avoid a clear contraction",
                "Restrictive policy stays in place for longer",
            ],
            "watch_for": "CPI and gasoline staying firm while retail sales remain positive and unemployment does not rise materially.",
            "support": {
                "cpi": _tier(cpi_yoy, lambda value: value >= 3.0, lambda value: value >= 2.5),
                "fed_rate": _tier(fed_rate, lambda value: value >= 3.5, lambda value: value >= 2.5),
                "retail_sales": _tier(retail_3m, lambda value: value >= 0.0, lambda value: value >= -1.0),
                "unemployment": _tier(labor_deterioration, lambda value: value < 0.3, lambda value: value < 0.5),
                "gasoline": _tier(gasoline_4w, lambda value: value >= 3.0, lambda value: value >= 0.0),
            },
        },
        {
            "key": "soft_landing",
            "title": "Soft landing with slower, positive growth",
            "status": "Soft-landing path",
            "tone": "positive",
            "thesis": "Spending and employment remain intact while inflation is not accelerating fast enough to force an immediate policy shock.",
            "consequence": "Demand can keep supporting revenue while labor conditions cool gradually. Earnings growth may slow without a broad contraction, favoring cash-generative companies with pricing power and sound balance sheets.",
            "transmission": [
                "Retail demand remains positive",
                "Unemployment stays contained",
                "Inflation cools enough for gradual easing",
            ],
            "watch_for": "Moderating CPI and gasoline alongside positive retail sales and only a gradual change in unemployment.",
            "support": {
                "cpi": combined_tier(
                    (cpi_yoy, cpi_1m),
                    lambda yearly, latest: yearly < 4.0 and latest <= 0.6,
                    lambda yearly, latest: yearly < 4.5 and latest <= 0.8,
                ),
                "fed_rate": _tier(fed_3m, lambda value: abs(value) <= 0.25, lambda value: value < 0.5),
                "retail_sales": _tier(retail_3m, lambda value: value >= 0.0, lambda value: value >= -0.75),
                "unemployment": _tier(labor_deterioration, lambda value: value < 0.3, lambda value: value < 0.5),
                "gasoline": _tier(gasoline_4w, lambda value: value <= 1.0, lambda value: value <= 8.0),
            },
        },
        {
            "key": "inflation_reacceleration",
            "title": "Inflation heats up again; policy tightens",
            "status": "Inflation re-acceleration risk",
            "tone": "risk",
            "thesis": "Firm demand and labor conditions give a fresh CPI or energy increase more room to pass through into costs and policy expectations.",
            "consequence": "A renewed price impulse can delay easing and make another policy increase more plausible. Bond yields, financing costs, and duration-sensitive equity valuations would be most exposed.",
            "transmission": [
                "Gasoline and consumer prices re-accelerate",
                "Input and distribution costs spread",
                "Expected policy easing is delayed or reversed",
            ],
            "watch_for": "Another broad CPI increase, gasoline remaining elevated, and any upward turn in the effective Fed funds rate.",
            "support": {
                "cpi": combined_tier(
                    (cpi_yoy, cpi_1m),
                    lambda yearly, latest: yearly >= 3.0 and latest > 0.0,
                    lambda yearly, latest: yearly >= 2.5,
                ),
                "fed_rate": _tier(fed_3m, lambda value: value > 0.1, lambda value: value > 0.0),
                "retail_sales": _tier(retail_3m, lambda value: value > 0.0, lambda value: value > -0.5),
                "unemployment": _tier(labor_deterioration, lambda value: value < 0.3, lambda value: value < 0.5),
                "gasoline": _tier(gasoline_4w, lambda value: value >= 3.0, lambda value: value >= 0.0),
            },
        },
        {
            "key": "consumer_slowdown",
            "title": "Consumer demand weakens; growth slows sharply",
            "status": "Inflation and slowdown risk",
            "tone": "risk",
            "thesis": "High prices and financing costs can erode real purchasing power, but the slowdown needs confirmation from retail sales and labor data.",
            "consequence": "If retail demand falls while unemployment rises, household purchasing power and business revenue can weaken together. Cyclical earnings, margins, credit quality, and broad risk appetite would face pressure.",
            "transmission": [
                "Prices and financing costs squeeze households",
                "Retail demand rolls over",
                "Hiring slows and unemployment rises",
            ],
            "watch_for": "A negative three-month retail trend paired with a sustained increase in unemployment.",
            "support": {
                "cpi": _tier(cpi_yoy, lambda value: value >= 3.0, lambda value: value >= 2.5),
                "fed_rate": _tier(fed_rate, lambda value: value >= 3.5, lambda value: value >= 2.5),
                "retail_sales": _tier(retail_3m, lambda value: value <= -0.5, lambda value: value < 0.0),
                "unemployment": _tier(labor_deterioration, lambda value: value >= 0.5, lambda value: value >= 0.3),
                "gasoline": _tier(gasoline_4w, lambda value: value >= 5.0, lambda value: value >= 2.0),
            },
        },
        {
            "key": "disinflation_cuts",
            "title": "Disinflation strengthens; the Fed moves to cuts",
            "status": "Disinflation and easing path",
            "tone": "positive",
            "thesis": "This path needs broad evidence that price pressure is fading while demand and labor are softening enough to create policy room.",
            "consequence": "A sustained decline in inflation and activity can open room for rate cuts. Bonds and rate-sensitive assets may benefit, although weaker earnings can offset part of that valuation support.",
            "transmission": [
                "CPI and gasoline pressure recede",
                "Demand and labor cool materially",
                "Policy can shift toward rate cuts",
            ],
            "watch_for": "CPI approaching 2%, falling gasoline, negative retail momentum, rising unemployment, and a clear decline in the policy rate.",
            "support": {
                "cpi": _tier(cpi_yoy, lambda value: value <= 2.5, lambda value: value < 4.0),
                "fed_rate": _tier(fed_3m, lambda value: value <= -0.25, lambda value: value <= 0.0),
                "retail_sales": _tier(retail_3m, lambda value: value <= -0.5, lambda value: value < 0.0),
                "unemployment": _tier(labor_deterioration, lambda value: value >= 0.5, lambda value: value >= 0.3),
                "gasoline": _tier(gasoline_4w, lambda value: value <= -3.0, lambda value: value <= 0.0),
            },
        },
    ]

    rows = []
    for priority, spec in enumerate(scenario_specs):
        evidence = []
        support_sum = 0.0
        available = 0
        component_weights = {"cpi": 1.0, "fed_rate": 1.0, "retail_sales": 1.0, "unemployment": 1.0, "gasoline": 0.5}
        maximum_support = sum(component_weights.values())
        for key in ("cpi", "fed_rate", "retail_sales", "unemployment", "gasoline"):
            contribution = spec["support"].get(key)
            if contribution is not None:
                support_sum += float(contribution) * component_weights[key]
                available += 1
            evidence.append({
                "key": key,
                "label": indicator_names[key],
                "value": indicator_values[key],
                "contribution": contribution,
                "weight": component_weights[key],
                "stance": (
                    "unavailable" if contribution is None
                    else "supporting" if contribution >= 1.0
                    else "partial" if contribution >= 0.5
                    else "contrary"
                ),
            })
        score = max(1.0, min(5.0, round((1.0 + 4.0 * support_sum / maximum_support) * 2.0) / 2.0))
        signal_label = (
            "Very strong fit" if score >= 4.5
            else "Strong fit" if score >= 3.5
            else "Developing fit" if score >= 2.5
            else "Limited support"
        )
        rows.append({
            **{key: value for key, value in spec.items() if key != "support"},
            "signal_score": score,
            "signal_label": signal_label,
            "coverage": available,
            "evidence": evidence,
            "_priority": priority,
        })

    rows.sort(key=lambda row: (-float(row["signal_score"]), int(row["_priority"])))
    for rank, row in enumerate(rows, 1):
        row["rank"] = rank
        row["is_leading"] = rank == 1
        row.pop("_priority", None)
    return rows


def _outlook(series: dict[str, dict[str, Any]]) -> dict[str, Any]:
    def latest(key: str) -> float | None:
        value = series.get(key, {}).get("latest", {}).get("value")
        return float(value) if value is not None else None

    cpi_yoy = _period_change(series.get("cpi", {}), 12, percent=True)
    cpi_1m = _period_change(series.get("cpi", {}), 1, percent=True)
    retail_nominal_3m = _period_change(series.get("retail_sales", {}), 3, percent=True)
    retail_3m = _aligned_real_retail_change(series.get("retail_sales", {}), series.get("cpi", {}), 3)
    retail_1m = _aligned_real_retail_change(series.get("retail_sales", {}), series.get("cpi", {}), 1)
    unemployment_3m = _period_change(series.get("unemployment", {}), 3)
    sahm_indicator = _sahm_indicator(series.get("unemployment", {}))
    gasoline_4w = _period_change(series.get("gasoline", {}), 4, percent=True)
    fed_rate = latest("fed_rate")
    fed_rate_3m = _period_change(series.get("fed_rate", {}), 3)
    unemployment_rate = latest("unemployment")
    measures = {
        "cpi_yoy_pct": cpi_yoy,
        "cpi_1m_pct": cpi_1m,
        "retail_3m_pct": retail_3m,
        "retail_1m_pct": retail_1m,
        "retail_nominal_3m_pct": retail_nominal_3m,
        "unemployment_3m_pp": unemployment_3m,
        "sahm_indicator_pp": sahm_indicator,
        "unemployment_rate_pct": unemployment_rate,
        "gasoline_4w_pct": gasoline_4w,
        "fed_rate_pct": fed_rate,
        "fed_rate_3m_pp": fed_rate_3m,
    }
    available = sum(bool(series.get(key, {}).get("points")) for key in (
        "cpi", "fed_rate", "retail_sales", "unemployment", "gasoline",
    ))
    if available < 3:
        return {
            "status": "Insufficient published data",
            "tone": "mixed",
            "warnings": [],
            "conclusion": (
                "A long-run market scenario is withheld until at least three official series are available. "
                "Missing releases remain unavailable rather than being replaced with estimates."
            ),
            "measures": measures,
            "scenarios": [],
            "leading_scenario_key": None,
            "methodology": "Scenario analysis uses only published observations and fixed thresholds; it is not a forecast or investment recommendation.",
        }

    policy_tight = fed_rate is not None and fed_rate >= 4.0

    warnings = []
    if cpi_yoy is not None and cpi_yoy >= 3.0:
        warnings.append(f"CPI is {cpi_yoy:.1f}% above its year-earlier level, keeping inflation pressure elevated.")
    if gasoline_4w is not None and gasoline_4w >= 5.0:
        warnings.append(f"Gasoline rose {gasoline_4w:.1f}% over four published weeks, which can lift household and transport costs.")
    if sahm_indicator is not None and sahm_indicator >= 0.5:
        warnings.append(f"The Sahm-style labor deterioration indicator reached {sahm_indicator:.2f} percentage points, a material slowdown warning.")
    if retail_3m is not None and retail_3m <= -1.0:
        warnings.append(f"Inflation-adjusted retail demand fell {abs(retail_3m):.1f}% over three months, suggesting softer real consumer demand.")
    if policy_tight:
        warnings.append(f"The effective Fed funds rate remains {fed_rate:.2f}%, so financing conditions can stay restrictive if maintained.")

    scenarios = _scenario_rankings(measures)
    leader = scenarios[0]

    return {
        "status": leader["status"],
        "tone": leader["tone"],
        "warnings": warnings,
        "conclusion": leader["consequence"],
        "measures": measures,
        "scenarios": scenarios,
        "leading_scenario_key": leader["key"],
        "methodology": (
            "Signal strength uses published observations and visible fixed thresholds. Retail momentum is adjusted for CPI and labor deterioration uses a Sahm-style three-month rule. "
            "Headline CPI already includes energy, so gasoline is capped at half weight as a transmission signal rather than a second full inflation vote. "
            "It ranks current scenario fit; it is not a forecast, calibrated probability, or investment recommendation."
        ),
    }


def dashboard_macro_snapshot(force: bool = False) -> dict[str, Any]:
    rows: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=len(SERIES_SPECS)) as pool:
        futures = {pool.submit(_series_payload, spec, force): spec["key"] for spec in SERIES_SPECS}
        for future in as_completed(futures):
            key = futures[future]
            try:
                rows[key] = future.result()
            except Exception as exc:
                spec = next(item for item in SERIES_SPECS if item["key"] == key)
                rows[key] = {
                    **spec,
                    "success": False,
                    "points": [],
                    "latest": {"date": None, "value": None},
                    "comparison": _change([]),
                    "peaks": {"12m": None, "24m": None, "5y": None},
                    "source": "FRED · Federal Reserve Bank of St. Louis",
                    "url": f"https://fred.stlouisfed.org/series/{spec['series']}",
                    "data_mode": "unavailable",
                    "live": False,
                    "stale_fallback": False,
                    "error": f"Macro series failed ({type(exc).__name__}).",
                }

    ordered = {spec["key"]: rows[spec["key"]] for spec in SERIES_SPECS}
    available = sum(1 for item in ordered.values() if item.get("success"))
    live_series = sum(1 for item in ordered.values() if item.get("success") and item.get("data_mode") == "live")
    snapshot_series = sum(1 for item in ordered.values() if item.get("success") and item.get("data_mode") == "snapshot")
    if live_series == len(SERIES_SPECS):
        data_mode = "live"
    elif snapshot_series == len(SERIES_SPECS):
        data_mode = "snapshot"
    elif available:
        data_mode = "mixed"
    else:
        data_mode = "unavailable"
    snapshot_dates = [item.get("snapshot_captured_at") for item in ordered.values() if item.get("snapshot_captured_at")]
    return {
        "success": available > 0,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "available_series": available,
        "total_series": len(SERIES_SPECS),
        "live_series": live_series,
        "snapshot_series": snapshot_series,
        "data_mode": data_mode,
        "snapshot_captured_at": max(snapshot_dates) if snapshot_dates else None,
        "series": ordered,
        "outlook": _outlook(ordered),
        "data_note": (
            "Live releases are preferred. When FRED is unreachable, the packaged date-stamped official snapshot is used; release frequencies vary and source agencies may revise observations."
        ),
        "refresh_seconds": 1800,
        "semantic_version": "45.0",
        "calculation_policy": {
            "retail_demand": "RSXFS deflated by CPIAUCSL over aligned months",
            "labor_deterioration": "latest 3-month unemployment average minus the prior 12-month minimum",
            "gasoline_weight": 0.5,
            "fed_rate_basis": "FEDFUNDS monthly average",
        },
    }
