from __future__ import annotations

import io
import re
import time
from datetime import datetime, timezone
from typing import Any

import pandas as pd
import requests

from .provider_cache import MACRO_CACHE

HNX_CURVE_URLS = [
    "https://www.hnx.vn/vi-vn/m-trai-phieu/duong-cong-loi-suat.html",
    "https://www-.hnx.vn/vi-vn/m-trai-phieu/duong-cong-loi-suat.html",
    "https://ccbonds.hnx.vn/vi-vn/m-trai-phieu/duong-cong-loai-suat.html",
]
HNX_CURVE_URL = HNX_CURVE_URLS[0]
FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"

# Last verified HNX snapshot used only when the official page cannot be read.
# It is explicitly labeled SNAPSHOT in the UI.
HNX_SNAPSHOT = [
    {"tenor":"3 tháng","months":3,"annual_spot_pct":3.8563,"par_yield_pct":3.8683},
    {"tenor":"6 tháng","months":6,"annual_spot_pct":3.8761,"par_yield_pct":3.8882},
    {"tenor":"9 tháng","months":9,"annual_spot_pct":3.8958,"par_yield_pct":3.9082},
    {"tenor":"1 năm","months":12,"annual_spot_pct":3.9152,"par_yield_pct":3.9283},
    {"tenor":"2 năm","months":24,"annual_spot_pct":3.9905,"par_yield_pct":4.0039},
    {"tenor":"3 năm","months":36,"annual_spot_pct":4.0623,"par_yield_pct":4.0762},
    {"tenor":"5 năm","months":60,"annual_spot_pct":4.1955,"par_yield_pct":4.2103},
    {"tenor":"7 năm","months":84,"annual_spot_pct":4.3150,"par_yield_pct":4.3301},
    {"tenor":"10 năm","months":120,"annual_spot_pct":4.4692,"par_yield_pct":4.4845},
    {"tenor":"15 năm","months":180,"annual_spot_pct":4.6622,"par_yield_pct":4.6777},
    {"tenor":"20 năm","months":240,"annual_spot_pct":4.7793,"par_yield_pct":4.7950},
]

_CACHE: dict[str, tuple[float, Any]] = {}
_TTL = 60.0
_FRED_TTLS = {
    # Release series change weekly or monthly; polling them every minute only
    # creates provider pressure and cannot reveal a newer official release.
    "GASREGW": 6 * 60 * 60,
    "DFF": 15 * 60,
}
_DEFAULT_FRED_TTL = 6 * 60 * 60


def _cached(key: str, loader, force: bool = False, ttl: float = _TTL):
    now = time.time()
    item = _CACHE.get(key)
    if item and now - item[0] < ttl and not force:
        return item[1]
    value = loader()
    _CACHE[key] = (now, value)
    return value


def _get(url: str, timeout: int = 10):
    r = requests.get(url, timeout=timeout, headers={"User-Agent": "FinancialAI/16.0"})
    r.raise_for_status()
    return r


def _fred(series: str, force: bool = False) -> pd.DataFrame:
    ttl = float(_FRED_TTLS.get(series, _DEFAULT_FRED_TTL))
    cache_key = f"fred:{series}:320"
    cached = MACRO_CACHE.get(cache_key, ttl=ttl, stale_ttl=30 * 24 * 60 * 60)
    if cached and cached.fresh and not force:
        frame = pd.DataFrame(cached.value or [])
        if not frame.empty:
            frame["observation_date"] = pd.to_datetime(frame["observation_date"], errors="coerce")
            frame[series] = pd.to_numeric(frame[series], errors="coerce")
            return frame.dropna(subset=["observation_date", series]).tail(320)

    def load():
        raw = _get(FRED_CSV.format(series=series), timeout=12).content
        df = pd.read_csv(io.BytesIO(raw))
        df["observation_date"] = pd.to_datetime(df["observation_date"], errors="coerce")
        df[series] = pd.to_numeric(df[series], errors="coerce")
        return df.dropna(subset=["observation_date", series]).tail(320)
    try:
        frame = _cached(f"fred:{series}", load, force=force, ttl=ttl)
        MACRO_CACHE.put(cache_key, [
            {"observation_date": date.strftime("%Y-%m-%d"), series: float(value)}
            for date, value in zip(frame["observation_date"], frame[series])
        ])
        return frame
    except Exception:
        if cached:
            frame = pd.DataFrame(cached.value or [])
            if not frame.empty:
                frame["observation_date"] = pd.to_datetime(frame["observation_date"], errors="coerce")
                frame[series] = pd.to_numeric(frame[series], errors="coerce")
                frame = frame.dropna(subset=["observation_date", series]).tail(320)
                if not frame.empty:
                    return frame
        raise


