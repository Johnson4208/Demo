from pathlib import Path
import shutil
import subprocess

ROOT=Path(__file__).resolve().parent

from config import DATA_ROOT, REPORTS_DIR, STORAGE_DIR, PARSER_VERSION, OCR_PROFILE_VERSION
print("Financial AI diagnostics")
print("="*60)
print("Parser version:", PARSER_VERSION)
print("OCR profile:", OCR_PROFILE_VERSION)

tesseract=shutil.which("tesseract") or str(Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"))
print("Tesseract:", tesseract if Path(tesseract).exists() else "NOT FOUND")
if Path(tesseract).exists():
    try:
        version=subprocess.run([tesseract,"--version"],capture_output=True,text=True,timeout=10)
        print(version.stdout.splitlines()[0] if version.stdout else version.stderr.splitlines()[0])
        langs=subprocess.run([tesseract,"--list-langs"],capture_output=True,text=True,timeout=10)
        print("Languages:", ", ".join(x.strip() for x in langs.stdout.splitlines()[1:] if x.strip()))
    except Exception as exc:
        print("Tesseract check failed:",exc)

try:
    import fitz
    print("PyMuPDF:", fitz.__doc__.splitlines()[0])
except Exception as exc:
    print("PyMuPDF: FAILED",exc)

try:
    import pytesseract
    from config import TESSDATA_DIR, OCR_LANG, TESSERACT_CMD
    if TESSERACT_CMD:
        pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD
    print("Configured tesseract:", TESSERACT_CMD or "NOT FOUND")
    print("Resolved tessdata:", TESSDATA_DIR or "NOT FOUND")
    print("OCR language:", OCR_LANG)
    if TESSDATA_DIR:
        print("eng.traineddata:", (TESSDATA_DIR/"eng.traineddata").exists())
        print("vie.traineddata:", (TESSDATA_DIR/"vie.traineddata").exists())
        try:
            langs=set(pytesseract.get_languages())
            print("Required languages:", {"eng","vie"}.issubset(langs), "available:", ", ".join(sorted(langs)))
        except Exception as exc:
            print("Tessdata initialization FAILED:", exc)
except Exception as exc:
    print("pytesseract check failed:",exc)

print("Data root:", DATA_ROOT)
print("Reports folder:", REPORTS_DIR)
print("Storage folder:", STORAGE_DIR)
print("SQLite:", STORAGE_DIR/"financial_ai.sqlite3")
print("="*60)
try:
    from engine.report_reader import _ensure_ocr_ready
    _ensure_ocr_ready()
    print("OCR self-test: PASS (Tesseract can initialize eng+vie).")
except Exception as exc:
    print("OCR self-test: FAIL", exc)
print("Next step: run scan.bat after any parser upgrade, then inspect the Overview data-quality score.")
