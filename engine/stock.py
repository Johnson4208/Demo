import numpy as np
import pandas as pd
import json
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from config import APP_VERSION, BASE_DIR, STOCK_PERIOD, SYMBOL_REGISTRY_PATH
from .market_data import batch_history as market_batch_history, history as market_history
from .provider_cache import MARKET_CACHE, MODEL_CACHE
from .technical import rsi as canonical_rsi


HORIZONS = (
    {"key": "5d", "label": "1 week", "trading_days": 5},
    {"key": "21d", "label": "1 month", "trading_days": 21},
    {"key": "63d", "label": "3 months", "trading_days": 63},
    {"key": "252d", "label": "12 months", "trading_days": 252},
)
FEATURE_LABELS = {
    "ret1": "1-day return",
    "ret5": "1-week momentum",
    "ret20": "1-month momentum",
    "ret60": "3-month momentum",
    "rsi14": "RSI (14)",
    "sma20_gap": "Distance from 20-day average",
    "sma60_gap": "Distance from 60-day average",
    "vol20": "20-day volatility",
    "vol60": "60-day volatility",
    "drawdown60": "60-day drawdown",
    "volume_z": "Volume deviation",
}

ALIASES = {
    "FPT": "FPT.VN",
    "FPT CORPORATION": "FPT.VN",
    "CONG TY CO PHAN FPT": "FPT.VN",
    "PNJ": "PNJ.VN",
    "PHU NHUAN JEWELRY JOINT STOCK COMPANY": "PNJ.VN",
    "CONG TY CO PHAN VANG BAC DA QUY PHU NHUAN": "PNJ.VN",
    "CMG": "CMG.VN",
    "CMC": "CMG.VN",
    "CMC CORPORATION": "CMG.VN",
    "CONG TY CO PHAN TAP DOAN CONG NGHE CMC": "CMG.VN",
    "VNZ": "VNZ.VN",
    "VNG": "VNZ.VN",
    "VNG CORPORATION": "VNZ.VN",
    "CONG TY CO PHAN TAP DOAN VNG": "VNZ.VN",
    "CONG TY CO PHAN VNG": "VNZ.VN",
    "VNG CORPORATION": "VNZ.VN",
}

def _norm_company(value):
    import unicodedata, re
    t=unicodedata.normalize("NFKD", str(value or ""))
    t="".join(ch for ch in t if not unicodedata.combining(ch))
    t=t.replace("đ","d").replace("Đ","D")
    t=re.sub(r"[^A-Za-z0-9]+"," ",t).strip().upper()
    return t


def _registry_aliases():
    """Load user-maintained symbols without requiring an application rebuild.

    The package registry supplies examples and defaults.  A persistent registry
    at SOLVAI_SYMBOL_REGISTRY overrides it and can be edited whenever a new
    company is added to the report library.
    """
    aliases = {}
    paths = [BASE_DIR / "data" / "company_symbols.json", SYMBOL_REGISTRY_PATH]
    seen = set()
    for path in paths:
        key = str(path)
        if key in seen or not path.exists():
            continue
        seen.add(key)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        if isinstance(payload, dict) and isinstance(payload.get("companies"), list):
            payload = payload["companies"]
        if isinstance(payload, dict):
            for name, symbol in payload.items():
                if str(name).strip() and str(symbol).strip():
                    aliases[_norm_company(name)] = str(symbol).strip().upper()
        elif isinstance(payload, list):
            for item in payload:
                if not isinstance(item, dict):
                    continue
                symbol = str(item.get("symbol") or item.get("ticker") or "").strip().upper()
                extra_aliases = item.get("aliases") or []
                if isinstance(extra_aliases, str):
                    extra_aliases = [extra_aliases]
                names = [item.get("company"), item.get("name"), *extra_aliases]
                if not symbol:
                    continue
                for name in names:
                    if str(name or "").strip():
                        aliases[_norm_company(name)] = symbol
    return aliases

