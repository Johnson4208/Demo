from pathlib import Path
import importlib

from config import REPORTS_DIR
from . import db


def check():
    checks=[]
    modules=["engine.analysis","engine.report_reader","engine.report_extractor","engine.risk","engine.stock","engine.news"]
    for module in modules:
        try:
            importlib.import_module(module)
            checks.append({"name": module, "ok": True, "message": "Loaded"})
        except Exception as exc:
            checks.append({"name": module, "ok": False, "message": str(exc)})

    companies=db.companies()
    reports=sum(c["reports"] for c in companies)
    checks.append({"name":"Report library", "ok": REPORTS_DIR.exists(), "message": f"{reports} report(s) indexed"})
    checks.append({"name":"Database", "ok": db.DB_PATH.exists(), "message": str(db.DB_PATH)})

    failed=[x for x in checks if not x["ok"]]
    return {
        "status": "READY" if not failed else "ATTENTION NEEDED",
        "checks": checks,
        "companies": companies,
        "recommendation": "Add more comparable reporting periods before trusting statistical conclusions." if reports < 20 else "The library has a larger evidence base; continue validating model outputs against later outcomes.",
    }
