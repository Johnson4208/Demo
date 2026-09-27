from pathlib import Path
import hashlib
import re
import shutil
import unicodedata
from difflib import SequenceMatcher
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict
from urllib.parse import unquote

from pypdf import PdfReader
from config import (
    OCR_ENABLED,
    OCR_MAX_PAGES,
    OCR_DPI,
    OCR_CACHE_DIR,
    OCR_LANG,
    OCR_PSM_PRIMARY,
    OCR_PSM_SECONDARY,
    OCR_PROFILE_VERSION,
    OCR_TRIAGE_DPI,
    OCR_TRIAGE_PSM,
    OCR_FULL_PSM,
    OCR_RESERVE_PAGES,
    OCR_USE_OPTIONAL_PADDLE,
    OCR_TARGET_ANCHOR_THRESHOLD,
    TESSDATA_DIR,
    TESSERACT_CMD,
)

SUPPORTED = {".pdf", ".txt", ".md", ".csv", ".docx"}
DATE_PATTERNS = [
    r"\b(\d{1,2})[/-](\d{1,2})[/-](20\d{2})\b",
    r"\b(\d{1,2})\s+tháng\s+(\d{1,2})\s+năm\s+(20\d{2})\b",
    r"\b(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(20\d{2})\b",
]
MONTHS = {"january":1,"february":2,"march":3,"april":4,"may":5,"june":6,"july":7,"august":8,"september":9,"october":10,"november":11,"december":12}

ACCOUNTING_ANCHORS = (
    "báo cáo kết quả hoạt động kinh doanh",
    "bao cao ket qua hoat dong kinh doanh",
    "bảng cân đối kế toán",
    "bang can doi ke toan",
    "báo cáo lưu chuyển tiền tệ",
    "bao cao luu chuyen tien te",
    "doanh thu thuần",
    "lợi nhuận sau thuế",
    "tài sản",
    "nợ phải trả",
)


def _date_from_match(match):
    day, month, year = match.groups()
    try:
        month_key = str(month).lower()
        month = MONTHS[month_key] if month_key in MONTHS else int(month)
        return datetime(int(year), int(month), int(day)).date()
    except Exception:
        return None


def _all_dates(text):
    out=[]
    for pattern in DATE_PATTERNS:
        for match in re.finditer(pattern,text or "",flags=re.I):
            value=_date_from_match(match)
            if value: out.append((match.start(),value))
    return out


def _period_from_filename(name):
    """Infer a reporting period from noisy Vietnamese/URL-safe filenames.

    Filename timestamps are treated as noise. If a quarter marker exists, the
    first 1-4 immediately after it is the quarter and the last 20xx found in the
    nearby suffix is used as the reporting year. Annual labels similarly use the
    nearby 20xx token. This handles filenames where spaces were encoded as ``20``.
    """
    low=unquote(Path(name).name if name else "").lower().replace("-","_")
    # Quarter marker: Quy 2 2026, Quy202202026, Q22026, etc.
    qmatch=re.search(r"(?:qu[yý]|quarter|q(?=[^a-z]))", low, re.I)
    if qmatch:
        tail=low[qmatch.end():qmatch.end()+100]
        qm=re.search(r"([1-4])", tail)
        # Prefer the last 20xx token before the next filename separator. This
        # handles encoded names such as `Quy202202026_...` where 2022 is an
        # artifact of encoded spacing and 2026 is the actual report year.
        parts=tail.strip("_").split("_")
        year=None
        for part in parts[:10]:
            ys=re.findall(r"(?=(20\d{2}))", part)
            if not ys:
                continue
            # Skip long pure-digit upload timestamps such as 20260616102031.
            if part.isdigit() and len(part) >= 12:
                continue
            year=int(ys[-1])
            break
        if year is None:
            ys=re.findall(r"(?=(20\d{2}))", tail)
            year=int(ys[-1]) if ys else None
        if qm and year:
            q=int(qm.group(1)); month=q*3
            return datetime(year,month,{3:31,6:30,9:30,12:31}[month]).date()

    # Explicit annual marker. Prefer a year near the marker; use the last nearby
    # match because encoded forms may contain an extra 20xx fragment.
    amatch=re.search(r"(?:nam|năm|year)", low, re.I)
    if amatch:
        tail=low[amatch.end():amatch.end()+30]
        years=re.findall(r"(?=(20\d{2}))", tail)
        if years:
            y=int(years[-1]); return datetime(y,12,31).date()

    years=[int(x) for x in re.findall(r"20\d{2}", low)]
    if not years:
        return None
    return datetime(years[-1],12,31).date()