def _fred_series(series: str, label: str, unit: str = "", force: bool = False, limit: int = 120) -> dict[str, Any]:
    try:
        df = _fred(series, force=force)
        points = [{"date": d.strftime("%Y-%m-%d"), "value": float(v)} for d, v in zip(df["observation_date"].tail(limit), df[series].tail(limit))]
        return {"success": True, "series": series, "label": label, "unit": unit, "points": points, "latest": points[-1] if points else {"date": None, "value": None}, "source": "FRED / Federal Reserve Bank of St. Louis", "url": f"https://fred.stlouisfed.org/series/{series}"}
    except Exception as exc:
        return {"success": False, "series": series, "label": label, "unit": unit, "points": [], "latest": {"date": None, "value": None}, "source": "FRED / Federal Reserve Bank of St. Louis", "url": f"https://fred.stlouisfed.org/series/{series}", "error": str(exc)}


def _yahoo_history(symbol: str, label: str, unit: str = "", period: str = "6mo", interval: str = "1d", force: bool = False, limit: int = 180) -> dict[str, Any]:
    def load():
        from .market_data import history as market_history

        frame = market_history(symbol, period=period, interval=interval, force=force)
        if frame is None or frame.empty:
            raise RuntimeError("No market observations returned.")
        col = "Close" if "Close" in frame.columns else frame.columns[0]
        values = pd.to_numeric(frame[col], errors="coerce").dropna()
        points=[]
        for idx,val in values.tail(limit).items():
            ts = pd.Timestamp(idx)
            points.append({"date": ts.isoformat(), "value": float(val)})
        return points
    try:
        points = _cached(f"yf:{symbol}:{period}:{interval}", load, force=force, ttl=45.0)
        return {"success": True, "symbol": symbol, "label": label, "unit": unit, "points": points, "latest": points[-1] if points else {"date": None, "value": None}, "source": "Yahoo Finance", "url": f"https://finance.yahoo.com/quote/{symbol}"}
    except Exception as exc:
        return {"success": False, "symbol": symbol, "label": label, "unit": unit, "points": [], "latest": {"date": None, "value": None}, "source": "Yahoo Finance", "url": f"https://finance.yahoo.com/quote/{symbol}", "error": str(exc)}


