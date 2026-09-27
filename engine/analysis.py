from datetime import date
from . import db
from .stock import ticker_for


def _period_key(row):
    return row.get("period_end") or f"year:{row.get('year')}"


SOURCE_PRIORITY = {
    "reconciled_income_statement": 100,
    "reconciled_balance_sheet": 100,
    "reconciled_profit_attribution": 100,
    "statement_parent_profit": 95,
    "statement_label": 85,
    "statement_cashflow_ytd": 84,
    "statement_ytd": 80,
    "statement_total_profit": 70,
    "derived": 60,
    "derived_ytd": 55,
    "reported_ratio": 40,
}

def _pick_priority(row):
    scope=row.get("scope")
    scope_score=200 if scope=="consolidated" else 100 if scope=="unknown" else 0
    source_score=SOURCE_PRIORITY.get(row.get("source_type"), 10)
    quality=float(row.get("document_quality") or 0)
    confidence=float(row.get("confidence") or 0)
    return (scope_score, source_score, quality, confidence)


def _dedupe_period(rows):
    """Choose the best evidence per period, prioritising consolidated and reconciled sources."""
    grouped={}
    for row in rows:
        key=_period_key(row)
        old=grouped.get(key)
        if old is None or _pick_priority(row)>_pick_priority(old):
            grouped[key]=row
    return sorted([r for r in grouped.values() if r.get("scope") != "separate"], key=lambda r:(r.get("period_end") or "",r.get("year") or 0))


def _resolve_company_key(company):
    """Resolve ticker, legal name, or library folder name to the stored company key."""
    raw=str(company or "").strip()
    docs=db.companies()
    if any(str(r.get("company") or "").upper()==raw.upper() for r in docs):
        return raw.upper()
    target=ticker_for(raw)
    for r in docs:
        stored=str(r.get("company") or "").strip()
        if stored and ticker_for(stored)==target:
            return stored.upper()
    return raw.upper()


def _raw_series(company, metric):
    company=_resolve_company_key(company)
    rows=_dedupe_period(db.observations(company,[metric]))
    trusted=[]
    high_trust_reconciled={
        "reconciled_income_statement",
        "reconciled_balance_sheet",
        "reconciled_profit_attribution",
        "statement_parent_profit",
    }
    for r in rows:
        quality=float(r.get("document_quality") or 0)
        confidence=float(r.get("confidence") or 0)
        status=(r.get("document_status") or "review").lower()
        source_type=r.get("source_type") or "statement"
        if r.get("scope") != "consolidated":
            continue
        if status == "failed":
            continue
        # A document can legitimately score below the global quality threshold
        # because one unrelated row was missed.  Do not discard a specific metric
        # when that exact observation was independently reconciled and has strong
        # confidence. This closes the gap where the scanner visibly extracted a
        # report but ROA/ROE/EBITDA remained unavailable.
        metric_trusted=(
            quality >= 70 and confidence >= 0.70
        ) or (
            source_type in high_trust_reconciled and confidence >= 0.86 and quality >= 55
        )
        if not metric_trusted:
            continue
        trusted.append({"year":r["year"],"period_end":r.get("period_end"),"value":r["value"],"comparison_value":r.get("comparison_value"),"confidence":confidence,"scope":r.get("scope"),"source_type":source_type,"quality":quality,"source_path":r.get("source_path"),"unit":r.get("unit")})
    return trusted

def _map_period(rows): return {_period_key(r):r for r in rows}


def _quarter(month): return (month-1)//3+1 if month else None


def _period_date(value):
    try: return date.fromisoformat(value) if value else None
    except Exception: return None


def _looks_like_quarter_source(path):
    name=str(path or "").replace("\\","/").rsplit("/",1)[-1].lower()
    compact=name.replace(" ","")
    # Explicit quarter markers win over generic "nam/year" tokens.
    if "quy" in compact or "quarter" in compact or any(f"q{q}" in compact for q in range(1,5)):
        return True
    # A period ending 30 Jun / 30 Sep is inherently interim unless the filename
    # clearly identifies an annual/financial-year report.
    if any(token in compact for token in ("annual","fy","yearly","nam_20","nam20","nam-20","year_20")):
        return False
    return False