def _period_from_text(text):
    """Extract reporting-period end from explicit statement language.

    The input is normalized by removing punctuation, so date separators may appear
    as spaces. We therefore accept slash, dash, or whitespace between components.
    """
    norm=_norm_ocr_probe_text(text or '')
    sep=r"(?:[ /\-]+)"
    patterns=[
        rf"(?:tu|from){sep}ngay{sep}\d{{1,2}}{sep}\d{{1,2}}{sep}20\d{{2}}{sep}(?:den|to){sep}ngay{sep}(\d{{1,2}}){sep}(\d{{1,2}}){sep}(20\d{{2}})",
        rf"(?:tu|from){sep}ngay{sep}\d{{1,2}}{sep}thang{sep}\d{{1,2}}{sep}nam{sep}20\d{{2}}{sep}(?:den|to){sep}ngay{sep}(\d{{1,2}}){sep}thang{sep}(\d{{1,2}}){sep}(20\d{{2}})",
        rf"(?:ket thuc ngay|kt thuc ngay|as at|as of|for the period ended|for the year ended|cho nam tai chinh ket thuc|cho ky tai chinh ket thuc){sep}(\d{{1,2}}){sep}(\d{{1,2}}){sep}(20\d{{2}})",
        rf"(?:ket thuc ngay|kt thuc ngay|as at|as of|for the period ended|for the year ended|cho nam tai chinh ket thuc|cho ky tai chinh ket thuc){sep}(\d{{1,2}}){sep}thang{sep}(\d{{1,2}}){sep}nam{sep}(20\d{{2}})",
    ]
    for pattern in patterns:
        m=re.search(pattern,norm,re.I|re.S)
        if not m:
            continue
        try:
            day,month,year=m.groups()[-3:]
            return datetime(int(year),int(month),int(day)).date()
        except Exception:
            continue
    # Annual reports sometimes say "cho nam tai chinh ket thuc ngay 31 thang 3 nam 2026"
    # while OCR fuses or drops words. Match the distinctive ending clause directly.
    m=re.search(r"(?:ket thuc|kt thuc)\s+ngay\s+(\d{1,2})\s+(?:thang\s+)?(\d{1,2})\s+(?:nam\s+)?(20\d{2})",norm,re.I)
    if m:
        try:
            day,month,year=m.groups(); return datetime(int(year),int(month),int(day)).date()
        except Exception:
            pass
    return None


def _norm_ocr_probe_text(text):
    value=unicodedata.normalize("NFKD",text or "")
    value=value.replace("đ","d").replace("Đ","D")
    value="".join(c for c in value if not unicodedata.combining(c))
    value=re.sub(r"[^a-zA-Z0-9]+"," ",value)
    return re.sub(r"\s+"," ",value).strip().lower()


def _compact_for_match(text):
    return re.sub(r"[^a-z0-9]", "", _norm_ocr_probe_text(text))


def _fuzzy_similar(a, b):
    a=_compact_for_match(a); b=_compact_for_match(b)
    if not a or not b: return 0.0
    return SequenceMatcher(None,a,b).ratio()


def _fuzzy_period_from_heading(text):
    # Handles OCR forms such as "kt thUc ngáy 31 tháng 3 näm 2026".
    norm=_norm_ocr_probe_text(text)
    m=re.search(r"(?:ket thuc|kt thuc)\s+ngay\s+(\d{1,2})\s+thang\s+(\d{1,2})\s+nam\s+(20\d{2})",norm)
    if m:
        d,mo,y=m.groups()
        try: return datetime(int(y),int(mo),int(d)).date()
        except Exception: pass
    return None