def _parse_hnx_curve(html: str):
    tables = []
    try:
        tables = pd.read_html(io.StringIO(html))
    except Exception:
        tables = []
    target = None
    for table in tables:
        flat_cols=[]
        for c in table.columns:
            if isinstance(c, tuple): flat_cols.append(" ".join(str(x) for x in c if str(x).lower()!='nan'))
            else: flat_cols.append(str(c))
        text = " ".join(flat_cols) + " " + " ".join(table.astype(str).fillna("").head(30).to_numpy().ravel())
        low = text.lower()
        if "spot rate theo năm" in low and any(x in low for x in ("3 tháng","6 tháng","2 năm","10 năm")):
            target = table.copy(); break
        if "spot rate" in low and "kỳ hạn" in low and "10 năm" in low:
            target = table.copy(); break
    if target is None:
        plain=re.sub(r"<script.*?</script>|<style.*?</style>"," ",html,flags=re.S|re.I)
        plain=re.sub(r"<[^>]+>"," ",plain)
        plain=re.sub(r"\s+"," ",plain)
        tenors=["3 tháng","6 tháng","9 tháng","1 năm","2 năm","3 năm","5 năm","7 năm","10 năm","15 năm","20 năm"]
        rows=[]
        for tenor in tenors:
            m=re.search(re.escape(tenor)+r"\s+([\d.,]+)\s+([^\s]+)\s+([\d.,]+)",plain,re.I)
            if m: rows.append([tenor,m.group(1),m.group(2),m.group(3)])
        if not rows: raise RuntimeError("HNX Spot Rate table was not found.")
        target=pd.DataFrame(rows,columns=["Kỳ hạn","Spot rate liên tục (%)","Par yield (%)","Spot rate theo năm (%)"])
    target.columns=[str(c[0] if isinstance(c,tuple) else c).strip() for c in target.columns]
    annual_col=next((c for c in target.columns if "spot rate theo năm" in str(c).lower()), target.columns[-1])
    par_col=next((c for c in target.columns if "par yield" in str(c).lower()), None)
    tenor_col=next((c for c in target.columns if "kỳ hạn" in str(c).lower() or "tenor" in str(c).lower()), target.columns[0])
    months_map={"3 tháng":3,"6 tháng":6,"9 tháng":9,"1 năm":12,"2 năm":24,"3 năm":36,"5 năm":60,"7 năm":84,"10 năm":120,"15 năm":180,"20 năm":240}
    rows=[]
    for _,r in target.iterrows():
        tenor=str(r.get(tenor_col," ")).strip()
        if tenor not in months_map: continue
        def numv(v):
            s=str(v).strip().replace("%","").replace(",",".")
            try: return float(s)
            except Exception: return None
        annual=numv(r.get(annual_col)); par=numv(r.get(par_col)) if par_col else None
        if annual is None: continue
        rows.append({"tenor":tenor,"months":months_map[tenor],"annual_spot_pct":annual,"par_yield_pct":par})
    if len(rows)<5: raise RuntimeError("HNX Spot Rate table was incomplete.")
    rows.sort(key=lambda x:x["months"])
    return rows


def _load_hnx_curve(force=False):
    errors=[]
    for url in HNX_CURVE_URLS:
        try:
            html=_get(url,timeout=12).text
            data=_parse_hnx_curve(html)
            return data,url,None,True
        except Exception as exc:
            errors.append(f"{url}: {exc}")
    return list(HNX_SNAPSHOT),HNX_CURVE_URL," | ".join(errors),False


def _latest_unemployment_vietnam() -> dict[str, Any]:
    url = "https://www.nso.gov.vn/"
    candidates = [
        "https://www.nso.gov.vn/tin-tuc-thong-ke/2026/07/thong-cao-bao-chi-ve-tinh-hinh-lao-dong-viec-lam-quy-ii-va-6-thang-dau-nam-2026/",
    ]
    for target in candidates:
        try:
            html = _get(target).text
            m = re.search(r"tỷ lệ thất nghiệp trong độ tuổi lao động[^%]{0,160}?([0-9]+,[0-9]+)%", html, flags=re.I)
            val = float(m.group(1).replace(",", ".")) if m else None
            return {"value_pct": val, "period": "Q2 2026", "source": "Vietnam NSO", "url": target}
        except Exception:
            continue
    return {"value_pct": None, "period": None, "source": "Vietnam NSO", "url": url, "error": "Official NSO page unavailable."}


def _trend_state(points: list[dict[str, Any]], higher_is_positive: bool = True) -> str:
    vals=[float(x["value"]) for x in points[-10:] if x.get("value") is not None]
    if len(vals)<2: return "UNAVAILABLE"
    delta=vals[-1]-vals[0]
    if abs(delta) < max(abs(vals[-1])*0.002, 1e-9): return "STABLE"
    up=delta>0
    return "IMPROVING" if (up and higher_is_positive) or ((not up) and (not higher_is_positive)) else "WEAKENING"


