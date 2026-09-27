from statistics import NormalDist
from datetime import date
from . import db
from .analysis import latest, growth, _raw_series, _period_date


def _fiscal_year_end_month(company):
    """Infer the company's fiscal-year end month from annual statements when available."""
    try:
        docs = db.company_documents(company)
    except Exception:
        return 12
    months=[]
    for d in docs:
        p=d.get("period_end")
        if not p: continue
        month=int(str(p)[5:7])
        path=str(d.get("path") or "").lower()
        quarter_hint=("quy" in path) or ("quý" in path) or ("quarter" in path) or any(f"q{q}" in path for q in range(1,5))
        annual_hint=(not quarter_hint) and any(t in path for t in ("kiem_toan_nam","annual","yearly","fy","nam_20","nam20","nam-20"))
        if annual_hint:
            months.append(month)
    return max(set(months), key=months.count) if months else 12


def _quarter_revenue_ytd(company, current_row):
    """Rebuild YTD revenue from verified standalone quarter revenue when possible.

    This is used only by the risk layer. It prevents malformed YTD OCR values from
    entering Beneish SGI/GMI while leaving the working overview pipeline untouched.
    """
    d=_period_date(current_row.get("period_end"))
    if not d: return None
    revenue_rows=_raw_series(company,"revenue")
    if not revenue_rows: return None
    fy_end=_fiscal_year_end_month(company)
    fy_start=(fy_end % 12)+1
    # Fiscal year label anchored to its ending year.
    if d.month < fy_start:
        fy_year=d.year
    else:
        fy_year=d.year+1 if fy_start!=1 else d.year
    def fiscal_index(dt):
        return ((dt.month-fy_start)%12)+1
    candidates=[]
    for r in revenue_rows:
        rd=_period_date(r.get("period_end"))
        if not rd or rd>d: continue
        if fiscal_index(rd)>fiscal_index(d): continue
        # Ensure it belongs to the same fiscal year.
        rfy=rd.year if rd.month < fy_start else (rd.year+1 if fy_start!=1 else rd.year)
        if rfy!=fy_year: continue
        candidates.append(r)
    if not candidates: return None
    candidates=sorted(candidates,key=lambda x:x.get("period_end") or "")
    current_value=sum(float(r["value"]) for r in candidates if r.get("value") is not None)
    # Rebuild prior-year same-period comparator from each quarter's comparator.
    comp_values=[]
    for r in candidates:
        cv=r.get("comparison_value")
        if cv is None: return None
        cv=float(cv)
        # Older statement-comparison extraction can be one thousand times larger
        # when the report table is labelled million VND. Normalize only the
        # comparator so the source-period value remains untouched.
        current=float(r.get("value") or 0)
        if current>0 and cv>0 and not (0.35 <= cv/current <= 3.5):
            choices=[cv/(1000**k) for k in range(1,5)] + [cv*(1000**k) for k in range(1,3)]
            valid=[x for x in choices if x>0 and 0.35 <= x/current <= 3.5]
            if valid:
                cv=min(valid,key=lambda x:abs((x/current)-0.9))
        comp_values.append(cv)
    comparison=sum(comp_values) if comp_values else None
    return {"value":current_value,"comparison_value":comparison,"source_type":"reconstructed_quarter_ytd","confidence":min(float(r.get("confidence") or .8) for r in candidates),"period_end":current_row.get("period_end"),"year":current_row.get("year"),"scope":"consolidated"}


def _normalize_reported_ytd(company, row, metric):
    if row is None: return None
    if metric != "revenue" or row.get("source_type") != "reported_comparable_ytd":
        return row
    # First prefer reconstruction from quarter revenue; it is immune to the
    # million-VND vs VND scaling error found in older extracted YTD rows.
    rebuilt=_quarter_revenue_ytd(company,row)
    if rebuilt is not None:
        return rebuilt
    return row