def infer_period_end(text, path=None):
    # Prefer the reporting-period language in the statement itself. This avoids
    # picking a random later date from notes, signatures, or filing metadata.
    from_text=_period_from_text(text or "") or _fuzzy_period_from_heading(text or "")
    if from_text:
        return from_text
    filename_period=_period_from_filename(path)
    if filename_period:
        return filename_period
    dates=_all_dates(text)
    if not dates:
        name=unquote(Path(path).name if path else "").lower()
        quarter=re.search(r"qu[ýy]\s*([1-4])",name)
        year=re.search(r"20\d{2}",name)
        if year and quarter:
            q=int(quarter.group(1)); y=int(year.group(0)); month=q*3
            return datetime(y,month,{3:31,6:30,9:30,12:31}[month]).date()
        return None
    # Generic fallback: prefer dates near explicit end/statement language, then the
    # latest date no later than a plausible report year inferred from the filename.
    context_patterns=[r"tại ngày",r"tai ngay",r"đến ngày",r"den ngay",r"kết thúc ngày",r"ket thuc ngay",r"as at",r"as of",r"for the year ended",r"for the period ended"]
    candidates=[]
    for position,date_value in dates:
        left=text[max(0,position-220):position].lower()
        if any(re.search(pattern,left) for pattern in context_patterns):
            candidates.append(date_value)
    if candidates:
        return max(candidates)
    return max(value for _,value in dates)

def infer_year(path,text=""):
    period_end=infer_period_end(text,path)
    if period_end: return period_end.year
    match=re.search(r"(20\d{2})",unquote(Path(path).name))
    if match: return int(match.group(1))
    years=[int(x) for x in re.findall(r"\b(20\d{2})\b",text)]
    return max(years) if years else None


def infer_scope(path,text=""):
    name=unquote(Path(path).name).lower()
    raw=text or ""
    low=raw.lower()
    compact=_norm_ocr_probe_text(raw)
    compact_name=_norm_ocr_probe_text(name)
    # Prefer the scope attached to an actual financial-statement heading.
    section_heads=[
        "báo cáo kết quả hoạt động kinh doanh",
        "bao cao ket qua hoat dong kinh doanh",
        "bảng cân đối kế toán",
        "bang can doi ke toan",
        "báo cáo lưu chuyển tiền tệ",
        "bao cao luu chuyen tien te",
    ]
    scored={"consolidated":0,"separate":0}
    for head in section_heads:
        start=0; target=head.lower()
        while True:
            pos=low.find(target,start)
            if pos<0: break
            context=low[max(0,pos-500):min(len(low),pos+500)]
            if any(x in context for x in ["hợp nhất","hop nhat","consolidated"]): scored["consolidated"]+=3
            if any(x in context for x in ["riêng","rieng","separate","standalone"]): scored["separate"]+=3
            start=pos+len(target)
    if scored["consolidated"]>scored["separate"] and scored["consolidated"]:
        return "consolidated"
    if scored["separate"]>scored["consolidated"] and scored["separate"]:
        return "separate"
    # Fuzzy match OCR-damaged statement titles. This is intentionally used only
    # for scope classification, where the title is a high-value anchor.
    for line in raw.splitlines()[:220]:
        compact_line=_compact_for_match(line)
        if _fuzzy_similar(compact_line, "bao cao tai chinh hop nhat") >= 0.76 or _fuzzy_similar(compact_line, "consolidated financial statements") >= 0.78:
            scored["consolidated"] += 2
        if _fuzzy_similar(compact_line, "bao cao tai chinh rieng") >= 0.76 or _fuzzy_similar(compact_line, "separate financial statements") >= 0.78:
            scored["separate"] += 2
    if scored["consolidated"]>scored["separate"] and scored["consolidated"]:
        return "consolidated"
    if scored["separate"]>scored["consolidated"] and scored["separate"]:
        return "separate"
    # Fall back to explicit title occurrences anywhere in the parsed text.
    consolidated=sum(low.count(x) for x in ["báo cáo tài chính hợp nhất", "bao cao tai chinh hop nhat", "consolidated financial statements"] )
    separate=sum(low.count(x) for x in ["báo cáo tài chính riêng", "bao cao tai chinh rieng", "separate financial statements"] )
    consolidated += compact.count("bao cao tai chinh hop nhat") + compact.count("consolidated financial statements")
    separate += compact.count("bao cao tai chinh rieng") + compact.count("separate financial statements") + compact.count("standalone financial statements")
    if consolidated>separate and consolidated: return "consolidated"
    if separate>consolidated and separate: return "separate"
    # Filename is only a tie-breaker, never the first source of truth.
    if any(x in name for x in ["hop20nhat","hop20nh","hop nhat","hop_nhat","consolidated"]) or "hop nhat" in compact_name: return "consolidated"
    if any(x in name for x in ["rieng","riêng","separate","standalone"]) or any(x in compact_name for x in ["bao cao tai chinh rieng","separate financial statements","standalone"]): return "separate"
    return "unknown"