def ticker_for(company):
    raw=str(company or "").strip()
    if raw.upper().startswith("YF:"):
        return raw[3:].strip().upper()
    if "." in raw.upper() or raw.startswith("^") or "=" in raw: return raw.upper()
    norm=_norm_company(raw)
    registry = _registry_aliases()
    if norm in registry: return registry[norm]
    if norm in ALIASES: return ALIASES[norm]
    # Handle common legal-name suffixes without requiring the folder name to be a ticker.
    for key,ticker in registry.items():
        if len(key) >= 4 and key in norm: return ticker
    for key,ticker in ALIASES.items():
        if key and key in norm: return ticker
    return raw.upper()+".VN"


def _finite_float(value):
    try:
        v=float(value)
        return v if np.isfinite(v) else None
    except Exception:
        return None

def rsi(series, period=14):
    return canonical_rsi(series, period)


def _feature_frame(frame):
    close = frame["Close"].astype(float)
    volume = frame["Volume"].astype(float)
    returns = close.pct_change(fill_method=None)
    features = pd.DataFrame(index=frame.index)
    features["ret1"] = returns
    features["ret5"] = close.pct_change(5, fill_method=None)
    features["ret20"] = close.pct_change(20, fill_method=None)
    features["ret60"] = close.pct_change(60, fill_method=None)
    features["rsi14"] = rsi(close)
    features["sma20_gap"] = close / close.rolling(20).mean() - 1
    features["sma60_gap"] = close / close.rolling(60).mean() - 1
    features["vol20"] = returns.rolling(20).std()
    features["vol60"] = returns.rolling(60).std()
    features["drawdown60"] = close / close.rolling(60).max() - 1
    log_volume = np.log1p(volume.replace(0, np.nan))
    features["volume_z"] = (
        (log_volume - log_volume.rolling(20).mean())
        / log_volume.rolling(20).std()
    )
    return features.replace([np.inf, -np.inf], np.nan)


def _model_pair():
    logistic = make_pipeline(
        StandardScaler(),
        LogisticRegression(max_iter=2000, class_weight="balanced", random_state=42),
    )
    forest = RandomForestClassifier(
        n_estimators=140,
        max_depth=6,
        min_samples_leaf=8,
        random_state=42,
        class_weight="balanced",
        n_jobs=1,
    )
    return logistic, forest


def _pair_probability(models, values):
    logistic, forest = models
    return (
        logistic.predict_proba(values)[:, 1]
        + forest.predict_proba(values)[:, 1]
    ) / 2.0


