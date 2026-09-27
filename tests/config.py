import os
from pathlib import Path
import shutil


def _env_flag(name, default=False):
    value = os.getenv(name)
    if value is None:
        return bool(default)
    return value.strip().lower() in {"1", "true", "yes", "on"}


ENVIRONMENT = os.getenv("SOLVAI_ENV", "development").strip().lower() or "development"
IS_PRODUCTION = ENVIRONMENT in {"production", "prod"}
APP_PORT = int(os.getenv("PORT", os.getenv("SOLVAI_PORT", "5000")))
TRUST_PROXY = _env_flag("SOLVAI_TRUST_PROXY", False)
PROXY_HOPS = max(1, min(3, int(os.getenv("SOLVAI_PROXY_HOPS", "1"))))
SECURE_COOKIES = _env_flag("SOLVAI_SECURE_COOKIES", IS_PRODUCTION)
OLLAMA_ENABLED = _env_flag("SOLVAI_OLLAMA_ENABLED", not IS_PRODUCTION)
REQUEST_TIMEOUT = max(5, min(300, int(os.getenv("SOLVAI_REQUEST_TIMEOUT", "120"))))
MAX_UPLOAD_MB = max(1, min(250, int(os.getenv("SOLVAI_MAX_UPLOAD_MB", "80"))))
MAX_REPORT_PAGES = max(1, min(2000, int(os.getenv("SOLVAI_MAX_REPORT_PAGES", "500"))))
MAX_USER_UPLOADS_PER_HOUR = max(1, min(100, int(os.getenv("SOLVAI_MAX_USER_UPLOADS_PER_HOUR", "12"))))

BASE_DIR = Path(__file__).resolve().parent
# Persistent data can live outside the application/version directory. This is
# important for Docker upgrades: containers/images may be replaced while the
# mounted data volume remains intact.
#
# Local/Windows default preserves the existing layout for backwards
# compatibility. In Docker, set SOLVAI_DATA_DIR=/data and mount a named volume
# or host folder at /data.
_DATA_ROOT_ENV = os.getenv("SOLVAI_DATA_DIR", "").strip()
if _DATA_ROOT_ENV:
    DATA_ROOT = Path(_DATA_ROOT_ENV).expanduser().resolve()
    REPORTS_DIR = Path(os.getenv("SOLVAI_REPORTS_DIR", str(DATA_ROOT / "reports" / "Companies_reports"))).expanduser().resolve()
    STORAGE_DIR = Path(os.getenv("SOLVAI_STORAGE_DIR", str(DATA_ROOT / "storage"))).expanduser().resolve()
else:
    DATA_ROOT = BASE_DIR
    REPORTS_DIR = Path(os.getenv("SOLVAI_REPORTS_DIR", str(BASE_DIR / "reports" / "Companies_reports"))).expanduser().resolve()
    STORAGE_DIR = Path(os.getenv("SOLVAI_STORAGE_DIR", str(BASE_DIR / "storage"))).expanduser().resolve()

DB_PATH = Path(os.getenv("SOLVAI_DB_PATH", str(STORAGE_DIR / "financial_ai.sqlite3"))).expanduser().resolve()
UPLOAD_DIR = STORAGE_DIR / "uploads"
OCR_CACHE_DIR = STORAGE_DIR / "ocr_cache"
SYMBOL_REGISTRY_PATH = Path(
    os.getenv("SOLVAI_SYMBOL_REGISTRY", str(DATA_ROOT / "company_symbols.json"))
).expanduser().resolve()
PERSISTENCE_MARKER = STORAGE_DIR / ".solvai_persistence_initialized"
# Tesseract should normally use the system installation on Windows.  A
# project-local tessdata directory is kept only as a fallback for portable
# deployments.  Set TESSDATA_DIR explicitly to override this behavior.

# Bump whenever extraction/OCR logic changes. The scanner uses this to invalidate
# stale/empty parses automatically.
APP_VERSION = "45.0.0"
PARSER_VERSION = "13.5.0"
OCR_PROFILE_VERSION = "7.3"

STOCK_PERIOD = os.getenv("STOCK_PERIOD", "5y")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")

OCR_ENABLED = os.getenv("OCR_ENABLED", "1") != "0"
OCR_MAX_PAGES = int(os.getenv("OCR_MAX_PAGES", "0"))  # 0 = all pages
OCR_DPI = float(os.getenv("OCR_DPI", "190"))
OCR_LANG = os.getenv("OCR_LANG", "vie+eng")
OCR_PSM_PRIMARY = int(os.getenv("OCR_PSM_PRIMARY", "6"))
OCR_PSM_SECONDARY = int(os.getenv("OCR_PSM_SECONDARY", "11"))