def _market_bundle(force=False):
    from .market_data import batch_history as market_batch_history

    symbols=[
        ("GC=F","Gold","USD/oz"),
        ("USDVND=X","USD/VND","VND per USD"),
        ("EURUSD=X","EUR/USD","USD per EUR"),
        ("USDJPY=X","USD/JPY","JPY per USD"),
        ("USDCNY=X","USD/CNY","CNY per USD"),
        ("^VNINDEX","VN-Index","points"),
        ("^VN30","VN30","points"),
        ("^HNX","HNX-Index","points"),
    ]
    out={}
    frames = market_batch_history(
        [item[0] for item in symbols], period="10d", interval="15m", force=force,
    )
    for sym, label, unit in symbols:
        frame = frames.get(sym)
        if frame is None or frame.empty:
            out[sym] = {
                "success": False, "symbol": sym, "label": label, "unit": unit,
                "points": [], "latest": {"date": None, "value": None},
                "source": "Yahoo Finance", "url": f"https://finance.yahoo.com/quote/{sym}",
                "error": "No market observations returned.",
            }
            continue
        column = "Close" if "Close" in frame.columns else frame.columns[0]
        points = []
        for index, value in pd.to_numeric(frame[column], errors="coerce").dropna().tail(160).items():
            points.append({"date": pd.Timestamp(index).isoformat(), "value": float(value)})
        out[sym] = {
            "success": bool(points), "symbol": sym, "label": label, "unit": unit,
            "points": points, "latest": points[-1] if points else {"date": None, "value": None},
            "source": "Yahoo Finance", "url": f"https://finance.yahoo.com/quote/{sym}",
        }
    return out


def _scenario_summary(out: dict[str, Any]) -> dict[str, Any]:
    def latest(name, default=None):
        obj=out.get(name,{})
        return obj.get("latest",{}).get("value", default)
    fed=latest("fed_rate")
    pmi=latest("pmi")
    rec=latest("recession_probability")
    sahm=out.get("us_sahm",{}).get("latest_indicator_pp")
    gold=latest("GC=F")
    usdvnd=latest("USDVND=X")
    vnidx=latest("^VNINDEX")
    parts=[]
    if pmi is not None: parts.append(f"U.S. manufacturing PMI is {pmi:.1f} ({'expansion' if pmi>=50 else 'contraction'} zone).")
    if fed is not None: parts.append(f"The effective Fed funds rate is {fed:.2f}%.")
    if rec is not None: parts.append(f"The published median U.S. recession probability is {rec:.2f}%.")
    if sahm is not None: parts.append(f"The Sahm indicator is {sahm:.2f} pp ({'signal' if sahm>=0.5 else 'below trigger'}).")
    if gold is not None: parts.append(f"Gold is around {gold:,.0f} USD/oz in the latest market feed.")
    if usdvnd is not None: parts.append(f"USD/VND is around {usdvnd:,.0f}.")
    if vnidx is not None: parts.append(f"VN-Index is around {vnidx:,.0f}.")
    implications=[]
    if pmi is not None and pmi>=50 and (sahm is None or sahm<0.5) and (rec is None or rec<10):
        implications.append("Base case: the global cycle currently reads more like continued expansion than an imminent U.S. recession, which is generally more supportive for cyclical and growth risk assets.")
    elif pmi is not None and pmi<50 or (sahm is not None and sahm>=0.5) or (rec is not None and rec>=20):
        implications.append("Downside case: weaker manufacturing or a rising recession signal would typically pressure cyclicals, raise demand for defensive assets, and tighten financial conditions.")
    if fed is not None and pmi is not None:
        implications.append("If rates stay high while PMI weakens, valuation multiples and financing-sensitive sectors can face more pressure; if rates fall while PMI stabilizes, liquidity-sensitive assets can receive support.")
    if usdvnd is not None:
        implications.append("A stronger USD versus VND can raise imported-cost and foreign-funding pressure for some Vietnamese businesses; a stable or softer USD/VND is usually friendlier to domestic liquidity.")
    return {"headline":" | ".join(parts) if parts else "Live macro observations are currently unavailable.","implications":implications,"updated_at":datetime.now(timezone.utc).isoformat()}