def _walk_forward_slices(total, horizon_days, folds=3):
    """Expanding training windows separated from validation by the horizon.

    The gap prevents a training label from using a future closing price that
    belongs to the following validation period.
    """
    minimum_train = max(180, horizon_days + 80)
    available = total - minimum_train - horizon_days
    if available < 60:
        return []
    test_size = max(20, min(90, available // folds))
    first_train_end = total - horizon_days - test_size * folds
    slices = []
    for fold in range(folds):
        train_end = first_train_end + fold * test_size
        validation_start = train_end + horizon_days
        validation_end = min(total, validation_start + test_size)
        if train_end >= minimum_train and validation_end - validation_start >= 20:
            slices.append((slice(0, train_end), slice(validation_start, validation_end)))
    return slices


def _direction(probability, reliable):
    if not reliable:
        return "UNCERTAIN"
    if probability >= 0.58:
        return "UPWARD"
    if probability <= 0.42:
        return "DOWNWARD"
    return "UNCERTAIN"


def _horizon_model(features, close, horizon_spec):
    days = int(horizon_spec["trading_days"])
    future_return = close.shift(-days) / close - 1.0
    target = pd.Series(np.nan, index=close.index, dtype=float)
    target.loc[future_return.notna()] = (future_return.loc[future_return.notna()] > 0).astype(float)
    model_frame = features.copy()
    model_frame["target"] = target
    model_frame = model_frame.dropna()
    current = features.dropna().iloc[[-1]] if not features.dropna().empty else None
    if current is None or len(model_frame) < max(260, days + 100):
        return {
            **horizon_spec,
            "status": "unavailable",
            "reason": "Not enough non-overlapping market history for this horizon.",
            "data_points": len(model_frame),
        }

    X = model_frame.drop(columns="target")
    y = model_frame["target"].astype(int)
    if y.nunique() < 2:
        return {
            **horizon_spec,
            "status": "unavailable",
            "reason": "Historical outcomes contain only one class.",
            "data_points": len(model_frame),
        }

    out_probabilities = []
    out_targets = []
    fold_rows = []
    for fold_number, (train_slice, validation_slice) in enumerate(
        _walk_forward_slices(len(X), days), 1
    ):
        X_train, y_train = X.iloc[train_slice], y.iloc[train_slice]
        X_validation, y_validation = X.iloc[validation_slice], y.iloc[validation_slice]
        if y_train.nunique() < 2 or X_validation.empty:
            continue
        models = _model_pair()
        models[0].fit(X_train, y_train)
        models[1].fit(X_train, y_train)
        raw = _pair_probability(models, X_validation)
        out_probabilities.extend(raw.tolist())
        out_targets.extend(y_validation.tolist())
        fold_rows.append({
            "fold": fold_number,
            "training_rows": len(X_train),
            "validation_rows": len(X_validation),
            "up_probability": _finite_float(np.mean(raw)),
            "accuracy": _finite_float(accuracy_score(y_validation, raw >= 0.5)),
            "brier_score": _finite_float(brier_score_loss(y_validation, raw)),
        })

    if len(out_targets) < 60 or len(set(out_targets)) < 2 or len(fold_rows) < 2:
        return {
            **horizon_spec,
            "status": "unavailable",
            "reason": "Walk-forward validation did not produce enough resolved outcomes.",
            "data_points": len(model_frame),
            "validation_samples": len(out_targets),
        }

    raw_oof = np.asarray(out_probabilities, dtype=float)
    y_oof = np.asarray(out_targets, dtype=int)
    calibration_cut = len(y_oof) // 2
    calibration_train_y = y_oof[:calibration_cut]
    evaluation_y = y_oof[calibration_cut:]
    if len(set(calibration_train_y)) < 2 or len(set(evaluation_y)) < 2:
        return {
            **horizon_spec,
            "status": "unavailable",
            "reason": "The held-out calibration period does not contain both outcomes.",
            "data_points": len(model_frame),
            "validation_samples": len(out_targets),
        }
    evaluation_calibrator = LogisticRegression(max_iter=1000, random_state=42)
    evaluation_calibrator.fit(raw_oof[:calibration_cut].reshape(-1, 1), calibration_train_y)
    calibrated_evaluation = evaluation_calibrator.predict_proba(
        raw_oof[calibration_cut:].reshape(-1, 1)
    )[:, 1]

    # Refit the sigmoid on every out-of-sample model prediction only after the
    # calibration quality has been assessed on its untouched later half.
    calibrator = LogisticRegression(max_iter=1000, random_state=42)
    calibrator.fit(raw_oof.reshape(-1, 1), y_oof)

    final_models = _model_pair()
    final_models[0].fit(X, y)
    final_models[1].fit(X, y)
    raw_current = float(_pair_probability(final_models, current)[0])
    probability = float(calibrator.predict_proba(np.asarray([[raw_current]]))[:, 1][0])

    base_rate = float(np.mean(calibration_train_y))
    baseline_probability = np.full(len(evaluation_y), base_rate)
    accuracy = float(accuracy_score(evaluation_y, calibrated_evaluation >= 0.5))
    baseline_accuracy = max(base_rate, 1.0 - base_rate)
    brier = float(brier_score_loss(evaluation_y, calibrated_evaluation))
    baseline_brier = float(brier_score_loss(evaluation_y, baseline_probability))
    brier_skill = (1.0 - brier / baseline_brier) * 100.0 if baseline_brier > 0 else 0.0
    probability_std = float(np.std([row["up_probability"] for row in fold_rows]))
    stability = "Stable" if probability_std <= 0.05 else "Variable" if probability_std <= 0.10 else "Unstable"
    effective_samples = max(len(fold_rows), round(len(evaluation_y) / max(1, days)))
    minimum_effective = 8 if days <= 5 else 5 if days <= 21 else 4
    reliable = (
        brier_skill >= 2.0
        and accuracy >= baseline_accuracy - 0.02
        and effective_samples >= minimum_effective
    )
    quality = (
        "Strong" if reliable and brier_skill >= 12 and len(y_oof) >= 180 and stability == "Stable"
        else "Usable" if reliable
        else "Insufficient"
    )
    reason = (
        "Walk-forward probability clears the held-out historical base-rate and sample-quality checks."
        if reliable else
        "Directional output is suppressed because held-out skill or effective history is insufficient."
    )
    forest_importance = final_models[1].feature_importances_
    importance_total = float(np.sum(forest_importance)) or 1.0
    importance = sorted(
        (
            {
                "feature": key,
                "label": FEATURE_LABELS.get(key, key),
                "importance_pct": _finite_float(value / importance_total * 100.0),
            }
            for key, value in zip(X.columns, forest_importance)
        ),
        key=lambda row: row["importance_pct"] or 0.0,
        reverse=True,
    )[:5]
    return {
        **horizon_spec,
        "status": "ok",
        "data_points": len(model_frame),
        "direction": _direction(probability, reliable),
        "up_probability": _finite_float(probability),
        "down_probability": _finite_float(1.0 - probability),
        "raw_probability": _finite_float(raw_current),
        "signal_suppressed": not reliable,
        "quality": quality,
        "quality_reason": reason,
        "validation": {
            "method": "Three expanding walk-forward windows use a horizon-length leakage gap. A sigmoid is trained on the earlier half of out-of-sample predictions and scored on the untouched later half.",
            "folds": len(fold_rows),
            "walk_forward_samples": len(y_oof),
            "samples": len(evaluation_y),
            "effective_non_overlapping_samples": effective_samples,
            "accuracy": _finite_float(accuracy),
            "baseline_accuracy": _finite_float(baseline_accuracy),
            "brier_score": _finite_float(brier),
            "baseline_brier_score": _finite_float(baseline_brier),
            "brier_skill_pct": _finite_float(brier_skill),
            "log_loss": _finite_float(log_loss(evaluation_y, calibrated_evaluation, labels=[0, 1])),
            "fold_probability_std": _finite_float(probability_std),
            "stability": stability,
            "folds_detail": fold_rows,
        },
        "feature_importance": importance,
    }


def analyze_frame(frame, horizons=HORIZONS):
    """Run the deterministic quant layer on a supplied OHLCV history."""
    if frame is None or frame.empty:
        return {"status": "No market data available."}
    required = {"Close", "Volume"}
    if not required.issubset(frame.columns):
        return {"status": "Market history is missing Close or Volume data."}
    frame = frame.copy().sort_index()
    close = frame["Close"].astype(float)
    features = _feature_frame(frame)
    horizon_rows = [_horizon_model(features, close, spec) for spec in horizons]
    available = [row for row in horizon_rows if row.get("status") == "ok"]
    if not available:
        return {
            "status": "Not enough historical observations for a validated directional model.",
            "data_points": int(features.dropna().shape[0]),
            "price": _finite_float(close.iloc[-1]),
            "horizons": horizon_rows,
        }
    primary = next((row for row in available if row["key"] == "21d"), available[0])
    sma20 = close.rolling(20).mean().iloc[-1]
    sma60 = close.rolling(60).mean().iloc[-1]
    zones = {
        "support20": close.tail(20).min(),
        "resistance20": close.tail(20).max(),
        "support60": close.tail(60).min(),
        "resistance60": close.tail(60).max(),
    }
    skill = max(0.0, float(primary["validation"]["brier_skill_pct"] or 0.0))
    confidence = abs(float(primary["up_probability"]) - 0.5) * 200.0 * min(1.0, skill / 15.0)
    latest_features = features.dropna().iloc[-1].to_dict()
    return {
        "status": "ok",
        "data_points": int(primary["data_points"]),
        "price": _finite_float(close.iloc[-1]),
        "primary_horizon": primary["key"],
        "primary_horizon_label": primary["label"],
        "direction": primary["direction"],
        "up_probability": primary["up_probability"],
        "down_probability": primary["down_probability"],
        "confidence": _finite_float(confidence),
        "validation_accuracy": primary["validation"]["accuracy"],
        "validation": primary["validation"],
        "signal_suppressed": primary["signal_suppressed"],
        "quality": primary["quality"],
        "quality_reason": primary["quality_reason"],
        "horizons": horizon_rows,
        "features": {key: _finite_float(value) for key, value in latest_features.items()},
        "feature_importance": primary["feature_importance"],
        "moving_averages": {"sma20": _finite_float(sma20), "sma60": _finite_float(sma60)},
        "zones": {key: _finite_float(value) for key, value in zones.items()},
        "warning": (
            "Probabilities are calibrated from historical walk-forward tests, not guarantees. "
            "Signals that fail the historical probability baseline are shown as uncertain."
        ),
    }

def analyze(company):
    ticker = ticker_for(company)
    try:
        frame = market_history(ticker, period=STOCK_PERIOD, interval="1d", auto_adjust=False)

        if frame.empty:
            return {
                "status": "No market data available.",
                "ticker": ticker,
            }

        latest_date = pd.Timestamp(frame.index[-1]).isoformat()
        latest_close = _finite_float(frame["Close"].iloc[-1]) if "Close" in frame else None
        model_key = f"stock:{APP_VERSION}:{ticker}:{latest_date}:{latest_close}"
        cached = MODEL_CACHE.get(model_key, ttl=3600.0, stale_ttl=86400.0)
        if cached:
            return dict(cached.value)
        result = analyze_frame(frame)
        result["ticker"] = ticker
        result["model_cache_key"] = model_key
        MODEL_CACHE.put(model_key, result)
        return result

    except Exception as exc:
        return {
            "status": "Market analysis unavailable.",
            "ticker": ticker,
            "error": str(exc),
        }



def _direct_yahoo_quote(ticker):
    import requests
    url = "https://query1.finance.yahoo.com/v7/finance/quote"
    r = requests.get(url, params={"symbols": ticker}, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    rows = (r.json().get("quoteResponse") or {}).get("result") or []
    return rows[0] if rows else {}


# Lightweight market fundamentals snapshot for the Company Overview. Dividend
# history is opt-in because it is only needed by the valuation workspace and
# may require an additional provider request.
def market_snapshot(company, include_dividends=False):
    ticker = ticker_for(company)
    snapshot_key = f"fundamentals:{ticker}:{'dividends' if include_dividends else 'core'}"
    cached_snapshot = MARKET_CACHE.get(snapshot_key, ttl=300.0, stale_ttl=86400.0)
    if cached_snapshot and cached_snapshot.fresh:
        return {**cached_snapshot.value, "cache_hit": True}
    info = {}
    fast = {}
    frame = None
    ticker_client = None
    dividend_history = []
    errors=[]
    # Preferred: yfinance, already an existing project dependency.
    try:
        import yfinance as yf
        ticker_client = yf.Ticker(ticker)
        info = ticker_client.info or {}
        fast = getattr(ticker_client, "fast_info", {}) or {}
        frame = market_history(ticker, period="3mo", interval="1d", auto_adjust=False)
        if include_dividends:
            dividends = getattr(ticker_client, "dividends", None)
            if dividends is not None and not getattr(dividends, "empty", True):
                for paid_at, amount in dividends.tail(16).items():
                    try:
                        dividend_history.append({
                            "date": pd.Timestamp(paid_at).date().isoformat(),
                            "amount": _finite_float(amount),
                        })
                    except Exception:
                        continue
    except Exception as exc:
        errors.append(f"yfinance: {exc}")
    # Fallback: Yahoo quote endpoint. This avoids making the UI depend on the
    # optional yfinance package being importable at runtime.
    if not info:
        try:
            info = _direct_yahoo_quote(ticker)
        except Exception as exc:
            errors.append(f"Yahoo quote: {exc}")
    price = info.get("regularMarketPrice") or info.get("currentPrice") or fast.get("last_price")
    trailing_eps = info.get("trailingEps") or info.get("epsTrailingTwelveMonths")
    pe = info.get("trailingPE")
    pb = info.get("priceToBook")
    shares = info.get("sharesOutstanding") or info.get("impliedSharesOutstanding")
    market_cap = info.get("marketCap")
    if market_cap is None and price is not None and shares is not None:
        market_cap = float(price) * float(shares)
    if shares is None and market_cap is not None and price not in (None, 0):
        shares = float(market_cap) / float(price)
    if pe is None and price is not None and trailing_eps not in (None, 0):
        pe = float(price) / float(trailing_eps)
    if trailing_eps is None and price is not None and pe not in (None, 0):
        trailing_eps = float(price) / float(pe)
    if pb is None and price is not None:
        book_value = info.get("bookValue")
        if book_value not in (None, 0):
            pb = float(price) / float(book_value)
    book_value = info.get("bookValue")
    if book_value is None and price is not None and pb not in (None, 0):
        book_value = float(price) / float(pb)
    avg10 = None
    if frame is not None and not frame.empty and "Volume" in frame:
        avg10 = float(pd.to_numeric(frame["Volume"], errors="coerce").tail(10).mean())
    if avg10 is None:
        try:
            avg10 = info.get("averageDailyVolume10Day") or info.get("averageDailyVolume3Month")
        except Exception:
            pass
    last_time = info.get("regularMarketTime")
    updated = None
    if last_time:
        try:
            from datetime import datetime, timezone
            updated = datetime.fromtimestamp(int(last_time), tz=timezone.utc).isoformat()
        except Exception:
            updated = None
    if price is None and not info:
        if cached_snapshot:
            return {**cached_snapshot.value, "cache_hit": True, "stale_fallback": True}
        return {"success": False, "ticker": ticker, "error": "Market data provider unavailable. " + " | ".join(errors), "source": "Yahoo Finance"}
    ex_dividend_date = info.get("exDividendDate")
    if ex_dividend_date:
        try:
            from datetime import datetime, timezone
            ex_dividend_date = datetime.fromtimestamp(int(ex_dividend_date), tz=timezone.utc).date().isoformat()
        except Exception:
            ex_dividend_date = None
    dividend_yield = _finite_float(info.get("dividendYield") or info.get("trailingAnnualDividendYield"))
    payout_ratio = _finite_float(info.get("payoutRatio"))
    earnings_growth = _finite_float(info.get("earningsGrowth"))
    revenue_growth = _finite_float(info.get("revenueGrowth"))
    gross_margin = _finite_float(info.get("grossMargins"))
    operating_margin = _finite_float(info.get("operatingMargins"))
    profit_margin = _finite_float(info.get("profitMargins"))
    return_on_equity = _finite_float(info.get("returnOnEquity"))
    if dividend_yield is not None and abs(dividend_yield) <= 1.5:
        dividend_yield *= 100.0
    if payout_ratio is not None and abs(payout_ratio) <= 1.5:
        payout_ratio *= 100.0
    if earnings_growth is not None and abs(earnings_growth) <= 1.5:
        earnings_growth *= 100.0
    if revenue_growth is not None and abs(revenue_growth) <= 1.5:
        revenue_growth *= 100.0
    if gross_margin is not None and abs(gross_margin) <= 1.5:
        gross_margin *= 100.0
    if operating_margin is not None and abs(operating_margin) <= 1.5:
        operating_margin *= 100.0
    if profit_margin is not None and abs(profit_margin) <= 1.5:
        profit_margin *= 100.0
    if return_on_equity is not None and abs(return_on_equity) <= 1.5:
        return_on_equity *= 100.0
    free_cash_flow = info.get("freeCashflow")
    operating_cash_flow = info.get("operatingCashflow") or info.get("operatingCashflowTrailingTwelveMonths")
    capital_expenditure = info.get("capitalExpenditures")
    total_debt = _finite_float(info.get("totalDebt"))
    total_cash = _finite_float(info.get("totalCash"))
    ebitda = _finite_float(info.get("ebitda"))
    net_debt_to_ebitda = None
    if ebitda is not None and ebitda > 0 and total_debt is not None:
        net_debt_to_ebitda = (total_debt - (total_cash or 0.0)) / ebitda
    payload = {
        "success": True,
        "ticker": ticker,
        "price": _finite_float(price),
        "pe": _finite_float(pe),
        "pb": _finite_float(pb),
        "eps": _finite_float(trailing_eps),
        "forward_pe": _finite_float(info.get("forwardPE")),
        "book_value_per_share": _finite_float(book_value),
        "market_cap": _finite_float(market_cap),
        "shares_outstanding": _finite_float(shares),
        "free_cash_flow": _finite_float(free_cash_flow),
        "operating_cash_flow": _finite_float(operating_cash_flow),
        "capital_expenditure": _finite_float(capital_expenditure),
        "dividend_rate": _finite_float(
            info.get("dividendRate")
            or info.get("trailingAnnualDividendRate")
            or (float(price) * float(dividend_yield) / 100.0 if price is not None and dividend_yield is not None else None)
        ),
        "dividend_yield_pct": _finite_float(dividend_yield),
        "payout_ratio_pct": _finite_float(payout_ratio),
        "earnings_growth_pct": _finite_float(earnings_growth),
        "revenue_growth_pct": _finite_float(revenue_growth),
        "gross_margin_pct": _finite_float(gross_margin),
        "operating_margin_pct": _finite_float(operating_margin),
        "profit_margin_pct": _finite_float(profit_margin),
        "return_on_equity_pct": _finite_float(return_on_equity),
        "net_debt_to_ebitda": _finite_float(net_debt_to_ebitda),
        "beta": _finite_float(info.get("beta")),
        "ex_dividend_date": ex_dividend_date,
        "dividend_history": dividend_history if include_dividends else [],
        "avg_volume_10d": _finite_float(avg10),
        "currency": info.get("currency") or fast.get("currency") or "VND",
        "market_state": info.get("marketState"),
        "updated_at": updated,
        "source": "Yahoo Finance / yfinance or Yahoo quote fallback",
        "warning": "Market fields may be delayed; the timestamp is the freshness check. Financial statement KPIs remain sourced from your verified local reports.",
        "errors": errors[-2:],
    }
    MARKET_CACHE.put(snapshot_key, payload)
    return {**payload, "cache_hit": False}



# Overview dashboard market carousel. Kept separate from company analysis so the
# existing stock/risk features remain unchanged.
_WORLD_MARKET_CACHE = {"intraday": {"ts": 0.0, "data": None}, "daily": {"ts": 0.0, "data": None}}
_WORLD_MARKET_CACHE_TTL = 45.0
_WORLD_MARKET_DAILY_TTL = 300.0

WORLD_MARKETS = [
    ("^VNINDEX", "VN-INDEX", "Vietnam"),
    ("^GSPC", "S&P 500", "United States"),
    ("^IXIC", "NASDAQ", "United States"),
    ("^DJI", "DOW JONES", "United States"),
    ("GC=F", "GOLD", "Commodities"),
    ("CL=F", "OIL (WTI)", "Commodities"),
    ("^N225", "Nikkei 225", "Japan"),
    ("^HSI", "Hang Seng", "Hong Kong"),
    ("^GDAXI", "DAX", "Germany"),
    ("^FTSE", "FTSE 100", "United Kingdom"),
    ("^STI", "Straits Times", "Singapore"),
    ("^KS11", "KOSPI", "South Korea"),
]


def _world_market_item(symbol, label, region, force=False, mode="intraday", frame=None):
    import time
    if frame is None:
        frame = market_history(
            symbol,
            period="3mo" if mode == "daily" else "2d",
            interval="1d" if mode == "daily" else "15m",
            auto_adjust=False,
            force=force,
        )
    if frame is None or frame.empty:
        raise RuntimeError("No market observations returned.")
    col = "Close" if "Close" in frame.columns else frame.columns[0]
    values = pd.to_numeric(frame[col], errors="coerce").dropna()
    if values.empty:
        raise RuntimeError("No valid price observations returned.")
    points=[]
    for idx,val in values.tail(160).items():
        ts=pd.Timestamp(idx)
        points.append({"date":ts.isoformat(),"value":float(val)})
    latest=points[-1]
    if mode == "daily":
        base=points[-2]["value"] if len(points)>1 else latest["value"]
    else:
        try:
            latest_day=pd.Timestamp(latest["date"]).date()
            session=[x for x in points if pd.Timestamp(x["date"]).date()==latest_day]
        except Exception:
            session=points
        base=session[0]["value"] if session else points[-2]["value"] if len(points)>1 else latest["value"]
    change_pct=((latest["value"]/base)-1.0)*100.0 if base else None
    return {"success":True,"symbol":symbol,"label":label,"region":region,"points":points,"latest":latest,"change_pct":_finite_float(change_pct),"source":"Yahoo Finance","url":f"https://finance.yahoo.com/quote/{symbol}","updated_at":time.time(),"intraday":mode!="daily","refresh_seconds":60}


def world_market_snapshot(force=False, mode="intraday"):
    import time
    now=time.time()
    key="daily" if mode=="daily" else "intraday"
    ttl=_WORLD_MARKET_DAILY_TTL if key=="daily" else _WORLD_MARKET_CACHE_TTL
    cache=_WORLD_MARKET_CACHE[key]
    if not force and cache["data"] is not None and now-cache["ts"]<ttl:
        return cache["data"]
    period="3mo" if key=="daily" else "2d"
    interval="1d" if key=="daily" else "15m"
    symbols=[row[0] for row in WORLD_MARKETS]
    frames=market_batch_history(symbols,period=period,interval=interval,auto_adjust=False,force=force)
    results=[]
    for sym,label,region in WORLD_MARKETS:
        try:
            results.append(_world_market_item(sym,label,region,force,key,frames.get(sym)))
        except Exception as exc:
            results.append({"success":False,"symbol":sym,"label":label,"region":region,"points":[],"latest":{"date":None,"value":None},"change_pct":None,"source":"Yahoo Finance","url":f"https://finance.yahoo.com/quote/{sym}","error":str(exc),"intraday":key!="daily","refresh_seconds":60})
    order={sym:i for i,(sym,_,_) in enumerate(WORLD_MARKETS)}
    results.sort(key=lambda x:order.get(x.get("symbol"),999))
    payload={"success":True,"updated_at":now,"refresh_seconds":60,"markets":results,"live":True,"mode":key,"request_strategy":"one batched provider request","note":"Daily graph snapshot loads first; intraday quotes are a second-stage refresh when the provider is publishing observations."}
    cache.update({"ts":now,"data":payload})
    return payload