def initialize_persistent_storage():
    """Prepare durable storage and migrate a legacy project-local store once.

    When SOLVAI_DATA_DIR points to a mounted Docker volume, the first startup
    copies the old project-local database/reports into that durable location.
    Later application versions use the same database and report files.
    """
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    OCR_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Keep the market-symbol mapping beside other persistent runtime data so a
    # newly added company can be connected to its exchange symbol without
    # rebuilding the image.  The packaged mapping is only a safe starter file.
    symbol_seed = BASE_DIR / "data" / "company_symbols.json"
    if _DATA_ROOT_ENV and not SYMBOL_REGISTRY_PATH.exists() and symbol_seed.exists():
        try:
            SYMBOL_REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(symbol_seed, SYMBOL_REGISTRY_PATH)
        except OSError:
            pass

    # Migration is only relevant when an external data root is configured.
    if not _DATA_ROOT_ENV:
        return {"migrated": False, "legacy_db": False, "legacy_reports": False}

    marker = PERSISTENCE_MARKER
    if marker.exists():
        return {"migrated": False, "legacy_db": False, "legacy_reports": False}

    seed_root = Path(os.getenv("SOLVAI_SEED_DIR", "/seed")).expanduser().resolve()
    legacy_storage = seed_root / "storage"
    legacy_reports = seed_root / "reports" / "Companies_reports"
    migrated_db = False
    migrated_reports = False

    legacy_db = legacy_storage / "financial_ai.sqlite3"
    try:
        if DB_PATH != legacy_db and not DB_PATH.exists() and legacy_db.exists():
            DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(legacy_db, DB_PATH)
            migrated_db = True
    except OSError:
        pass

    try:
        if REPORTS_DIR != legacy_reports and legacy_reports.exists():
            target_empty = not any(REPORTS_DIR.iterdir())
            if target_empty:
                shutil.copytree(legacy_reports, REPORTS_DIR, dirs_exist_ok=True)
                migrated_reports = True
    except OSError:
        pass

    try:
        marker.write_text(
            "Persistent SolvAI data initialized.\n"
            f"DATA_ROOT={DATA_ROOT}\n"
            f"DB_PATH={DB_PATH}\n"
            f"REPORTS_DIR={REPORTS_DIR}\n",
            encoding="utf-8",
        )
    except OSError:
        pass

    return {
        "migrated": migrated_db or migrated_reports,
        "legacy_db": migrated_db,
        "legacy_reports": migrated_reports,
    }


def resolve_tesseract():
    explicit = os.getenv("TESSERACT_CMD", "").strip()
    candidates = [
        explicit,
        shutil.which("tesseract"),
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ]
    seen=set()
    for value in candidates:
        if not value:
            continue
        try:
            candidate=str(Path(value).expanduser())
        except Exception:
            continue
        if candidate in seen:
            continue
        seen.add(candidate)
        if Path(candidate).exists():
            return candidate
    return None


def resolve_tessdata(tesseract_cmd):
    explicit = os.getenv("TESSDATA_DIR", "").strip()
    candidates=[]
    if explicit:
        candidates.append(Path(explicit).expanduser())
    if tesseract_cmd:
        exe=Path(tesseract_cmd).resolve()
        candidates.append(exe.parent / "tessdata")
    # Portable/local fallback.  Only use it when the expected language files
    # are actually present.
    candidates.append(BASE_DIR / "tessdata")
    for candidate in candidates:
        try:
            if candidate.is_dir() and (candidate / "eng.traineddata").exists() and (candidate / "vie.traineddata").exists():
                return candidate.resolve()
        except OSError:
            continue
    return None


TESSERACT_CMD = resolve_tesseract()
TESSDATA_DIR = resolve_tessdata(TESSERACT_CMD)

TRUSTED_NEWS_DOMAINS = {
    "reuters.com": 1.00,
    "bloomberg.com": 1.00,
    "ft.com": 0.95,
    "cnbc.com": 0.90,
    "vietnamnews.vn": 0.85,
    "vnexpress.net": 0.80,
    "tuoitre.vn": 0.75,
    "thanhnien.vn": 0.75,
    "cafef.vn": 0.70,
    "vietstock.vn": 0.70,
}

# Adaptive OCR: a cheap page-triage pass finds accounting pages first, then the
# high-quality OCR pass runs only on relevant or low-confidence pages.
OCR_TRIAGE_DPI = float(os.getenv("OCR_TRIAGE_DPI", "92"))
OCR_TRIAGE_PSM = int(os.getenv("OCR_TRIAGE_PSM", "11"))
OCR_FULL_PSM = int(os.getenv("OCR_FULL_PSM", str(OCR_PSM_PRIMARY)))
OCR_RESERVE_PAGES = int(os.getenv("OCR_RESERVE_PAGES", "16"))
OCR_USE_OPTIONAL_PADDLE = os.getenv("OCR_USE_OPTIONAL_PADDLE", "0") == "1"
OCR_TARGET_ANCHOR_THRESHOLD = int(os.getenv("OCR_TARGET_ANCHOR_THRESHOLD", "4"))