def _risk_series(company, metric):
    """Return risk inputs with correct period basis and robust YTD reconstruction."""
    company = company.upper().strip()
    if metric == "sga":
        selling=_raw_series(company,"selling_expense_ytd")
        admin=_raw_series(company,"admin_expense_ytd")
        if selling or admin:
            by_s={x.get("period_end"):x for x in selling}; by_a={x.get("period_end"):x for x in admin}
            out=[]
            for period in sorted(set(by_s)|set(by_a)):
                a=by_s.get(period); b=by_a.get(period)
                value=(a["value"] if a else 0)+(b["value"] if b else 0)
                comp_a=a.get("comparison_value") if a else None; comp_b=b.get("comparison_value") if b else None
                comparison=(comp_a if comp_a is not None else 0)+(comp_b if comp_b is not None else 0)
                out.append({"year":(a or b)["year"],"period_end":period,"value":value,"comparison_value":comparison if (comp_a is not None or comp_b is not None) else None,"confidence":min((a or b)["confidence"],0.9),"scope":"consolidated"})
            if out:return out
    if metric == "revenue":
        rows=_raw_series(company,"revenue_ytd")
        rows=[_normalize_reported_ytd(company,r,metric) for r in rows]
        # If there is no reliable YTD observation, derive it from verified quarters.
        out=[]
        for r in rows:
            if r.get("comparison_value") is not None and r.get("value") is not None:
                out.append(r)
        if out:
            return out
        # Fall back to the latest verified quarter; for a first-fiscal-quarter report
        # this is itself the YTD value.
        qrows=_raw_series(company,"revenue")
        return qrows
    if metric == "net_income":
        # Beneish interim analysis uses YTD income. Reconstruct it from verified
        # parent-profit quarter values so we do not mix standalone Q2 with YTD CFO.
        qrows=_raw_series(company,"net_income")
        if qrows:
            rebuilt=[]
            for cur in qrows:
                r=_quarter_revenue_ytd(company,cur)
                if r is None:
                    rebuilt.append(cur); continue
                # Use the same fiscal-year quarter set as revenue and sum parent profit.
                d=_period_date(cur.get("period_end")); fy_end=_fiscal_year_end_month(company); fy_start=(fy_end%12)+1
                def fi(dt): return ((dt.month-fy_start)%12)+1
                fy_year=d.year if d.month<fy_start else (d.year+1 if fy_start!=1 else d.year)
                vals=[]
                for x in qrows:
                    xd=_period_date(x.get("period_end"))
                    if not xd or xd>d or fi(xd)>fi(d): continue
                    xfy=xd.year if xd.month<fy_start else (xd.year+1 if fy_start!=1 else xd.year)
                    if xfy==fy_year: vals.append(x)
                if vals and all(x.get("comparison_value") is not None for x in vals):
                    rebuilt.append({**cur,"value":sum(float(x["value"]) for x in vals),"comparison_value":sum(float(x["comparison_value"]) for x in vals),"source_type":"reconstructed_quarter_ytd"})
                else: rebuilt.append(cur)
            return rebuilt
    if metric in {"gross_profit","depreciation"}:
        ytd_metric=metric+"_ytd" if metric=="gross_profit" else metric
        rows=_raw_series(company,ytd_metric)
        if rows:return rows
    if metric == "cash_flow":
        rows=_raw_series(company,"cash_flow")
        if rows:return rows
    return _raw_series(company,metric)


def _current_previous(company, metric):
    rows=_risk_series(company,metric)
    if not rows: return None,None,None
    rows=sorted(rows,key=lambda r:(r.get("period_end") or "",r.get("year") or 0))
    current=rows[-1]
    previous_value=current.get("comparison_value")
    if previous_value is not None:
        previous={"value":previous_value,"period_end":"prior-year-comparator","year":(current.get("year") or 0)-1}
        return current,previous,rows
    if len(rows)>=2:return current,rows[-2],rows
    return current,None,rows


def _value(row): return None if row is None else row.get("value")