def _looks_like_annual_source(path):
    name=str(path or "").replace("\\","/").rsplit("/",1)[-1].lower().replace(" ","")
    if "quy" in name or "quarter" in name or any(f"q{q}" in name for q in range(1,5)):
        return False
    return any(token in name for token in ("annual","fy","yearly","nam_20","nam20","nam-20","kiem_toan_nam","year_20"))

def _quarter_depreciation(company):
    dep=_raw_series(company,"depreciation")
    result=[]
    for row in dep:
        d=_period_date(row.get("period_end")); current=row["value"]
        if not d or _looks_like_annual_source(row.get("source_path")):
            continue
        q=_quarter(d.month)
        source=row.get("source_type") or ""
        # Explicit standalone-quarter cash-flow layouts can be used directly.
        if source == "statement_cashflow_quarter":
            result.append({**row,"value":current,"source_type":"quarter_depreciation_reported"})
            continue
        quarter_value=None
        if q==1:
            quarter_value=current
        elif q in {2,3,4}:
            prior_month={2:3,3:6,4:9}[q]
            prior=next((x for x in reversed(dep)
                        if x.get("year")==d.year
                        and (_period_date(x.get("period_end")) or date.min).month==prior_month
                        and not _looks_like_annual_source(x.get("source_path"))),None)
            if prior is not None:
                quarter_value=current-prior["value"]
            elif _looks_like_quarter_source(row.get("source_path")) or d.month==6:
                # Q2 reports can be the first available report in the fiscal year.
                # In that case the reported depreciation may already be standalone
                # (PNJ, and CMC's Apr-Jun fiscal quarter are examples). Never force a
                # subtraction from an annual year-end statement.
                quarter_value=current
        if quarter_value is not None:
            result.append({**row,"value":quarter_value,"source_type":"quarterized_depreciation"})
    return result


def _quarter_rows(rows):
    out=[]
    for r in rows:
        d=_period_date(r.get("period_end"))
        if not d or _looks_like_annual_source(r.get("source_path")):
            continue
        q=_quarter(d.month)
        if q not in {1,2,3,4}:
            continue
        out.append(r)
    return sorted(out,key=lambda x:(x.get("period_end") or "",x.get("year") or 0))


def _period_quarter_tuple(row):
    d=_period_date(row.get("period_end"))
    return (d.year, _quarter(d.month)) if d else None


def _quarters_are_consecutive(rows):
    tuples=[_period_quarter_tuple(r) for r in rows]
    if len(tuples)<2 or any(t is None for t in tuples):
        return False
    for (y1,q1),(y2,q2) in zip(tuples, tuples[1:]):
        expected=(y1+1,1) if q1==4 else (y1,q1+1)
        if (y2,q2)!=expected:
            return False
    return True