def _norm_ocr_probe(text):
    t=(text or "").lower()
    hits=sum(1 for k in ACCOUNTING_ANCHORS if k in t or k.replace("á","a").replace("ậ","a") in t)
    return hits >= 2


_OCR_READY = None
_OCR_ERROR = None


def _set_tesseract_cmd(pytesseract):
    if TESSERACT_CMD:
        pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD
    elif not shutil.which("tesseract"):
        raise RuntimeError("Tesseract OCR is not installed or is not available on PATH.")


def _ensure_ocr_ready():
    global _OCR_READY, _OCR_ERROR
    if _OCR_READY is not None:
        if _OCR_READY:
            return True, ""
        raise RuntimeError(_OCR_ERROR or "Tesseract OCR is not ready.")
    try:
        import pytesseract
        _set_tesseract_cmd(pytesseract)
        if not TESSDATA_DIR:
            raise RuntimeError(
                "No usable Tesseract tessdata directory was found. "
                "Expected eng.traineddata and vie.traineddata next to the Tesseract installation."
            )
        traineddata = [TESSDATA_DIR / "eng.traineddata", TESSDATA_DIR / "vie.traineddata"]
        missing = [str(p) for p in traineddata if not p.exists()]
        if missing:
            raise RuntimeError("Missing Tesseract language files: " + ", ".join(missing))
        # Do not force --tessdata-dir here. The Windows Tesseract installer
        # knows its own tessdata location, and passing a quoted Windows path
        # through pytesseract can cause Tesseract to receive a malformed path.
        languages = set(pytesseract.get_languages())
        required = {"eng", "vie"}
        missing_langs = sorted(required - languages)
        if missing_langs:
            raise RuntimeError(
                f"Tesseract found at {TESSERACT_CMD}, but languages {missing_langs} are unavailable in {TESSDATA_DIR}."
            )
        # Tiny smoke test: it verifies that tesseract can initialize the language
        # models, which is the failure mode seen on the user's Windows machine.
        from PIL import Image, ImageOps
        import io
        probe = ImageOps.grayscale(Image.new("RGB", (80, 40), "white"))
        pytesseract.image_to_string(
            probe, lang=OCR_LANG,
            config='--oem 1 --psm 6',
        )
        _OCR_READY = True
        _OCR_ERROR = None
        return True, ""
    except Exception as exc:
        _OCR_READY = False
        _OCR_ERROR = str(exc)
        raise RuntimeError(_OCR_ERROR)


def _ocr_anchor_score(text):
    low=_norm_ocr_probe_text(text or "")
    anchors=[
        "bao cao ket qua hoat dong kinh doanh",
        "bang can doi ke toan",
        "bao cao luu chuyen tien te",
        "doanh thu ban hang va cung cap dich vu",
        "doanh thu thuan",
        "loi nhuan gop",
        "loi nhuan sau thue",
        "chi phi ban hang",
    ]
    hits=sum(1 for a in anchors if a in low)
    nums=len(re.findall(r"\d[\d.,]{5,}", text or ""))
    return hits*20 + min(nums, 20) + (10 if "vnd" in low else 0)


def _ocr_data_rows(pytesseract, image, lang, config):
    """OCR a financial page and rebuild rows from word coordinates.

    Plain OCR text can place a table's number columns above / below the label
    text. Using image_to_data() gives every word a bounding box, allowing us to
    rebuild a visual row before the accounting parser sees it.
    """
    from pytesseract import Output
    data=pytesseract.image_to_data(image, lang=lang, config=config, output_type=Output.DICT)
    words=[]
    for i,raw in enumerate(data.get("text", [])):
        token=(raw or "").strip()
        if not token:
            continue
        try:
            conf=float(data.get("conf", [0])[i])
        except Exception:
            conf=-1
        if conf < 20:
            continue
        left=float(data["left"][i]); top=float(data["top"][i]); height=float(data["height"][i])
        center_y=top + height/2.0
        words.append((center_y,left,token,conf,height))
    words.sort(key=lambda x:(x[0],x[1]))
    if not words:
        return ""
    tolerance=max(8.0, image.height*0.008)
    rows=[]
    for item in words:
        if not rows or abs(item[0]-rows[-1]["cy"])>tolerance:
            rows.append({"cy":item[0],"items":[item]})
        else:
            rows[-1]["items"].append(item)
            rows[-1]["cy"]=sum(x[0] for x in rows[-1]["items"])/len(rows[-1]["items"])
    lines=[]
    for row in rows:
        items=sorted(row["items"], key=lambda x:x[1])
        lines.append(" ".join(x[2] for x in items))
    return "\n".join(lines)