def _balance_pair(company, metric, current_period):
    """For balance-sheet Beneish inputs, use the report comparator first, then the
    immediately preceding verified consolidated reporting date if necessary."""
    rows=_raw_series(company,metric)
    cur=next((r for r in rows if r.get("period_end")==current_period),None)
    if cur is None:return None,None
    if cur.get("comparison_value") is not None:
        return cur,{"value":cur.get("comparison_value"),"period_end":"report-comparator","year":(cur.get("year") or 0)-1}
    prior=[r for r in rows if r.get("period_end") and r.get("period_end")<current_period]
    if prior:
        return cur,sorted(prior,key=lambda x:x.get("period_end"))[-1]
    return cur,None


def beneish(company):
    names=["revenue","receivables","current_assets","ppe","depreciation","sga","current_liabilities","long_term_debt","assets","net_income","cash_flow","gross_profit"]
    # Flow values: current-period YTD / same-period comparator.
    pairs={}; missing=[]
    for name in names:
        if name in {"receivables","current_assets","ppe","current_liabilities","long_term_debt","assets"}:
            # Resolve the current period from the latest revenue row.
            rev_rows=_risk_series(company,"revenue")
            if not rev_rows:
                cur=prev=None
            else:
                period=sorted(rev_rows,key=lambda r:(r.get("period_end") or "",r.get("year") or 0))[-1].get("period_end")
                cur,prev=_balance_pair(company,name,period)
        else:
            cur,prev,_=_current_previous(company,name)
        pairs[name]=(cur,prev)
        if cur is None or prev is None or _value(cur) is None or _value(prev) is None: missing.append(name)
    if missing:
        return {"status":"Insufficient inputs for Beneish screening.","missing_inputs":missing,"periods":["latest", "prior-year comparator"],"note":"Unavailable: the consolidated report does not contain enough paired values for this screening."}
    try:
        r_c,r_p=_value(pairs["revenue"][0]),_value(pairs["revenue"][1])
        gross_c,gross_p=_value(pairs["gross_profit"][0]),_value(pairs["gross_profit"][1])
        rec_c,rec_p=_value(pairs["receivables"][0]),_value(pairs["receivables"][1])
        ca_c,ca_p=_value(pairs["current_assets"][0]),_value(pairs["current_assets"][1])
        ppe_c,ppe_p=_value(pairs["ppe"][0]),_value(pairs["ppe"][1])
        a_c,a_p=_value(pairs["assets"][0]),_value(pairs["assets"][1])
        dep_c,dep_p=abs(_value(pairs["depreciation"][0])),abs(_value(pairs["depreciation"][1]))
        sga_c,sga_p=abs(_value(pairs["sga"][0])),abs(_value(pairs["sga"][1]))
        cl_c,cl_p=_value(pairs["current_liabilities"][0]),_value(pairs["current_liabilities"][1])
        ltd_c,ltd_p=_value(pairs["long_term_debt"][0]),_value(pairs["long_term_debt"][1])
        ni_c,ni_p=_value(pairs["net_income"][0]),_value(pairs["net_income"][1])
        cfo_c,cfo_p=_value(pairs["cash_flow"][0]),_value(pairs["cash_flow"][1])
        if min(abs(r_c),abs(r_p),abs(gross_c),abs(gross_p),abs(a_c),abs(a_p))<=0:
            raise ValueError("Invalid zero/negative denominator in Beneish inputs")
        dsri=(rec_c/r_c)/(rec_p/r_p)
        gmi=(gross_p/r_p)/(gross_c/r_c)
        noncurrent_c=1-(ca_c+ppe_c)/a_c
        noncurrent_p=1-(ca_p+ppe_p)/a_p
        aqi=noncurrent_c/noncurrent_p if noncurrent_p else 1.0
        sgi=r_c/r_p
        depi=(dep_p/(dep_p+ppe_p))/(dep_c/(dep_c+ppe_c)) if dep_c+ppe_c and dep_p+ppe_p else 1.0
        sgai=(sga_c/r_c)/(sga_p/r_p)
        lvgi=((cl_c+ltd_c)/a_c)/((cl_p+ltd_p)/a_p)
        # The original Beneish definition scales total accruals by current-period
        # total assets.  Using average assets silently changes the published model.
        tata=(ni_c-cfo_c)/a_c
        score=(-4.84+0.92*dsri+0.528*gmi+0.404*aqi+0.892*sgi+0.115*depi-0.172*sgai+4.679*tata-0.327*lvgi)
        proxy=max(0.0,min(100.0,NormalDist().cdf(score)*100))
        current_period = pairs["revenue"][0].get("period_end")
        annual_basis = str(current_period or "").endswith("-12-31")
        return {
            "status":"ok",
            "score":round(score,3),
            # Retained for older API clients; new UI uses the explicit name below.
            "risk_proxy_pct":round(proxy,1),
            "relative_screen_signal_pct":round(proxy,1),
            "screening_flag":score>-1.78,
            "screening_label":"Review threshold crossed" if score>-1.78 else "Below review threshold",
            "model_scope":"Accounting-quality screen",
            "model_version":"Beneish M-score (8-variable)",
            "calibrated_probability":False,
            "period_basis":"annual" if annual_basis else "interim YTD adaptation",
            "adaptation_status":"published annual specification" if annual_basis else "experimental interim adaptation",
            "periods":[pairs["revenue"][1].get("period_end"),current_period],
            "components":{"DSRI":round(dsri,3),"GMI":round(gmi,3),"AQI":round(aqi,3),"SGI":round(sgi,3),"DEPI":round(depi,3),"SGAI":round(sgai,3),"LVGI":round(lvgi,3),"TATA":round(tata,4)},
            "note":(
                "Beneish M-score accounting-quality screen using consolidated evidence. "
                "The transformed relative screen signal is not a calibrated probability of fraud. "
                + ("The annual specification is used." if annual_basis else "Interim YTD flow figures and matched balance-sheet comparators are an experimental adaptation; confirm any flag against an annual audited report.")
            ),
        }
    except Exception as exc:
        return {"status":"Unable to calculate M-score.","error":str(exc)}