def _annual_ratio_series(company, metric):
    """Return annual ratio observations when annual financial statements exist."""
    revenue=_raw_series(company,"revenue")
    parent=_raw_series(company,"net_income_parent") or _raw_series(company,"net_income")
    op=_raw_series(company,"operating_profit")
    dep=_raw_series(company,"depreciation")
    assets=_raw_series(company,"assets")
    equity=_raw_series(company,"equity")
    annual_revenue=[r for r in revenue if (_period_date(r.get("period_end")) or date.min).month in {12,3,6,9} and str(r.get("year"))]
    # Prefer rows that look annual by having a year-end period and no quarter label.
    def looks_annual(r):
        d=_period_date(r.get("period_end"))
        if not d or d.day not in {30,31}:
            return False
        path=str(r.get("source_path") or "").lower()
        name=path.replace("\\","/").rsplit("/",1)[-1]
        annual_hint=any(token in name for token in ("nam", "annual", "year", "fy", "kiem_toan"))
        # December year-end is unambiguous for normal calendar-year filers.
        # For Vietnamese fiscal years ending 31 March (e.g. CMC), require an
        # annual-report hint in the source filename before treating 31 March
        # as an annual observation. This prevents Q1 from being mislabeled annual.
        if d.month==12:
            return annual_hint or True
        if d.month==3:
            return annual_hint
        return False
    annual_revenue=[r for r in revenue if looks_annual(r)]
    annual_parent=[r for r in parent if looks_annual(r)]
    annual_op=[r for r in op if looks_annual(r)]
    annual_dep=[r for r in dep if looks_annual(r)]
    annual_assets=[r for r in assets if looks_annual(r)]
    annual_equity=[r for r in equity if looks_annual(r)]
    by_rev={_period_key(r):r for r in annual_revenue}
    out=[]
    for r in sorted(annual_revenue,key=lambda x:x.get("period_end") or ""):
        p=_period_key(r); ni=next((x for x in annual_parent if _period_key(x)==p),None)
        if metric=="net_margin_annual" and ni and r.get("value"):
            out.append({"value":float(ni["value"])/float(r["value"])*100,"period_end":r.get("period_end"),"basis":"Annual"})
        elif metric=="ebitda_margin_annual":
            opx=next((x for x in annual_op if _period_key(x)==p),None); dx=next((x for x in annual_dep if _period_key(x)==p),None)
            if opx and dx and r.get("value"):
                out.append({"value":(float(opx["value"])+abs(float(dx["value"])))/float(r["value"])*100,"period_end":r.get("period_end"),"basis":"Annual"})
        elif metric in {"roa_annual","roe_annual"} and ni:
            series_assets=annual_assets if metric=="roa_annual" else annual_equity
            current=next((x for x in series_assets if _period_key(x)==p),None)
            if current and current.get("value"):
                prevs=[x for x in series_assets if (x.get("period_end") or "") < (current.get("period_end") or "")]
                prev=prevs[-1] if prevs else None
                denom=(float(current["value"])+float(prev["value"]))/2 if prev else float(current["value"])
                if denom:
                    out.append({"value":float(ni["value"])/denom*100,"period_end":r.get("period_end"),"basis":"Annual / average balance"})
    return out


def _ttm_growth(company, metric="revenue"):
    rows=_quarter_rows(_raw_series(company,metric))
    if len(rows)<8:
        return None
    rows=sorted(rows,key=lambda x:x.get("period_end") or "")
    current4=rows[-4:]; prior4=rows[-8:-4]
    if not _quarters_are_consecutive(current4) or not _quarters_are_consecutive(prior4):
        return None
    if _period_quarter_tuple(prior4[-1]) and _period_quarter_tuple(current4[0]):
        py,pq=_period_quarter_tuple(prior4[-1]); cy,cq=_period_quarter_tuple(current4[0])
        if not (cy==py+1 and cq==pq):
            return None
    a=sum(float(x["value"]) for x in current4); b=sum(float(x["value"]) for x in prior4)
    if b==0:
        return None
    return {"value":(a/b-1)*100,"period_end":current4[-1].get("period_end"),"basis":"TTM YoY"}

def _ttm_ratio_series(company, metric):
    """TTM/market-comparison ratios when four quarter observations exist.

    This is intentionally separate from the dashboard's latest-period ratios.
    It prevents mixing a terminal's TTM convention with the latest-quarter view.
    """
    revenue=_quarter_rows(_raw_series(company,"revenue"))
    parent=_quarter_rows(_raw_series(company,"net_income_parent"))
    if not parent:
        parent=_quarter_rows(_raw_series(company,"net_income"))
    op=_quarter_rows(_raw_series(company,"operating_profit"))
    dep=_quarter_depreciation(company)
    dep=_quarter_rows(dep)
    assets=_quarter_rows(_raw_series(company,"assets"))
    equity=_quarter_rows(_raw_series(company,"equity"))
    if not revenue or len(revenue)<4:
        return None
    revenue=sorted(revenue,key=lambda x:x.get("period_end") or "")
    current=revenue[-1]
    rev4=revenue[-4:]
    if not _quarters_are_consecutive(rev4):
        return None
    rev_sum=sum(float(x["value"]) for x in rev4)
    if rev_sum<=0:
        return None
    keyset={_period_key(x) for x in rev4}
    p4=[x for x in parent if _period_key(x) in keyset]
    if len(p4)<4:
        return None
    ni_sum=sum(float(x["value"]) for x in p4)
    if metric=="net_margin_ttm":
        return {"value":ni_sum/rev_sum*100,"period_end":current.get("period_end"),"basis":"TTM"}
    if metric=="roa_ttm" and len(assets)>=1:
        by={_period_key(x):x for x in assets}
        end=by.get(_period_key(current)); start=next((x for x in reversed(assets) if (x.get("period_end") or "") < (current.get("period_end") or "")),None)
        if end and end.get("value") and start.get("value"):
            return {"value":ni_sum/((float(start["value"])+float(end["value"]))/2)*100,"period_end":current.get("period_end"),"basis":"TTM / average balance"}
    if metric=="roe_ttm" and len(equity)>=1:
        by={_period_key(x):x for x in equity}
        end=by.get(_period_key(current)); start=next((x for x in reversed(equity) if (x.get("period_end") or "") < (current.get("period_end") or "")),None)
        if end and end.get("value") and start.get("value"):
            return {"value":ni_sum/((float(start["value"])+float(end["value"]))/2)*100,"period_end":current.get("period_end"),"basis":"TTM / average balance"}
    if metric=="ebitda_margin_ttm":
        op4=[x for x in op if _period_key(x) in keyset]
        dep4=[x for x in dep if _period_key(x) in keyset]
        if len(op4)==4 and len(dep4)==4:
            ebitda=sum(float(x["value"]) for x in op4)+sum(abs(float(x["value"])) for x in dep4)
            return {"value":ebitda/rev_sum*100,"period_end":current.get("period_end"),"basis":"TTM"}
    return None