def _ocr_image(image, preferred_rotation=0):
    import pytesseract
    from PIL import ImageEnhance, ImageOps, ImageFilter
    _set_tesseract_cmd(pytesseract)
    _ensure_ocr_ready()
    prepared=ImageOps.grayscale(image)
    prepared=ImageEnhance.Contrast(prepared).enhance(1.8)
    prepared=prepared.filter(ImageFilter.SHARPEN)
    config=f'--oem 1 --psm {OCR_PSM_PRIMARY}'
    warnings=[]
    angles=[]
    # Financial PDFs frequently carry incorrect page rotation metadata. Test all
    # four cardinal orientations rather than assuming the PDF metadata is correct.
    for angle in (preferred_rotation,0,90,180,270):
        angle=int(angle)%360
        if angle not in angles:
            angles.append(angle)
    best_text=""; best_score=-1; best_angle=0
    for angle in angles:
        candidate=prepared.rotate(angle,expand=True) if angle else prepared
        try:
            text=_ocr_data_rows(pytesseract,candidate,OCR_LANG,config)
        except Exception as exc:
            warnings.append(str(exc)); continue
        score=_ocr_anchor_score(text)
        if score>best_score:
            best_text,best_score,best_angle=text,score,angle
        # Once an accounting table is clearly readable, stop.
        if score>=70:
            break
    if best_score<50:
        # A secondary layout pass helps sparse / lightly separated statements.
        for angle in angles:
            candidate=prepared.rotate(angle,expand=True) if angle else prepared
            try:
                text=_ocr_data_rows(pytesseract,candidate,OCR_LANG,f'--oem 1 --psm {OCR_PSM_SECONDARY}')
            except Exception as exc:
                warnings.append(str(exc)); continue
            score=_ocr_anchor_score(text)
            if score>best_score:
                best_text,best_score,best_angle=text,score,angle
            if score>=70:
                break
    if not best_text:
        raise RuntimeError("Tesseract produced no usable text for this page.")
    if best_angle != 0:
        warnings.append(f"OCR page orientation corrected by {best_angle} degrees")
    return best_text,warnings



def _page_anchor_score(text):
    low=_norm_ocr_probe_text(text or "")
    anchors=(
        "bao cao ket qua hoat dong kinh doanh",
        "bao cao luu chuyen tien te",
        "bang can doi ke toan",
        "doanh thu thuan",
        "loi nhuan sau thue",
        "khu hao",
        "tong cong tai san",
        "tong cong nguon von",
        "loi nhuan thuan tu hoat dong kinh doanh",
    )
    hits=sum(1 for a in anchors if a in low)
    numbers=len(re.findall(r"\d[\d.,]{6,}", text or ""))
    return hits*10 + min(numbers,12)


def _quick_ocr_image(image, preferred_rotation=0):
    import pytesseract
    from PIL import ImageEnhance, ImageOps
    _set_tesseract_cmd(pytesseract); _ensure_ocr_ready()
    prepared=ImageOps.grayscale(image)
    prepared=ImageEnhance.Contrast(prepared).enhance(1.4)
    angles=[]
    for angle in (preferred_rotation,0,90,180,270):
        angle=int(angle)%360
        if angle not in angles: angles.append(angle)
    best=("",-1,0)
    for angle in angles:
        candidate=prepared.rotate(angle,expand=True) if angle else prepared
        try:
            text=_ocr_data_rows(pytesseract,candidate,OCR_LANG,f"--oem 1 --psm {OCR_TRIAGE_PSM}")
        except Exception:
            continue
        score=_page_anchor_score(text)
        if score>best[1]: best=(text,score,angle)
        if score>=OCR_TARGET_ANCHOR_THRESHOLD*10: break
    return best


def _render_page_images(path, indices, dpi):
    import fitz
    from PIL import Image
    document=fitz.open(str(path))
    zoom=dpi/72.0
    out=[]
    for index in indices:
        if index>=len(document): continue
        page=document[index]
        pixmap=page.get_pixmap(matrix=fitz.Matrix(zoom,zoom),colorspace=fitz.csRGB,alpha=False)
        image=Image.frombytes("RGB",[pixmap.width,pixmap.height],pixmap.samples)
        out.append((index,image,page.rotation))
    document.close()
    return out


