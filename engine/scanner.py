from config import REPORTS_DIR, PARSER_VERSION
from .report_reader import SUPPORTED,read_document,sha256
from .report_extractor import extract
from . import db
from .stock import ticker_for


def _ocr_was_used(text):
    return "--- OCR PAGE" in (text or "")


def scan():
    REPORTS_DIR.mkdir(parents=True,exist_ok=True)
    db.init_db(); stale=db.prune_missing_documents(REPORTS_DIR)
    document_count=0; observation_count=0; failed=[]; rescanned=[]; snapshot_restored=[]; snapshots_archived=[]
    for industry_dir in sorted(REPORTS_DIR.iterdir()):
        if not industry_dir.is_dir(): continue
        industry=industry_dir.name.strip()
        for company_dir in sorted(industry_dir.iterdir()):
            if not company_dir.is_dir(): continue
            company=company_dir.name.upper().strip()
            for path in sorted(company_dir.rglob("*")):
                if not path.is_file() or path.suffix.lower() not in SUPPORTED: continue
                try:
                    digest=sha256(path); existing=db.existing_document(path); obs_count=db.observation_count(path) if existing else 0
                    can_skip=(existing and existing.get("sha256")==digest and existing.get("parser_version")==PARSER_VERSION and obs_count>0 and existing.get("status")!="failed")
                    if can_skip:
                        document_count+=1; continue

                    rel_path=str(path.relative_to(REPORTS_DIR))
                    # A durable snapshot for the current file hash + parser version
                    # can be restored instantly when switching application versions.
                    # This avoids re-running OCR/extraction just because a version changed.
                    restored=db.restore_snapshot(path, digest, PARSER_VERSION)
                    if restored:
                        snapshot_restored.append({"file": rel_path, **restored})
                        document_count+=1
                        observation_count+=int(restored.get("observations") or 0)
                        continue

                    if existing:
                        # Preserve the previous version's verified values before the
                        # new parser replaces them. This is what makes rollback safe.
                        archived=db.snapshot_current_document(path)
                        if archived:
                            snapshots_archived.append({"file": rel_path, "snapshot_id": archived, "parser_version": existing.get("parser_version")})
                        rescanned.append(rel_path)
                    text=read_document(path); parsed=extract(text,path)
                    # A second extraction pass is triggered only when a consolidated
                    # report has too few core observations. This keeps normal scans
                    # fast while rescuing statements whose key table pages were missed.
                    core_metrics={"revenue","net_income","operating_profit","assets","equity","depreciation"}
                    found_metrics={m for m, *_rest in parsed.get("observations",[]) if m in core_metrics}
                    if parsed.get("scope")=="consolidated" and len(found_metrics)<3 and path.suffix.lower()==".pdf":
                        try:
                            import os
                            prev_pages=os.environ.get("OCR_RESERVE_PAGES")
                            os.environ["OCR_RESERVE_PAGES"]="28"
                            deep_text=read_document(path)
                            os.environ["OCR_RESERVE_PAGES"] = prev_pages if prev_pages is not None else "16"
                            deep_parsed=extract(deep_text,path)
                            if len(deep_parsed.get("observations",[]))>len(parsed.get("observations",[])):
                                text,parsed=deep_text,deep_parsed
                        except Exception:
                            pass
                    year=parsed["year"]
                    if year is None:
                        failed.append({"file":str(path.relative_to(REPORTS_DIR)),"reason":"Could not determine reporting year/date."}); continue
                    if len(text.strip())<200:
                        parsed["status"]="failed"; parsed["quality_score"]=0
                        parsed.setdefault("warnings",[]).append("Report text/OCR is too sparse. Check PyMuPDF and Tesseract with Vietnamese language data.")
                    elif not parsed["observations"]:
                        parsed["status"]="failed"; parsed["quality_score"]=0
                        parsed.setdefault("warnings",[]).append("Text was extracted but no financial line items matched the accounting labels.")
                    db.replace_document(path,company,industry,year,parsed["period_end"],parsed["scope"],PARSER_VERSION,digest,text[:2500000],parsed.get("quality_score",0),parsed.get("status","review"),parsed.get("warnings",[]),_ocr_was_used(text))
                    db.replace_observations(path,company,industry,year,parsed["period_end"],parsed["observations"])
                    # Save the successful result independently of the current
                    # document row. Future versions can reuse it by file hash.
                    if parsed.get("status", "review") != "failed" and parsed.get("observations"):
                        db.save_scan_snapshot(
                            path, digest, PARSER_VERSION,
                            company=company, industry=industry, year=year,
                            period_end=parsed["period_end"], scope=parsed["scope"],
                            text=text[:2500000], quality_score=parsed.get("quality_score",0),
                            status=parsed.get("status","review"), warnings=parsed.get("warnings",[]),
                            ocr_used=_ocr_was_used(text), observations=parsed["observations"],
                        )
                    document_count+=1; observation_count+=len(parsed["observations"])
                    print(f"[{parsed.get('status','review').upper():8}] {company[:24]:<24} -> {ticker_for(company):8} | {path.name} | scope={parsed.get('scope')} | period={parsed.get('period_end')} | obs={len(parsed.get('observations',[]))} | quality={parsed.get('quality_score',0)}")
                except Exception as exc:
                    failed.append({"file":str(path.relative_to(REPORTS_DIR)),"reason":str(exc)}); print(f"Scan error: {path}: {exc}")
    return {
        "documents":document_count,
        "observations":observation_count,
        "companies":db.companies(),
        "failed":failed,
        "stale_removed":stale,
        "rescanned":rescanned,
        "snapshot_restored":snapshot_restored,
        "snapshots_archived":snapshots_archived,
    }