def _derived_series(company, metric):
    revenue=_raw_series(company,"revenue")
    revenue_ytd=_raw_series(company,"revenue_ytd")
    net_income_parent=_raw_series(company,"net_income_parent")
    net_income=_raw_series(company,"net_income")
    net_income = _dedupe_period(net_income_parent + net_income) if net_income_parent else net_income
    op=_raw_series(company,"operating_profit")
    dep=_quarter_depreciation(company)
    debt=_raw_series(company,"debt")
    if not debt:
        short_debt=_raw_series(company,"short_term_debt")
        long_debt=_raw_series(company,"long_term_debt")
        debt=[]
        for r in short_debt+long_debt:
            key=_period_key(r)
            if any(x.get("period_end")==r.get("period_end") and x.get("year")==r.get("year") for x in debt):
                continue
            sd=next((x for x in short_debt if _period_key(x)==key),None)
            ld=next((x for x in long_debt if _period_key(x)==key),None)
            if sd or ld:
                debt.append({**(sd or ld),"value":float(sd["value"] if sd else 0)+float(ld["value"] if ld else 0),"source_type":"derived"})
    assets=_raw_series(company,"assets")
    equity=_raw_series(company,"equity")
    total_sources=_raw_series(company,"total_sources")
    total_liabilities=_raw_series(company,"total_liabilities")
    cash=_raw_series(company,"cash_flow")
    # Recover balance-sheet denominators when a direct row was missed but the formal
    # total-sources row is present.  This is safer than leaving ROA/ROE unavailable
    # because the 280/400 row was lost by OCR.
    if not assets and total_sources:
        assets=total_sources
    if not equity and total_sources and total_liabilities:
        eq=[]
        for ts in total_sources:
            key=_period_key(ts); liab=next((x for x in total_liabilities if _period_key(x)==key),None)
            if liab and ts.get("value") is not None and liab.get("value") is not None:
                eq.append({**ts,"value":ts["value"]-liab["value"],"source_type":"reconciled_balance_sheet","confidence":min(float(ts.get("confidence",0.5)),float(liab.get("confidence",0.5)))})
        if eq:
            equity=eq
    cash_ytd=cash  # cash-flow statements are commonly reported YTD
    by_rev=_map_period(revenue); by_rev_ytd=_map_period(revenue_ytd); by_net=_map_period(net_income); by_op=_map_period(op); by_dep=_map_period(dep); by_debt=_map_period(debt); by_assets=_map_period(assets); by_equity=_map_period(equity); by_cash=_map_period(cash); by_cash_ytd=_map_period(cash_ytd)
    periods=sorted(set(by_rev)|set(by_net)|set(by_op)|set(by_dep)|set(by_debt)|set(by_assets)|set(by_equity)|set(by_cash))
    out=[]
    for p in periods:
        rev=by_rev.get(p); rev_ytd=by_rev_ytd.get(p); ni=by_net.get(p); oper=by_op.get(p); d=by_dep.get(p); debt_row=by_debt.get(p); asset_row=by_assets.get(p); equity_row=by_equity.get(p); cash_row=by_cash.get(p)
        if metric=="net_margin" and rev and ni and rev["value"]:
            out.append({"year":rev["year"],"period_end":rev["period_end"],"value":ni["value"]/rev["value"]*100,"comparison_value":None,"confidence":min(rev["confidence"],ni["confidence"]),"scope":"consolidated","quality":min(rev.get("quality",0),ni.get("quality",0))})
        elif metric=="ebitda" and rev and oper and d:
            out.append({"year":rev["year"],"period_end":rev["period_end"],"value":oper["value"]+abs(d["value"]),"comparison_value":None,"confidence":min(oper["confidence"],d["confidence"]),"scope":"consolidated","quality":min(rev.get("quality",0),oper.get("quality",0),d.get("quality",0))})
        elif metric=="ebitda_margin" and rev and oper and d and rev["value"]:
            ebitda=oper["value"]+abs(d["value"])
            out.append({"year":rev["year"],"period_end":rev["period_end"],"value":ebitda/rev["value"]*100,"comparison_value":None,"confidence":min(rev["confidence"],oper["confidence"],d["confidence"]),"scope":"consolidated","quality":min(rev.get("quality",0),oper.get("quality",0),d.get("quality",0))})
        elif metric=="cash_flow_margin":
            # CFO and income-statement quarter should share the same period_end.
            # Never combine a YTD cash-flow number with a standalone-quarter revenue.
            if cash_row and rev and cash_row.get("period_end")==rev.get("period_end") and rev["value"]:
                out.append({"year":rev["year"],"period_end":rev["period_end"],"value":cash_row["value"]/rev["value"]*100,"comparison_value":None,"confidence":min(cash_row["confidence"],rev["confidence"]),"scope":"consolidated","quality":min(cash_row.get("quality",0),rev.get("quality",0))})
        elif metric in {"roa","roe"}:
            denominator_row=asset_row if metric=="roa" else equity_row
            if ni and denominator_row and denominator_row["value"]:
                # For interim reports this is the latest-period return on average
                # capital/asset base. The numerator is the parent-attributable profit
                # where the consolidated statement provides it. This matches the
                # company's own quarterly economics; market terminals may instead
                # publish TTM/annual ROAA/ROAE, which is a different basis.
                prev=denominator_row.get("comparison_value")
                denom=((denominator_row["value"]+prev)/2) if prev not in (None,0) else denominator_row["value"]
                if denom:
                    out.append({"year":ni["year"],"period_end":ni["period_end"],"value":ni["value"]/denom*100,"comparison_value":None,"confidence":min(ni["confidence"],denominator_row["confidence"]),"scope":"consolidated","quality":min(ni.get("quality",0),denominator_row.get("quality",0)),"basis":"latest_period_parent_profit_over_average_balance"})
        elif metric=="debt_to_ebitda" and debt_row and oper and d:
            ebitda=oper["value"]+abs(d["value"])
            if ebitda>0:
                pd=_period_date(rev["period_end"] if rev else debt_row["period_end"])
                annualized=ebitda*4 if pd and pd.month in {3,6,9} else ebitda
                out.append({"year":debt_row["year"],"period_end":debt_row["period_end"],"value":debt_row["value"]/annualized,"comparison_value":None,"confidence":min(debt_row["confidence"],oper["confidence"],d["confidence"]),"scope":"consolidated","quality":min(debt_row.get("quality",0),oper.get("quality",0),d.get("quality",0), (rev or debt_row).get("quality",0))})
    return out