def macro_snapshot(force: bool = False) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    out: dict[str, Any] = {"success": True, "updated_at": now, "sources": [], "warnings": [], "refresh_seconds": 300, "live_market": True}

    hnx, hnx_url, hnx_error, hnx_live = _load_hnx_curve(force=force)
    if hnx:
        two=next((x["annual_spot_pct"] for x in hnx if x["months"]==24),None); ten=next((x["annual_spot_pct"] for x in hnx if x["months"]==120),None)
        status="LIVE" if hnx_live else "SNAPSHOT"
        source="HNX Government Bond Spot Rate Curve" if hnx_live else "HNX Government Bond Spot Rate Curve (last verified snapshot)"
        out["hnx_curve"]={"points":hnx,"spread_10y_2y_pp":(ten-two) if ten is not None and two is not None else None,"source":source,"url":hnx_url,"status":status,"live":bool(hnx_live),"error":hnx_error}
        out["sources"].append("HNX" if hnx_live else "HNX snapshot")
        if not hnx_live: out["warnings"].append("Live HNX curve is unavailable; the last verified snapshot is shown and labeled SNAPSHOT.")
    else:
        out["hnx_curve"]={"points":[],"spread_10y_2y_pp":None,"source":"HNX Government Bond Spot Rate Curve","url":HNX_CURVE_URL,"status":"Unavailable"}
        out["warnings"].append("HNX curve unavailable.")

    # Required global macro series.
    series_specs=[
        ("UNRATE","unemployment","U.S. Unemployment Rate","%",120),
        ("SAHMCURRENT","sahm_series","Claudia Sahm Rule","pp",120),
        ("DFF","fed_rate","Effective Federal Funds Rate","%",120),
        ("RECRISKUSP50","recession_probability","U.S. Recession Probability","%",80),
        ("NAPM","pmi","ISM Manufacturing PMI","index",80),
    ]
    for sid,key,label,unit,limit in series_specs:
        out[key]=_fred_series(sid,label,unit,force=force,limit=limit)
        if not out[key]["success"]: out["warnings"].append(f"{label} is currently unavailable.")
    sahm_points=out["sahm_series"]["points"]
    latest_sahm=out["sahm_series"]["latest"].get("value")
    out["us_sahm"]={"unemployment":out["unemployment"]["points"],"indicator":sahm_points,"latest_indicator_pp":latest_sahm,"latest_date":out["sahm_series"]["latest"].get("date"),"threshold_pp":0.50,"status":"RECESSION SIGNAL" if latest_sahm is not None and latest_sahm>=0.5 else "NO SIGNAL","source":"Claudia Sahm / FRED","url":"https://fred.stlouisfed.org/series/SAHMCURRENT"}

    # Treasury spread, recession state, and market layer.
    try:
        d2=_fred("DGS2",force=force); d10=_fred("DGS10",force=force); merged=pd.merge(d2,d10,on="observation_date",how="inner"); merged["spread"]=merged["DGS10"]-merged["DGS2"]
        curve=[{"date":d.strftime("%Y-%m-%d"),"value":float(v)} for d,v in zip(merged["observation_date"].tail(260),merged["spread"].tail(260))]
        out["us_curve"]={"spread_10y_2y":curve[-1]["value"] if curve else None,"history":curve,"status":"INVERTED" if curve and curve[-1]["value"]<0 else "POSITIVE SLOPE","source":"U.S. Treasury rates via FRED","url":"https://fred.stlouisfed.org/series/T10Y2Y"}
    except Exception as exc:
        out["us_curve"]={"spread_10y_2y":None,"history":[],"status":"Unavailable","source":"U.S. Treasury rates via FRED","error":str(exc),"url":"https://fred.stlouisfed.org/series/T10Y2Y"}
        out["warnings"].append("U.S. Treasury curve unavailable.")
    out["recession_regime"]=_fred_series("USREC","NBER U.S. Recession Regime","0/1",force=force,limit=120)
    out["vietnam_unemployment"]=_latest_unemployment_vietnam()

    markets=_market_bundle(force=force)
    out.update(markets)
    # Convenience groups used by the UI.
    out["global_markets"]={k:markets[k] for k in ["GC=F","EURUSD=X","USDJPY=X","USDCNY=X","USDVND=X"] if k in markets}
    out["vietnam_markets"]={k:markets[k] for k in ["^VNINDEX","^VN30","^HNX","USDVND=X"] if k in markets}
    out["summary"]=_scenario_summary(out)
    out["data_status"]={"market":"near-real-time where provider supports intraday data","macro":"latest published observation; release frequency varies by series"}
    return out