def assess(company):
    flags=[]
    leverage=latest(company,"debt_to_ebitda"); revenue_growth=growth(company,"revenue"); margin=latest(company,"net_margin")
    if leverage and leverage["value"]>4: flags.append("High leverage")
    elif leverage and leverage["value"]>3: flags.append("Elevated leverage")
    if revenue_growth is not None and revenue_growth<0: flags.append("Revenue declined in the latest same-period comparison")
    if margin and margin["value"]<0: flags.append("Negative net margin")
    consistency=[]
    for metric in ["revenue","net_income","debt","cash_flow"]:
        rows=_risk_series(company,metric)
        if not rows: continue
        current=rows[-1]; prior=current.get("comparison_value")
        if prior is not None and prior!=0:
            # Percentage change is not meaningful for cash flow when values cross
            # zero or when the comparator itself is negative. Keep the signal safe
            # by returning Unavailable for that metric instead of a misleading %.
            if metric=="cash_flow" and (current.get("value",0)<=0 or prior<=0):
                continue
            change=(current["value"]/prior-1)*100
            # Reject implausible changes caused by legacy unit/scaling errors.
            if abs(change) <= 300:
                consistency.append({"metric":metric,"periods":["prior-year comparator",current.get("period_end") or current.get("year")],"change_pct":round(change,2)})
    return {
        "company":company,
        "feature":"investment_research",
        "stage":"accounting_quality_screen",
        "flags":flags,
        "report_consistency":consistency,
        "beneish":beneish(company),
        "disclaimer":"Accounting-quality screening is an investigative aid, not a legal conclusion, audit opinion, fraud probability, valuation, or buy/sell signal. Corporate restructuring or accounting-policy changes can change ratios without implying misconduct.",
    }