def series(company, metric):
    company=_resolve_company_key(company)
    if metric in {"net_margin","ebitda","ebitda_margin","debt_to_ebitda","cash_flow_margin","roa","roe"}:
        return _derived_series(company,metric)
    return _raw_series(company,metric)


def latest(company, metric):
    values=series(company,metric)
    if not values: return None
    return max(values, key=lambda r: (_period_date(r.get("period_end")) or date.min, float(r.get("quality") or 0), float(r.get("confidence") or 0)))


def yoy_growth(company, metric):
    company=_resolve_company_key(company)
    """Return same-period YoY growth only.

    Priority order:
      1) an actual verified prior-year observation with the same period-end month/day;
      2) an explicitly trusted same-period comparator embedded in the current statement;
      3) otherwise None. Never use the previous sequential quarter.
    """
    values=series(company,metric)
    if not values: return None
    values=sorted(values,key=lambda r: (r.get("period_end") or "", r.get("year") or 0))
    current=values[-1]
    current_value=current.get("value")
    if current_value is None: return None
    current_date=_period_date(current.get("period_end"))
    if current_date:
        target_year=current_date.year-1
        same_period=[]
        for x in values:
            d=_period_date(x.get("period_end"))
            if d and d.year==target_year and d.month==current_date.month:
                same_period.append(x)
        if same_period:
            target=same_period[-1]
            if target.get("value") not in (None,0):
                return (current_value/target["value"]-1)*100
    comparison=current.get("comparison_value")
    # Revenue reconciliation can produce a clean current-period net revenue while
    # dropping the comparator. Recover the same-period prior-year comparator from
    # gross revenue minus revenue deductions on the same consolidated source.
    if comparison is None and metric=="revenue":
        source_path=current.get("source_path")
        period=current.get("period_end")
        gr_rows=_raw_series(company,"gross_revenue")
        rd_rows=_raw_series(company,"revenue_reductions")
        gr=next((x for x in gr_rows if x.get("period_end")==period and (source_path is None or x.get("source_path")==source_path)),None)
        rd=next((x for x in rd_rows if x.get("period_end")==period and (source_path is None or x.get("source_path")==source_path)),None)
        if gr and rd and gr.get("comparison_value") is not None and rd.get("comparison_value") is not None:
            try:
                comparison=float(gr["comparison_value"])-float(rd["comparison_value"])
            except Exception:
                comparison=None
    trusted_source=current.get("source_type") in {"statement_with_adjusted_comparator","reported_comparable_ytd","reconciled_income_statement","statement_label","statement_parent_profit"}
    if comparison is not None and trusted_source and comparison>0:
        try:
            comparison=float(comparison)
            # Statement reconciliation tables are sometimes labelled "million VND"
            # while the main statement is stored as VND. Normalize by a power of 1,000
            # before applying the ratio guard.
            candidates=[comparison/(1000**k) for k in range(0,5)] + [comparison*(1000**k) for k in range(1,3)]
            valid=[c for c in candidates if c>0 and current_value and 0.35 <= abs(c/current_value) <= 3.5]
            if valid:
                best=min(valid,key=lambda c:abs(c-current_value*0.85))
                ratio=abs(best/current_value) if current_value else 0
                # A same-period prior-year comparator should normally be on the same
                # order of magnitude. If the extracted value is actually an H1/YTD
                # column (a common OCR/table-order failure), refuse it rather than
                # displaying a false growth rate.
                if 0.5 <= ratio <= 1.5:
                    return (current_value/best-1)*100
        except Exception:
            pass
    return None