def _page_native_texts(path):
    try:
        reader=PdfReader(str(path))
        return [(i,(page.extract_text() or "")) for i,page in enumerate(reader.pages)]
    except Exception:
        return []


def _choose_ocr_pages(path, native_pages):
    """Return every eligible page for low-cost triage.

    Completeness is more important than a page-number heuristic: scanned reports can
    put comparative tables, depreciation notes, or cash-flow evidence well after page
    16/36. The expensive high-resolution pass is still selective, so the all-page triage
    does not imply all-page high-resolution OCR.
    """
    total=len(native_pages)
    if not total:
        return []
    limit=total if OCR_MAX_PAGES in (0,None) else min(total,OCR_MAX_PAGES)
    return list(range(limit))


def _optional_paddle_ocr(image_path):
    """Optional table-aware rescue. It is never required for normal operation."""
    if not OCR_USE_OPTIONAL_PADDLE: return ""
    try:
        from paddleocr import PaddleOCR
        ocr=PaddleOCR(lang="vi", use_doc_orientation_classify=True, use_doc_unwarping=True, use_textline_orientation=True)
        result=ocr.predict(str(image_path))
        lines=[]
        for res in result or []:
            payload=getattr(res,"json",None)
            if callable(payload): payload=payload()
            if isinstance(payload,dict):
                texts=((payload.get("res") or {}).get("rec_texts") or [])
                lines.extend(str(x) for x in texts if x)
        return "\n".join(lines)
    except Exception:
        return ""


def _adaptive_render_with_fitz(path):
    native_pages=_page_native_texts(path)
    total=len(native_pages)
    if total==0: return []
    limit=total if OCR_MAX_PAGES in (0,None) else min(total,OCR_MAX_PAGES)
    candidate_indices=_choose_ocr_pages(path,native_pages)

    # First, triage all candidate pages at low DPI. This pass is designed to find
    # pages, not to produce final financial text.
    triage=[]
    for index,image,rotation in _render_page_images(path,candidate_indices,OCR_TRIAGE_DPI):
        text,score,angle=_quick_ocr_image(image,rotation)
        triage.append((index,score,angle,text))

    # Always include the highest-scoring pages plus pages with statement anchors.
    triage_sorted=sorted(triage,key=lambda x:x[1],reverse=True)
    target=set()
    for index,score,angle,text in triage_sorted[:max(OCR_RESERVE_PAGES,8)]:
        target.add(index)
    for index,score,angle,text in triage_sorted:
        if score>=OCR_TARGET_ANCHOR_THRESHOLD*10: target.add(index)

    # Also inspect native-text pages that are structurally important even when OCR
    # triage was weak, so a missing comparative column can trigger a deep pass later.
    for index,text in native_pages:
        if index>=limit: continue
        low=_norm_ocr_probe_text(text)
        if any(a in low for a in ("doanh thu thuần","loi nhuan sau thue","tong cong tai san","khau hao","bang can doi ke toan","bao cao ket qua hoat dong kinh doanh")):
            target.add(index)

    # Final high-resolution OCR only on target pages.
    results=[]
    for index,image,rotation in _render_page_images(path,sorted(target),OCR_DPI):
        text,warnings=_ocr_image(image,rotation)
        # If the high-quality Tesseract result is still weak, optionally try the
        # table-aware PaddleOCR rescue. This never replaces a good Tesseract result.
        if _page_anchor_score(text)<10:
            paddle_text=_optional_paddle_ocr(str(path))
            if paddle_text and len(paddle_text)>len(text):
                text += "\n" + paddle_text
                warnings.append("Optional PaddleOCR rescue used")
        results.append((index,text,warnings))
    return results

def _render_with_fitz(path, page_limit):
    import fitz
    from PIL import Image
    zoom=OCR_DPI/72.0
    document=fitz.open(str(path))
    page_limit=min(len(document),page_limit)
    def render(index):
        page=document[index]
        pixmap=page.get_pixmap(matrix=fitz.Matrix(zoom,zoom),colorspace=fitz.csRGB,alpha=False)
        image=Image.frombytes("RGB",[pixmap.width,pixmap.height],pixmap.samples)
        text,warnings=_ocr_image(image, page.rotation)
        return index,text,warnings
    with ThreadPoolExecutor(max_workers=min(4,page_limit or 1)) as pool:
        return list(pool.map(render,range(page_limit)))