def growth(company,metric): return yoy_growth(company,metric)

def _value(company,metric):
    item=latest(company,metric); return item["value"] if item else None


def transparency_alerts(company):
    company=company.upper().strip(); docs=db.company_documents(company)
    if not docs:return []
    consolidated=[d for d in docs if d.get("scope")=="consolidated"]
    latest_doc=(consolidated or [d for d in docs if d.get("scope")!="separate"] or docs)[-1]
    period=latest_doc.get("period_end")
    required={"revenue":"Revenue","net_income":"Net income","gross_profit":"Gross profit","operating_profit":"Operating profit","depreciation":"Depreciation","assets":"Total assets","cash_flow":"Operating cash flow"}
    missing=[]
    for metric,label in required.items():
        if not [x for x in _raw_series(company,metric) if x.get("period_end")==period]: missing.append(label)
    warnings=[]
    try:
        import json
        warnings=json.loads(latest_doc.get("warnings") or "[]")
    except Exception: pass
    if latest_doc.get("scope")!="consolidated": missing.insert(0,"Consolidated financial statement")
    return missing + warnings


def peer_rows(company):
    result=[]
    for peer in db.peers(company):
        c=peer["company"]
        result.append({"company":c,"revenue_growth":growth(c,"revenue"),"net_margin":_value(c,"net_margin"),"roe":_value(c,"roe"),"roa":_value(c,"roa"),"debt_to_ebitda":_value(c,"debt_to_ebitda"),"reports":peer["reports"]})
    return result


def health(company):
    revenue_growth=growth(company,"revenue"); margin=_value(company,"net_margin"); roe=_value(company,"roe"); leverage=_value(company,"debt_to_ebitda")
    components={}; signals=[]
    if revenue_growth is not None: components["Growth"]=max(0,min(100,50+revenue_growth*3)); signals.append("Revenue is growing" if revenue_growth>=0 else "Revenue is declining")
    if margin is not None: components["Profitability"]=max(0,min(100,50+margin*2))
    if roe is not None: components["Capital efficiency"]=max(0,min(100,50+roe*1.5))
    if leverage is not None: components["Leverage"]=max(0,min(100,100-leverage*15)); signals.append("Leverage is elevated" if leverage>3 else "Leverage is moderate")
    score=round(sum(components.values())/len(components)) if components else None
    if score is None: label,direction="INSUFFICIENT DATA","INSUFFICIENT"
    elif score>=75: label,direction="STRONG","UP"
    elif score>=60: label,direction="POSITIVE","UP"
    elif score>=45: label,direction="MIXED","FLAT"
    elif score>=30: label,direction="WEAK","DOWN"
    else: label,direction="VERY WEAK","DOWN"
    return {"score":score,"label":label,"direction":direction,"signals":signals,"components":components}


OVERVIEW_REPORT_METRICS = [
    # Income statement lines extracted from the verified report.
    "gross_revenue", "revenue_reductions", "revenue", "cost_of_goods_sold",
    "gross_profit", "operating_profit", "net_income", "net_income_total",
    "net_income_parent", "nci_profit", "selling_expense", "admin_expense",
    "sga", "depreciation",
    # Balance sheet and capital structure lines extracted from the report.
    "assets", "total_liabilities", "equity", "total_sources",
    "current_assets", "current_liabilities", "receivables", "ppe",
    "short_term_debt", "long_term_debt", "debt",
    # Cash flow statement line.
    "cash_flow",
]

OVERVIEW_DERIVED_METRICS = [
    "revenue_growth", "ebitda", "ebitda_margin", "net_margin",
    "cash_flow_margin", "debt_to_ebitda", "roe", "roa",
]