def _render_with_poppler(path,page_limit):
    import subprocess,tempfile
    from PIL import Image
    info=subprocess.run(["pdfinfo",str(path)],capture_output=True,text=True,timeout=30,check=True)
    total_pages=1
    for line in info.stdout.splitlines():
        if line.lower().startswith("pages:"):
            total_pages=int(line.split(":",1)[1].strip()); break
    page_limit=min(total_pages,page_limit)
    results=[]
    with tempfile.TemporaryDirectory() as tmp:
        prefix=f"{tmp}/page"
        subprocess.run(["pdftoppm","-png","-r",str(int(OCR_DPI)),"-f","1","-l",str(page_limit),str(path),prefix],capture_output=True,text=True,timeout=180,check=True)
        for candidate in sorted(Path(tmp).glob("page-*.png")):
            match=re.search(r"(\d+)\.png$",candidate.name)
            if not match: continue
            idx=int(match.group(1))-1
            if idx<page_limit:
                with Image.open(candidate) as image:
                    text,warnings=_ocr_image(image.convert("RGB"), 0)
                    results.append((idx,text,warnings))
    return results


def _ocr_pdf(path):
    try:
        _ensure_ocr_ready()
    except Exception as exc:
        print(f"OCR warning {path}: Tesseract OCR is not ready -> {exc}")
        return ""
    cache_key=hashlib.sha1(
        f"{Path(path).resolve()}|{path.stat().st_size}|{path.stat().st_mtime_ns}|{OCR_LANG}|{OCR_DPI}|{OCR_MAX_PAGES}|{OCR_PROFILE_VERSION}|adaptive|{OCR_TRIAGE_DPI}|{OCR_TRIAGE_PSM}|{OCR_RESERVE_PAGES}|{TESSERACT_CMD}|{TESSDATA_DIR}".encode()
    ).hexdigest()
    cache_file=OCR_CACHE_DIR/f"{cache_key}.txt"
    if cache_file.exists():
        try: return cache_file.read_text(encoding="utf-8",errors="ignore")
        except Exception: pass
    errors=[]; results=[]
    try:
        results=_adaptive_render_with_fitz(path)
    except Exception as exc:
        errors.append(f"adaptive fitz renderer unavailable ({exc})")
    if not results:
        try:
            results=_render_with_poppler(path,OCR_MAX_PAGES or 10**9)
        except Exception as exc:
            errors.append(f"poppler renderer unavailable ({exc})")
    if not results:
        print(f"OCR warning {path}: no OCR renderer available -> {'; '.join(errors)}")
        return ""
    results.sort(key=lambda x:x[0])
    chunks=[]
    for idx,text,warnings in results:
        if not text.strip(): continue
        warning_line=("\nOCR_WARNING: " + " | ".join(warnings)) if warnings else ""
        chunks.append(f"\n--- OCR PAGE {idx+1} ---\n{text}{warning_line}")
    output="\n".join(chunks)
    try:
        OCR_CACHE_DIR.mkdir(parents=True,exist_ok=True); cache_file.write_text(output,encoding="utf-8")
    except Exception: pass
    return output

def _native_text_is_sufficient(native):
    compact=re.sub(r"\s+","",native or "")
    if len(compact)<700: return False
    low=(native or "").lower()
    anchor_hits=sum(1 for anchor in ACCOUNTING_ANCHORS if anchor in low)
    financial_numbers=len(re.findall(r"\d[\d.,]{5,}",native or ""))
    return anchor_hits>=3 and financial_numbers>=8


def read_document(path):
    path=Path(path); suffix=path.suffix.lower()
    if suffix==".pdf":
        reader=PdfReader(str(path))
        native="\n".join((page.extract_text() or "") for page in reader.pages)
        if _native_text_is_sufficient(native) or not OCR_ENABLED:
            return native
        ocr=_ocr_pdf(path)
        return (native+"\n"+ocr).strip()
    if suffix in {".txt",".md",".csv"}: return path.read_text(encoding="utf-8",errors="ignore")
    if suffix==".docx":
        from docx import Document
        return "\n".join(p.text for p in Document(str(path)).paragraphs)
    return ""


def sha256(path):
    digest=hashlib.sha256()
    with open(path,"rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""): digest.update(chunk)
    return digest.hexdigest()