def overview(company):
    company=company.upper().strip(); documents=db.company_documents(company)
    if not documents:return {"error":"Company not found in the report library."}
    consolidated=[d for d in documents if d.get("scope")=="consolidated"]
    latest_doc=(consolidated[-1] if consolidated else documents[-1])
    # The Full Research workspace must receive every line item that the scanner
    # already verified. Previously only the small dashboard KPI set crossed the
    # API boundary, which made valid scanned values appear unavailable.
    metric_names=list(dict.fromkeys(OVERVIEW_REPORT_METRICS+OVERVIEW_DERIVED_METRICS))
    metrics={name:(growth(company,"revenue") if name=="revenue_growth" else latest(company,name)) for name in metric_names}
    alerts=transparency_alerts(company)
    tracked=["revenue","revenue_growth","net_margin","ebitda_margin","roe","roa","debt_to_ebitda"]
    metric_values={name:(growth(company,"revenue") if name=="revenue_growth" else latest(company,name)) for name in tracked}
    available=sum(1 for name in tracked if metric_values[name] is not None)
    unavailable_reasons={}
    for name,value in metric_values.items():
        if value is not None:
            continue
        if name=="revenue_growth":
            unavailable_reasons[name]="No verified same-period prior-year comparator."
        elif name in {"roa","roe"}:
            unavailable_reasons[name]="No verified consolidated profit plus average balance-sheet denominator."
        elif name=="ebitda_margin":
            unavailable_reasons[name]="No verified operating profit plus quarter-compatible depreciation."
        elif name=="debt_to_ebitda":
            unavailable_reasons[name]="No verified debt plus EBITDA on the same period basis."
        else:
            unavailable_reasons[name]="Required consolidated inputs were not verified."
    market_ratios={
        "net_margin_ttm":_ttm_ratio_series(company,"net_margin_ttm"),
        "ebitda_margin_ttm":_ttm_ratio_series(company,"ebitda_margin_ttm"),
        "roa_ttm":_ttm_ratio_series(company,"roa_ttm"),
        "roe_ttm":_ttm_ratio_series(company,"roe_ttm"),
        "net_margin_annual":(_annual_ratio_series(company,"net_margin_annual") or [None])[-1],
        "ebitda_margin_annual":(_annual_ratio_series(company,"ebitda_margin_annual") or [None])[-1],
        "roa_annual":(_annual_ratio_series(company,"roa_annual") or [None])[-1],
        "roe_annual":(_annual_ratio_series(company,"roe_annual") or [None])[-1],
        "revenue_growth_ttm":_ttm_growth(company,"revenue"),
    }
    market_preferred={
        "net_margin":market_ratios["net_margin_ttm"] or market_ratios["net_margin_annual"],
        "ebitda_margin":market_ratios["ebitda_margin_ttm"] or market_ratios["ebitda_margin_annual"],
        "roa":market_ratios["roa_ttm"] or market_ratios["roa_annual"],
        "roe":market_ratios["roe_ttm"] or market_ratios["roe_annual"],
        "revenue_growth":market_ratios["revenue_growth_ttm"],
    }
    # Keep the existing UI but return a data-quality score that cannot claim 100/100
    # when most of the displayed KPIs are actually unavailable.
    doc_quality=float(latest_doc.get("quality_score") or 0)
    coverage_score=round(available/7*100)
    quality_score=round(min(doc_quality, coverage_score if consolidated else 0))
    scan_status={name:("available" if metrics.get(name) is not None else "unavailable") for name in OVERVIEW_REPORT_METRICS}
    scan_available=sum(1 for status in scan_status.values() if status=="available")
    return {"company":company,"industry":latest_doc["industry"],"reports":len(documents),"years":sorted({d["year"] for d in documents if d.get("year")}),"latest_report":{"period_end":latest_doc.get("period_end"),"scope":latest_doc.get("scope"),"status":latest_doc.get("status"),"quality_score":quality_score,"warnings":alerts,"file":PathLikeName(latest_doc.get("path"))},"health":health(company),"metrics":metrics,"scan_coverage":{"available_metrics":scan_available,"total_metrics":len(OVERVIEW_REPORT_METRICS),"metric_status":scan_status},"market_ratios":market_ratios,"ratio_views":{"latest":{k:(v["value"] if isinstance(v,dict) and "value" in v else v) for k,v in {"net_margin":_value(company,"net_margin"),"ebitda_margin":_value(company,"ebitda_margin"),"roa":_value(company,"roa"),"roe":_value(company,"roe"),"revenue_growth":growth(company,"revenue")}.items()},"market":{k:(v.get("value") if isinstance(v,dict) else None) for k,v in market_preferred.items()},"market_basis":{k:(v.get("basis") if isinstance(v,dict) else None) for k,v in market_preferred.items()}},"history":{m:series(company,m) for m in ["revenue","ebitda","net_income"]},"peers":peer_rows(company),"coverage":{"available_metrics":available,"total_metrics":7,"metric_status":{k:("available" if v is not None else "unavailable") for k,v in metric_values.items()},"unavailable_reasons":unavailable_reasons,"transparency_alerts":alerts}}


def PathLikeName(path): return str(path).replace("\\","/").split("/")[-1] if path else None

def compare(companies):
    clean=[]
    for company in companies:
        raw=company.upper().strip()
        if not raw: continue
        resolved=_resolve_company_key(raw)
        item=(raw,resolved)
        if item not in clean: clean.append(item)
    data=[]
    for raw,resolved in clean:
        row=overview(resolved)
        if "error" not in row:
            row["company"]=raw
            row["library_company"]=resolved
        data.append(row)
    valid=[x for x in data if "error" not in x]
    if len(valid)<2:return {"error":"At least two companies with report data are required.","companies":data}
    return {"companies":valid}

def extract_document_text(company,limit=12000):
    documents=db.company_documents(company); pieces=[]
    for document in documents[-3:]: pieces.append(f"PERIOD {document.get('period_end')} SCOPE {document.get('scope')} SOURCE {document['path']}\n{document['text'][:limit]}")
    return "\n\n".join(pieces)

def rebuild_derived_metrics():
    """Kept as a compatibility hook; derived metrics are now calculated from source data on demand."""
    return {"companies":len(db.companies())}
