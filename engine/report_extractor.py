import re
import unicodedata
from difflib import SequenceMatcher
from .report_reader import infer_year, infer_period_end, infer_scope

LABELS={
"gross_revenue":["doanh thu bán hàng và cung cấp dịch vụ","doanh thu ban hang va cung cap dich vu","gross revenue","sales revenue"],
"revenue_reductions":["các khoản giảm trừ doanh thu","các khoản giảm trừ","revenue deductions","deductions from revenue","cac khoan giam tru doanh thu"],
"revenue":["doanh thu thuần về bán hàng và cung cấp dịch vụ","doanh thu thuần","doanh thu thun","net revenue","net sales"],
"cost_of_goods_sold":["giá vốn hàng bán","giá vốn hàng bán và dịch vụ cung cấp","cost of goods sold","cost of sales","gia von hang ban"],
"gross_profit":["lợi nhuận gộp về bán hàng và cung cấp dịch vụ","lợi nhuận gộp","gross profit","loi nhuan gop"],
"net_income":["lợi nhuận sau thuế thu nhập doanh nghiệp","lợi nhuận sau thuế","profit after tax","net income","net profit","loi nhuan sau thue"],
"net_income_parent":["lợi nhuận sau thuế của cổ đông công ty mẹ","lợi nhuận sau thuế của công ty mẹ","lợi nhuận sau thuế thuộc về cổ đông công ty mẹ","profit attributable to owners of the parent","profit attributable to owners","loi nhuan sau thue cua cong ty me"],
"nci_profit":["lợi nhuận sau thuế của cổ đông không kiểm soát","lợi nhuận sau thuế của cổ đông không kiểm soát","profit attributable to non-controlling interests","non-controlling interests","loi nhuan sau thue cua co dong khong kiem soat"],
"operating_profit":["lợi nhuận thuần từ hoạt động kinh doanh","operating profit","operating income","profit from operations","loi nhuan thuan tu hoat dong kinh doanh"],
"cash_flow":["lưu chuyển tiền thuần từ hoạt động kinh doanh","lưu chuyển tiền từ hoạt động kinh doanh","net cash from operating activities","cash flow from operating activities","luu chuyen tien thuan tu hoat dong kinh doanh"],
"assets":["tổng cộng tài sản","tổng tài sản","tong cong tai san","tong cgng tai san","total assets"],
"total_sources":["tổng cộng nguồn vốn","tổng cộng nguồn vốn (440=300+400)","total liabilities and equity","total sources"],
"equity":["tổng cộng nguồn vốn chủ sở hữu","tổng cộng vốn chủ sở hữu","vốn chủ sở hữu","nguồn vốn chủ sở hữu","nguon von chu so huu","nguon von chu so huu","total equity","shareholders equity"],
"total_liabilities":["nợ phải trả","no phai tra","nq phai tra","total liabilities"],"current_assets":["tài sản ngắn hạn","current assets"],
"receivables":["các khoản phải thu ngắn hạn","phải thu ngắn hạn của khách hàng","accounts receivable","trade receivables"],
"ppe":["tài sản cố định hữu hình","tài sản cố định","property, plant and equipment"],"current_liabilities":["nợ ngắn hạn","current liabilities"],
"short_term_debt":["vay và nợ thuê tài chính ngắn hạn","vay và nv thuê tài chính ngắn hạn","vay ngắn hạn","vay ngan han","short-term borrowings","current borrowings"],
"long_term_debt":["vay và nợ thuê tài chính dài hạn","vay và nq thu tài chính dài hạn","vay dài hạn","vay dai han","long-term borrowings","non-current borrowings"],
"depreciation":["khấu hao tài sản cố định và bất động sản đầu tư","khấu hao tài sản cố định","depreciation of property, plant and equipment","depreciation","khấu hao"],
"selling_expense":["chi phí bán hàng","selling expenses","selling expense"],"admin_expense":["chi phí quản lý doanh nghiệp","general and administrative expenses","administrative expenses"],
}
TOKEN_RE=re.compile(r"[\(\[]?-?\d[\d.,]*[\)\]}]?")

EXPECTED_CODES={
"gross_revenue":{"01"}, "revenue_reductions":{"02"}, "revenue":{"10"},
"cost_of_goods_sold":{"11"}, "gross_profit":{"20"}, "operating_profit":{"30"},
"net_income":{"60"}, "net_income_parent":{"61"}, "nci_profit":{"62"},
"assets":{"280"}, "total_liabilities":{"300"}, "equity":{"400"}, "total_sources":{"440"},
"current_assets":{"100"}, "current_liabilities":{"310"},
"short_term_debt":{"321"}, "long_term_debt":{"339"},
"cash_flow":{"20"},
}
CODE_REQUIRED={"gross_revenue","revenue_reductions","revenue","gross_profit","operating_profit","net_income","net_income_parent","nci_profit","assets","total_liabilities","equity","total_sources","current_assets","current_liabilities","short_term_debt","long_term_debt"}

INCOME_START=["báo cáo kết quả hoạt động kinh doanh","bao cao ket qua hoat dong kinh doanh","statement of income","income statement"]
BALANCE_START=["bảng cân đối kế toán","bang can doi ke toan","balance sheet"]
CASHFLOW_START=["báo cáo lưu chuyển tiền tệ","bao cao luu chuyen tien te","cash flow statement"]
SECTION_MARKERS=INCOME_START+BALANCE_START+CASHFLOW_START+[
    "thuyết minh báo cáo tài chính","thuyet minh bao cao tai chinh","notes to the financial statements",
    "báo cáo tài chính hợp nhất","bao cao tai chinh hop nhat","báo cáo tài chính riêng","bao cao tai chinh rieng"
]


def _compact(text): return re.sub(r"\s+"," ",text or "")


def _norm(text):
    text=unicodedata.normalize("NFKD",text or "")
    text=text.replace("đ","d").replace("Đ","D")
    text="".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+"," ",text).strip().lower()


def _norm_with_map(text):
    normalized_chars=[]
    raw_indices=[]
    last_was_space=False
    for idx,ch in enumerate(text or ""):
        piece=unicodedata.normalize("NFKD",ch).replace("đ","d").replace("Đ","D")
        piece="".join(c for c in piece if not unicodedata.combining(c)).lower()
        if not piece:
            continue
        for out in piece:
            if out.isspace():
                if last_was_space:
                    continue
                out=" "
                last_was_space=True
            else:
                last_was_space=False
            normalized_chars.append(out)
            raw_indices.append(idx)
    while normalized_chars and normalized_chars[0]==" ":
        normalized_chars.pop(0); raw_indices.pop(0)
    while normalized_chars and normalized_chars[-1]==" ":
        normalized_chars.pop(); raw_indices.pop()
    return "".join(normalized_chars), raw_indices


def _raw_slice_for_norm(text, norm_pos, norm_len):
    normalized,mapping=_norm_with_map(text)
    if norm_pos<0 or norm_pos>=len(mapping): return len(text),len(text)
    raw_start=mapping[norm_pos]
    end_norm=min(len(mapping)-1,norm_pos+max(1,norm_len)-1)
    raw_end=mapping[end_norm]+1
    return raw_start,raw_end


def _parse_number(token):
    token=str(token).strip().replace(" ","")
    if not token: return None
    negative=(token.startswith(("(","[","{")) and any(ch in token[1:] for ch in ")]}")) or token.startswith("-")
    token=token.strip("()[]{}")
    token=token.replace("₫","")
    if not re.search(r"\d",token): return None
    # OCR/financial statements commonly use either 13.810.340.987 or 13,810,340.987.
    # Interpret separators using the last separator as decimal only when it has 1-2 digits.
    try:
        dot_count=token.count("."); comma_count=token.count(",")
        if dot_count+comma_count >= 2:
            value=float(token.replace(",","").replace(".",""))
        elif "," in token:
            parts=token.split(",")
            value=float(token.replace(",","")) if len(parts[-1])==3 else float(token.replace(",","."))
        elif "." in token:
            parts=token.split(".")
            value=float(token.replace(".","")) if len(parts[-1])==3 else float(token)
        else:
            value=float(re.sub(r"\D","",token))
    except ValueError:
        return None
    else:
        value=float(re.sub(r"\D","",token))
    return -value if negative else value


def _is_financial_token(token):
    digits=re.sub(r"\D","",token)
    return len(digits)>=5


def _compact_norm(text):
    return re.sub(r"[^a-z0-9]", "", _norm(text))


def _label_match_position(block, label):
    normalized,mapping=_norm_with_map(block)
    wanted=_norm(label)
    pos=normalized.find(wanted)
    if pos>=0: return pos,mapping
    compact=_compact_norm(block); compact_wanted=_compact_norm(label)
    cpos=compact.find(compact_wanted) if compact_wanted else -1
    if cpos<0: return -1,mapping
    # Best-effort mapping from compact position back to raw block position.
    seen=0
    for idx,ch in enumerate(normalized):
        if ch==" ": continue
        if seen==cpos: return idx,mapping
        seen+=1
    return -1,mapping


def _fuzzy_label_pos(block, label):
    """Return the raw line offset of a likely OCR-damaged accounting label.

    The matcher is deliberately row-local and number-insensitive. It compares only
    a few short windows near the beginning of the textual row, which is both faster
    and safer than fuzzy-matching a multi-row neighborhood.
    """
    target=_compact_norm(label)
    if not target:
        return -1
    target_len=len(target)
    best=(-1,0.0)
    offset=0
    for line in (block or '').splitlines():
        clean=_compact_norm(re.sub(r"\d[\d.,]*", " ", line))
        if not clean:
            offset += len(line)+1
            continue
        if target in clean:
            return offset
        candidates=[]
        # Most Vietnamese accounting rows start with the label immediately after
        # a row code, so prefix windows are highly effective for OCR mutations.
        for extra in (-2,0,2,4,8,14):
            end=min(len(clean), max(1,target_len+extra))
            if end>0:
                candidates.append(clean[:end])
        score=max((SequenceMatcher(None,c,target).ratio() for c in candidates if c),default=0.0)
        if score>best[1]: best=(offset,score)
        offset += len(line)+1
    # Short labels need a slightly higher threshold because accidental short-word
    # matches are more common; long statement labels can tolerate more OCR noise.
    threshold=0.78 if target_len>=18 else 0.88
    return best[0] if best[1]>=threshold else -1

def _section(text, starts, expected_labels=None, target_period=None):
    """Select the strongest occurrence of a statement heading.

    Financial PDFs often repeat headings in a table of contents, audit report, and
    actual statement. Choosing the first occurrence can point extraction at the TOC.
    Score each heading by the density of expected accounting labels/numeric rows in
    the following lines and select the best candidate.
    """
    lines=(text or "").splitlines()
    expected_labels=expected_labels or []
    expected=[_norm(x) for x in expected_labels]
    expected_compact=[_compact_norm(x) for x in expected_labels]
    starts_norm=[_norm(x) for x in starts]
    starts_compact=[_compact_norm(x) for x in starts]
    candidates=[]
    for i,line in enumerate(lines):
        norm=_norm(line); compact=_compact_norm(line)
        matched=any(w and (w in norm or cw in compact) for w,cw in zip(starts_norm,starts_compact))
        if not matched:
            matched=any(_fuzzy_label_pos(line, marker) >= 0 for marker in starts)
        if not matched: continue
        window="\n".join(lines[i:min(len(lines),i+110)])
        wnorm=_norm(window); wcompact=_compact_norm(window)
        label_hits=sum(1 for w,cw in zip(expected,expected_compact) if (w and w in wnorm) or (cw and cw in wcompact))
        numeric_tokens=len(_row_values(window))
        title_bonus=4 if any(x in norm for x in ["bang", "bao cao", "statement"]) else 0
        period_bonus=0
        period_penalty=0
        if target_period:
            d=target_period
            target_variants=[
                f"{d.day:02d}/{d.month:02d}/{d.year}",
                f"{d.day} thang {d.month} nam {d.year}",
                f"ngay {d.day} thang {d.month} nam {d.year}",
                f"den {d.day} thang {d.month} nam {d.year}",
            ]
            if any(_compact_norm(v) in wcompact for v in target_variants): period_bonus=30
            # Sections explicitly talking about another reporting date are weaker.
            other_dates=re.findall(r"20\d{2}", wnorm)
            if other_dates and str(d.year) not in other_dates: period_penalty=10
        candidates.append((label_hits*12 + min(numeric_tokens,18) + title_bonus + period_bonus - period_penalty, i))
    if not candidates: return ""
    _,start_idx=max(candidates,key=lambda x:x[0])
    end_idx=len(lines)
    markers=[(_norm(x),_compact_norm(x)) for x in SECTION_MARKERS]
    start_keys=set(starts_norm + starts_compact)
    for i in range(start_idx+1,len(lines)):
        norm=_norm(lines[i]); compact=_compact_norm(lines[i])
        same_section=any((w and w in norm) or (cw and cw in compact) for w,cw in zip(starts_norm,starts_compact))
        if same_section:
            continue
        if any((w and w in norm) or (cw and cw in compact) for w,cw in markers):
            end_idx=i
            break
    return "\n".join(lines[start_idx:end_idx])

def _unit_scale(text):
    low=_norm(text)
    if "tỷ đồng" in low or "ty dong" in low: return 1_000_000_000.0
    if "triệu đồng" in low or "trieu dong" in low: return 1_000_000.0
    if "nghìn đồng" in low or "nghin dong" in low: return 1_000.0
    return 1.0


def _candidate_spans(text,label):
    """Yield evidence windows anchored to the row containing *label*.

    Exact/compact matches are preferred. Fuzzy matching is only attempted on an
    individual line, and the evidence window begins at that line so values from
    adjacent rows cannot be mistaken for the matched metric.
    """
    lines=(text or '').splitlines()
    wanted=_norm(label); wanted_compact=_compact_norm(label)
    for i,line in enumerate(lines):
        norm_line=_norm(line); compact_line=_compact_norm(line)
        matched=False
        if wanted and wanted in norm_line:
            matched=True
        elif wanted_compact and wanted_compact in compact_line:
            matched=True
        else:
            pos=_fuzzy_label_pos(line,label)
            matched=pos>=0
        if not matched and i+1 < len(lines):
            # Some OCR/PDF text extraction splits the accounting label over two
            # physical lines (for example CMG's gross-profit and operating-profit
            # rows). Match the combined label conservatively, but keep the evidence
            # window anchored at the first line so the following row is not stolen.
            two=' '.join(lines[i:i+2])
            if (wanted and wanted in _norm(two)) or (wanted_compact and wanted_compact in _compact_norm(two)):
                matched=True
            elif _fuzzy_label_pos(two,label) >= 0:
                matched=True
        if not matched:
            continue
        # Include one continuation line only when the first line has too few
        # financial values. This accommodates wrapped labels without swallowing
        # the next accounting row.
        window=line
        # If a label spans two visual lines, preserve the continuation even when
        # the number columns already sit on the first OCR line. This is common in
        # B02a-DN/HN statements (e.g. "Doanh thu thuần ... / cung cấp dịch vụ").
        two = ' '.join(lines[i:i+2]) if i+1 < len(lines) else line
        exact_on_line = (wanted and wanted in norm_line) or (wanted_compact and wanted_compact in compact_line)
        label_spans_two = (wanted and wanted in _norm(two)) or (wanted_compact and wanted_compact in _compact_norm(two))
        if label_spans_two and not exact_on_line and i+1 < len(lines):
            window += '\n' + lines[i+1]
        elif len(_row_values(window)) < 2 and i+1 < len(lines):
            window += '\n' + lines[i+1]
        if len(_row_values(window)) < 2 and i+2 < len(lines):
            window += '\n' + lines[i+2]
        yield window[:700]


def _row_values(span, scale=1.0):
    # Repair common OCR/PDF extraction splits inside one number. Examples:
    # 2/785.227.684.465 -> 2.785.227.684.465; 2..323.260... -> 2.323.260...
    repaired=str(span or "")
    repaired=re.sub(r"(?<=\d)[/|I]\s*(?=\d{3}(?:[.,]\d{3})+)", ".", repaired)
    repaired=re.sub(r"(?<=\d)[.]{2,}(?=\d{3}[.,])", ".", repaired)
    vals=[]
    for token in TOKEN_RE.findall(repaired):
        if not _is_financial_token(token): continue
        value=_parse_number(token)
        if value is not None: vals.append(value*scale)
    # Remove obvious dates and years accidentally captured by OCR windows.
    filtered=[]
    for value in vals:
        if 1900 <= value <= 2100: continue
        filtered.append(value)
    return filtered[:6]


def _extract_by_code(section, codes, *, scale=None, label_hint=None, min_values=1):
    """Extract a financial row using an accounting code before the first large number.

    Restricting the code search to tokens before the first financial value avoids
    accidental matches against note numbers appearing later in the same row.
    """
    if not section:
        return None
    wanted_codes={str(c).lstrip("0") or "0" for c in codes}
    candidates=[]
    lines=(section or '').splitlines()
    for i,line in enumerate(lines):
        for span in (line, (line+'\n'+lines[i+1]) if i+1 < len(lines) else line):
            stripped=span.strip()
            tokens=stripped.split()
            if not tokens:
                continue
            # Accounting identity labels such as 440=300+400 are not financial values.
            def _looks_like_value(tok):
                if re.search(r"[=+]", tok) and not re.search(r"[.,]\d", tok):
                    return False
                return _is_financial_token(tok)
            first_fin_idx=None
            for j,tok in enumerate(tokens):
                if _looks_like_value(tok):
                    first_fin_idx=j
                    break
            if first_fin_idx is None:
                continue
            code_match=False
            for tok in tokens[:min(first_fin_idx+2,10)]:
                digits=re.sub(r"\D", "", tok)
                # Support fused identity tokens like "440=300+400".
                for code in wanted_codes:
                    # A code token is normally short ("321", "440"). Do not let a
                    # financial value such as "321.863.252.391" masquerade as code 321.
                    if re.fullmatch(rf"\D*{re.escape(code)}\D*", tok):
                        code_match=True
                        break
                    # Special accounting identity token such as "440=300+400".
                    if code in wanted_codes and re.search(rf"(?:^|\D){re.escape(code)}(?:=|\D)", tok) and re.search(r"[=+]", tok):
                        code_match=True
                        break
                if code_match: break
            if not code_match:
                continue
            vals=_row_values(span, _unit_scale(span) if scale is None else scale)
            if len(vals)<min_values:
                continue
            score=50
            if tokens and re.sub(r"\D", "", tokens[0]).lstrip("0") in wanted_codes:
                score+=25
            if label_hint:
                compact=_compact_norm(span); target=_compact_norm(label_hint)
                if target and target in compact:
                    score+=45
                elif target:
                    sim=SequenceMatcher(None, compact[:max(len(target),12)], target).ratio()
                    if sim < 0.50:
                        continue
                    score+=int(25*sim)
            candidates.append((score, vals, span))
    return max(candidates,key=lambda x:x[0]) if candidates else None

def _extract_strict_row(section, labels, *, scale=None, min_values=1):
    """Find a row where the primary accounting label is present on the same visual line.

    This prevents section headings such as "Lưu chuyển tiền từ hoạt động kinh doanh"
    from being mistaken for the net cash-flow row.
    """
    if not section: return None
    candidates=[]
    for i,line in enumerate((section or '').splitlines()):
        norm_line=_norm(line); compact_line=_compact_norm(line)
        for label in labels:
            wanted=_norm(label); wanted_compact=_compact_norm(label)
            if not ((wanted and wanted in norm_line) or (wanted_compact and wanted_compact in compact_line)):
                continue
            vals=_row_values(line, _unit_scale(line) if scale is None else scale)
            if len(vals)<min_values:
                continue
            score=100 if wanted and wanted in norm_line else 80
            # Prefer rows that actually look like a reported total line.
            if 'thuần' in norm_line or 'thuan' in norm_line: score += 15
            if re.search(r"\b20\b", line): score += 5
            candidates.append((score, vals, line))
    return max(candidates,key=lambda x:x[0]) if candidates else None

def _extract_metric_from_section(section, labels, *, scale=None, metric=None):
    if not section: return None
    best=None
    for label in labels:
        for span in _candidate_spans(section,label):
            candidate_scale=_unit_scale(span) if scale is None else scale
            vals=_row_values(span,candidate_scale)
            if len(vals)<2: continue
            score=0.0
            norm_label=_norm(label)
            lines_span=span.splitlines()
            first_line=_norm(lines_span[0]) if lines_span else ""
            norm_section=_norm(span)
            if norm_label and norm_label in first_line:
                score+=60
            elif norm_label and norm_label in norm_section:
                score+=25
            # A fuzzy/combined match is useful for wrapped labels, but an exact
            # label on the same row should always outrank a neighboring-row match.
            if len(vals)>=4: score+=15
            # Row codes are corroborating evidence. They are powerful when present on
            # the same line as the label, but labels/section context still remain primary.
            codes=EXPECTED_CODES.get(metric or "", set())
            if codes:
                first=lines_span[0].strip().split()[0] if lines_span and lines_span[0].strip() else ""
                first_digits=re.sub(r"\D", "", first)
                norm_label=_norm(label)
                # OCR may render 01 as 1, 10 as I0, etc.; accept exact digit codes or
                # a code token immediately before the label. An exact accounting label
                # is allowed to override a corrupted row code (e.g. PNJ's row 10 OCR'd as 40).
                code_match=False
                if first_digits and first_digits in {c.lstrip("0") or "0" for c in codes}:
                    score+=35; code_match=True
                elif any(re.search(rf"(?:^|\s){re.escape(c)}(?:\s|$)", lines_span[0] if lines_span else "") for c in codes):
                    score+=30; code_match=True
                exact_label_on_first=(norm_label and norm_label in first_line)
                if metric in CODE_REQUIRED and not code_match and not exact_label_on_first:
                    continue
            if best is None or score>best[0]: best=(score,vals,span)
    return best


def _extract_metric_raw_safe(text, labels, *, metric=None, min_values=1):
    """Strict raw-text fallback for reports whose section heading is OCR-damaged.

    Only exact/compact label matches on a single row (or a wrapped two-line label) are
    considered. Numeric code-only matches are delegated to _extract_by_code so a note
    reference cannot masquerade as a financial row.
    """
    candidates=[]
    lines=(text or '').splitlines()
    for label in labels:
        wanted=_norm(label); compact_wanted=_compact_norm(label)
        for i,line in enumerate(lines):
            line_norm=_norm(line); line_comp=_compact_norm(line)
            matched=(wanted and wanted in line_norm) or (compact_wanted and compact_wanted in line_comp)
            span=line
            if not matched and i+1 < len(lines):
                two=line+'\n'+lines[i+1]
                two_norm=_norm(two); two_comp=_compact_norm(two)
                matched=(wanted and wanted in two_norm) or (compact_wanted and compact_wanted in two_comp)
                if matched: span=two
            if not matched:
                continue
            vals=_row_values(span,_unit_scale(span))
            if len(vals)<min_values:
                continue
            score=100 if wanted and wanted in line_norm else 90
            codes=EXPECTED_CODES.get(metric or '',set())
            if codes:
                first_digits=re.sub(r'\D','',line.strip().split()[0]) if line.strip().split() else ''
                if first_digits and first_digits.lstrip('0') in {c.lstrip('0') for c in codes}:
                    score+=35
            candidates.append((score,vals,span))
    return max(candidates,key=lambda x:x[0]) if candidates else None


def _sanitise_comparison(metric, current, comparison, period_end):
    """Reject a value that is very likely an H1/YTD column rather than the same-period comparator."""
    if comparison is None or current in (None,0):
        return comparison
    ratio=abs(float(comparison)/float(current))
    # For quarterly revenue/financial statement rows, a same-quarter comparator
    # should not silently become a 2-4x YTD amount. Keep wider tolerance for profit
    # lines because losses/turnarounds can legitimately be extreme.
    if metric in {"gross_revenue","revenue_reductions","revenue","cost_of_goods_sold","gross_profit","selling_expense","admin_expense","short_term_debt","long_term_debt","assets","equity","total_liabilities"}:
        if period_end and getattr(period_end,'month',None) in {6,9,12} and not (0.45 <= ratio <= 1.8):
            return None
    return comparison

def _append(result,metric,value,unit="absolute",confidence=0.78,source="statement",comparison_value=None):
    if value is not None:
        result.append((metric,float(value),unit,float(confidence),source,None if comparison_value is None else float(comparison_value)))


def _find_percent(text,labels):
    low=_norm(text)
    for label in labels:
        idx=low.find(_norm(label))
        if idx<0: continue
        m=re.search(r"(-?\d+(?:[.,]\d+)?)\s*%",text[idx:idx+220])
        if m: return float(m.group(1).replace(",","."))
    return None


def _adjusted_revenue_comparison(text):
    norm=_norm(text)
    anchors=[
        "dieu chinh lai so lieu cung ky",
        "dieu chinh lai so lieu",
        "cai nhin tuong dong",
        "cùng một phương pháp kế toán",
        "cung mot phuong phap ke toan",
    ]
    anchor_pos=-1
    for anchor in anchors:
        pos=norm.find(_norm(anchor))
        if pos>=0:
            anchor_pos=pos; break
    if anchor_pos<0: return None,None,None,None
    raw_anchor,_=_raw_slice_for_norm(text,anchor_pos,len(_norm(anchors[0])))
    tail=text[raw_anchor:raw_anchor+2400]
    low=_norm(tail); pos=low.find("doanh thu thuan")
    if pos<0: pos=low.find("doanh thu thun")
    if pos<0: return None,None,None,None
    raw_pos,_=_raw_slice_for_norm(tail,pos,len("doanh thu thuan"))
    line=tail[raw_pos:raw_pos+650]
    tokens=[t for t in TOKEN_RE.findall(line) if _is_financial_token(t)]
    vals=[_parse_number(t) for t in tokens]
    vals=[v for v in vals if v is not None]
    if len(vals)<2: return None,None,None,None
    scale=_unit_scale(tail)
    vals=[v*scale for v in vals]
    # The adjusted comparison table is expected to be:
    # current quarter, prior-year comparable quarter, delta, %, current YTD, prior-year YTD, ...
    if len(vals)>=6:
        return vals[0],vals[1],vals[4],vals[5]
    return vals[0],vals[1],None,None


def _quality(values,scope,text):
    warnings=[]
    score=35
    required=["revenue","gross_profit","operating_profit","net_income"]
    present=sum(1 for x in required if x in values)
    score += present*12
    if "assets" in values: score+=7
    if "cash_flow" in values: score+=5
    if "depreciation" in values: score+=5
    if scope=="consolidated": score+=8
    elif scope=="unknown": warnings.append("Statement scope could not be confirmed as consolidated.")
    else: warnings.append("Separate financial statement detected; core analytics require consolidated statements.")
    # Accounting identity checks are strong evidence that row alignment worked.
    gr,red,rev,gp=values.get("gross_revenue"),values.get("revenue_reductions"),values.get("revenue"),values.get("gross_profit")
    if gr is not None and red is not None and rev is not None:
        if abs((gr-red)-rev)/max(abs(rev),1)<0.002:
            score+=8
        else:
            if values.get("revenue_reported_ocr") is not None and abs((gr-red)-rev)/max(abs(rev),1)<0.002:
                score+=4
            else:
                warnings.append("Revenue reconciliation failed.")
                score-=10
    assets,liab,equity=values.get("assets"),values.get("total_liabilities"),values.get("equity")
    if assets is not None and liab is not None and equity is not None:
        if abs(assets-(liab+equity))/max(abs(assets),1)<0.01: score+=7
        else: warnings.append("Balance-sheet identity did not reconcile within tolerance.")
    if len(text.strip())<1000: warnings.append("Source text/OCR is sparse."); score-=15
    score=max(0,min(100,score))
    core_ok=all(k in values for k in ("revenue","gross_profit","operating_profit","net_income"))
    status="verified" if score>=80 and core_ok and not any("failed" in w.lower() for w in warnings) else "review" if score>=50 else "failed"
    return score,status,warnings


def extract(text,path):
    raw=text or ""
    year=infer_year(path,raw); period_end=infer_period_end(raw,path); scope=infer_scope(path,raw)
    result=[]; values={}; comps={}
    income=_section(raw,INCOME_START,[x for x,_ in [("gross_revenue",0),("revenue_reductions",0),("revenue",0),("gross_profit",0),("operating_profit",0),("net_income",0),("net_income_parent",0),("nci_profit",0),("selling_expense",0),("admin_expense",0)] for x in [*LABELS[x]]], target_period=period_end) or raw
    balance=_section(raw,BALANCE_START,[*LABELS["assets"],*LABELS["total_liabilities"],*LABELS["equity"],*LABELS["current_assets"],*LABELS["current_liabilities"],*LABELS["short_term_debt"],*LABELS["long_term_debt"]], target_period=period_end) or raw
    cashflow=_section(raw,CASHFLOW_START,[*LABELS["cash_flow"],*LABELS["depreciation"]], target_period=period_end) or raw

    income_metrics=[
        ("gross_revenue",0.94), ("revenue_reductions",0.90), ("revenue",0.96),
        ("cost_of_goods_sold",0.92), ("gross_profit",0.93),("operating_profit",0.93),("net_income_parent",0.95),("nci_profit",0.92),("net_income",0.94),
        ("selling_expense",0.88),("admin_expense",0.88),
    ]
    qmonth=period_end.month if period_end else None
    for metric,base_conf in income_metrics:
        found=_extract_metric_from_section(income,LABELS[metric],metric=metric)
        if not found:
            found=_extract_metric_raw_safe(raw,LABELS[metric],metric=metric)
        # Parent-attributable profit and NCI are particularly important for
        # consolidated groups. OCR sometimes mangles the long Vietnamese labels,
        # but the statutory row codes 61/62 remain readable. Rescue those rows
        # directly before falling back to total consolidated profit.
        if not found and metric in {"net_income_parent","nci_profit"} and path is not None:
            code = {"net_income_parent":"61","nci_profit":"62"}[metric]
            found=_extract_by_code(income, {code}, label_hint=None, min_values=1) or _extract_by_code(raw, {code}, label_hint=None, min_values=1)
        if not found: continue
        _,vals,evidence=found
        if metric=="revenue_reductions":
            vals=[abs(v) for v in vals]
        values[metric]=vals[0]
        comps[metric]=_sanitise_comparison(metric, vals[0], vals[1] if len(vals)>1 else None, period_end)
        _append(result,metric,vals[0],confidence=base_conf,source="statement_label",comparison_value=comps[metric])
        # For Q1 the current quarter and YTD are identical. For Q2-Q4 the row usually
        # carries current/prior quarter followed by current/prior YTD columns.
        if metric in {"gross_revenue","revenue_reductions","revenue","gross_profit","operating_profit","net_income","net_income_parent","nci_profit","selling_expense","admin_expense"}:
            if len(vals)>=4 and qmonth and qmonth>=6:
                _append(result,metric+"_ytd",vals[2],confidence=base_conf-0.02,source="statement_ytd",comparison_value=vals[3])
            elif len(vals)>=2 and qmonth==3:
                _append(result,metric+"_ytd",vals[0],confidence=base_conf-0.02,source="statement_ytd",comparison_value=vals[1])

    # For company-level profitability, prefer profit attributable to owners of the parent.
    # Total consolidated net income includes non-controlling interests and can materially
    # distort Net Margin/ROE for groups such as FPT. Keep the total in net_income_total.
    # Consolidated profit attribution: parent profit is the company-level input.
    # If total profit and NCI are both trustworthy and their implied parent is close
    # to the reported parent row, use that reconciliation. Otherwise retain the explicit
    # parent row because OCR often corrupts leading digits in total/NCI rows.
    parent_reported=values.get("net_income_parent")
    nci_reported=values.get("nci_profit")
    total_reported=values.get("net_income")
    parent_cmp=comps.get("net_income_parent")
    nci_cmp=comps.get("nci_profit")
    total_cmp=comps.get("net_income")
    if parent_reported is not None and total_reported is not None and nci_reported is not None:
        implied_parent=total_reported-nci_reported
        if abs(implied_parent-parent_reported)/max(abs(parent_reported),1)<=0.05:
            parent_reported=implied_parent
            values["net_income_parent"]=parent_reported
        values["net_income_total"]=parent_reported+nci_reported
    elif parent_reported is not None and nci_reported is not None:
        values["net_income_total"]=parent_reported+nci_reported
    elif total_reported is not None:
        values["net_income_total"]=total_reported
    if parent_reported is not None:
        values["net_income"]=parent_reported
        result=[x for x in result if x[0] not in {"net_income","net_income_total","net_income_ytd"}]
        if values.get("net_income_total") is not None:
            _append(result,"net_income_total",values["net_income_total"],confidence=0.97,source="reconciled_profit_attribution" if (nci_reported is not None) else "statement_total_profit",comparison_value=(parent_cmp+nci_cmp) if parent_cmp is not None and nci_cmp is not None else total_cmp)
        _append(result,"net_income",parent_reported,confidence=0.98,source="statement_parent_profit",comparison_value=parent_cmp)
    elif total_reported is not None:
        values["net_income"]=total_reported
        result=[x for x in result if x[0]!="net_income"]
        _append(result,"net_income_total",total_reported,confidence=0.94,source="statement_total_profit",comparison_value=total_cmp)
        _append(result,"net_income",total_reported,confidence=0.92,source="statement_total_profit",comparison_value=total_cmp)

    # Reconcile gross revenue - deductions = net revenue. When OCR corrupts a digit
    # in the net-revenue row, the accounting identity is stronger evidence than the
    # isolated OCR token. Accept the derived value when gross revenue is plausible and
    # the result is positive; retain a warning if it differed materially from the OCR row.
    if values.get("gross_revenue") is not None and values.get("revenue_reductions") is not None:
        reconciled=values["gross_revenue"]-values["revenue_reductions"]
        reported=values.get("revenue")
        if reconciled > 0:
            material_gap = reported is not None and abs(reconciled-reported)/max(abs(reconciled),1) >= 0.002
            values["revenue"]=reconciled
            result=[x for x in result if x[0] not in {"revenue","revenue_ytd"}]
            _append(result,"revenue",reconciled,confidence=0.98 if material_gap else 0.995,source="reconciled_income_statement",comparison_value=comps.get("revenue"))
            if material_gap:
                # Keep the original row as audit evidence without feeding it to analytics.
                values["revenue_reported_ocr"]=reported

    # Reconcile gross profit from the accounting identity when OCR damaged the
    # reported gross-profit number. The statement row itself remains evidence,
    # but the derived value is used when it reconciles exactly with revenue and
    # cost of goods sold.
    cogs=values.get("cost_of_goods_sold"); rev_value=values.get("revenue"); gp_reported=values.get("gross_profit")
    if rev_value is not None and cogs is not None:
        gp_derived=rev_value-abs(cogs)
        if gp_reported is None or abs(gp_reported-gp_derived)/max(abs(gp_derived),1)>0.01:
            values["gross_profit"]=gp_derived
            result=[x for x in result if x[0] not in {"gross_profit","gross_profit_ytd"}]
            _append(result,"gross_profit",gp_derived,confidence=0.95,source="reconciled_income_statement")

    adj_current,adj_prior,adj_ytd,adj_ytd_prior=_adjusted_revenue_comparison(raw)
    if adj_current is not None:
        # Keep the exact reported quarter revenue from the statement. The adjusted
        # comparison table is used only to improve the prior-year comparator.
        exact_current=values.get("revenue",adj_current)
        result=[x for x in result if x[0] not in {"revenue","revenue_ytd"}]
        values["revenue"]=exact_current; comps["revenue"]=adj_prior
        _append(result,"revenue",exact_current,confidence=0.99 if exact_current!=adj_current else 0.98,source="statement_with_adjusted_comparator",comparison_value=adj_prior)
        if adj_ytd is not None:
            _append(result,"revenue_ytd",adj_ytd,confidence=0.98,source="reported_comparable_ytd",comparison_value=adj_ytd_prior)

    balance_specs=["assets","total_liabilities","equity","total_sources","current_assets","current_liabilities","short_term_debt","long_term_debt","ppe","receivables"]
    for metric in balance_specs:
        code_map={"assets":{"280"},"total_liabilities":{"300"},"equity":{"400"},"total_sources":{"440"},"current_assets":{"100"},"current_liabilities":{"310"},"short_term_debt":{"321"},"long_term_debt":{"339"}}
        found=None
        if metric in code_map:
            # Formal balance-sheet totals are safest when selected by their accounting
            # code alone. Generic labels such as "nợ phải trả" and "vốn chủ sở hữu"
            # also occur in notes and accounting-policy text.
            found=_extract_by_code(balance, code_map[metric], label_hint=None, min_values=1)
            if not found:
                found=_extract_by_code(raw, code_map[metric], label_hint=None, min_values=1)
        if not found:
            found=_extract_metric_from_section(balance,LABELS[metric],metric=metric)
        if not found and metric in code_map and metric in {"assets","total_liabilities","equity","total_sources","current_assets","current_liabilities","short_term_debt","long_term_debt"}:
            found=_extract_by_code(balance, code_map[metric], label_hint=None, min_values=1) or _extract_by_code(raw, code_map[metric], label_hint=None, min_values=1)
        # Do not fall back to generic-label search for the balance-sheet totals: labels
        # such as "nợ phải trả" and "vốn chủ sở hữu" occur frequently in notes.
        if not found and metric not in {"assets","total_liabilities","equity","total_sources"}:
            found=_extract_metric_raw_safe(raw,LABELS[metric],metric=metric,min_values=1)
        if not found: continue
        _,vals,_=found
        values[metric]=vals[0]; comps[metric]=_sanitise_comparison(metric, vals[0], vals[1] if len(vals)>1 else None, period_end)
        _append(result,metric,vals[0],confidence=0.90 if metric in {"assets","equity","total_liabilities"} else 0.86,source="statement_label",comparison_value=comps[metric])

    for metric,conf in (("cash_flow",0.96),("depreciation",0.94)):
        if metric=="cash_flow":
            found=_extract_strict_row(cashflow,["lưu chuyển tiền thuần từ hoạt động kinh doanh","net cash from operating activities","cash flow from operating activities"],min_values=1)
            if not found:
                found=_extract_metric_raw_safe(cashflow,LABELS[metric],metric=metric,min_values=1)
            if not found:
                found=_extract_by_code(cashflow,{"20"},label_hint="lưu chuyển tiền thuần từ hoạt động kinh doanh",min_values=1)
            if not found:
                found=_extract_metric_raw_safe(raw,LABELS[metric],metric=metric,min_values=1)
        else:
            found=_extract_metric_from_section(cashflow,LABELS[metric],metric=metric)
        if not found: continue
        _,vals,_=found
        values[metric]=vals[0]; comps[metric]=_sanitise_comparison(metric, vals[0], vals[1] if len(vals)>1 else None, period_end)
        # If the cash-flow table explicitly labels a standalone quarter column,
        # the first extracted value is already quarter-specific.  Keep that fact in
        # source_type so the analysis layer will not subtract an unrelated prior
        # annual/fiscal period.
        probe=_norm(cashflow[:4000])
        has_quarter_column=bool(re.search(r"qu[ýy]\s*[1-4]|quarter\s*[1-4]|q[1-4]\s*20\d{2}",probe,re.I))
        cash_source="statement_cashflow_quarter" if has_quarter_column else "statement_cashflow_ytd"
        _append(result,metric,vals[0],confidence=conf,source=cash_source,comparison_value=comps[metric])

    if values.get("short_term_debt") is not None or values.get("long_term_debt") is not None:
        prior=(comps.get("short_term_debt") or 0)+(comps.get("long_term_debt") or 0)
        _append(result,"debt",(values.get("short_term_debt") or 0)+(values.get("long_term_debt") or 0),confidence=0.90,source="derived",comparison_value=prior or None)
    # Balance-sheet identity reconciliation. The formal total-sources row 440 is a
    # powerful anchor when OCR corrupts one of the 280/300/400 totals. Prefer the
    # combination that satisfies: Assets = Liabilities + Equity = Total sources.
    total_sources=values.get("total_sources")
    if total_sources is not None:
        assets=values.get("assets"); liab=values.get("total_liabilities"); equity=values.get("equity")
        if assets is None or abs(assets-total_sources)/max(abs(total_sources),1)>0.005:
            if assets is not None: values["assets_reported_ocr"]=assets
            values["assets"]=total_sources
            result=[x for x in result if x[0]!="assets"]
            _append(result,"assets",total_sources,confidence=0.97,source="reconciled_balance_sheet",comparison_value=comps.get("total_sources"))
        if equity is not None and liab is not None:
            implied_liab=total_sources-equity
            if implied_liab>0 and abs(liab-implied_liab)/max(abs(implied_liab),1)>0.005:
                values["total_liabilities_reported_ocr"]=liab
                values["total_liabilities"]=implied_liab
                result=[x for x in result if x[0]!="total_liabilities"]
                _append(result,"total_liabilities",implied_liab,confidence=0.97,source="reconciled_balance_sheet",comparison_value=(comps.get("total_sources")-comps.get("equity")) if comps.get("total_sources") is not None and comps.get("equity") is not None else comps.get("total_liabilities"))
        elif liab is not None and equity is None:
            implied_equity=total_sources-liab
            if implied_equity>=0:
                values["equity"]=implied_equity
                result=[x for x in result if x[0]!="equity"]
                _append(result,"equity",implied_equity,confidence=0.94,source="reconciled_balance_sheet",comparison_value=None)
        elif equity is not None and liab is None:
            implied_liab=total_sources-equity
            if implied_liab>=0:
                values["total_liabilities"]=implied_liab
                result=[x for x in result if x[0]!="total_liabilities"]
                _append(result,"total_liabilities",implied_liab,confidence=0.94,source="reconciled_balance_sheet",comparison_value=None)
    if values.get("equity") is None and values.get("assets") is not None and values.get("total_liabilities") is not None:
        prior_equity=None
        if comps.get("assets") is not None and comps.get("total_liabilities") is not None: prior_equity=comps["assets"]-comps["total_liabilities"]
        _append(result,"equity",values["assets"]-values["total_liabilities"],confidence=0.78,source="derived",comparison_value=prior_equity)
        values["equity"]=values["assets"]-values["total_liabilities"]
    elif values.get("equity") is not None and values.get("assets") is not None and values.get("total_liabilities") is not None:
        implied_equity=values["assets"]-values["total_liabilities"]
        if abs(values["equity"]-implied_equity)/max(abs(implied_equity),1)>0.000001:
            prior_equity=None
            if comps.get("assets") is not None and comps.get("total_liabilities") is not None: prior_equity=comps["assets"]-comps["total_liabilities"]
            # Prefer the explicit equity row when the total-sources identity is not
            # available. Only reconcile to the balance equation if the discrepancy is small.
            if abs(values["equity"]-implied_equity)/max(abs(implied_equity),1)<=0.005:
                values["equity"]=implied_equity
                result=[x for x in result if x[0]!="equity"]
                _append(result,"equity",implied_equity,confidence=0.96,source="reconciled_balance_sheet",comparison_value=prior_equity)
    if values.get("selling_expense") is not None or values.get("admin_expense") is not None:
        prior_sga=(comps.get("selling_expense") or 0)+(comps.get("admin_expense") or 0)
        _append(result,"sga",(values.get("selling_expense") or 0)+(values.get("admin_expense") or 0),confidence=0.86,source="derived",comparison_value=prior_sga or None)
        sga_ytd=None
        sell_ytd=next((x for x in result if x[0]=="selling_expense_ytd"),None); admin_ytd=next((x for x in result if x[0]=="admin_expense_ytd"),None)
        if sell_ytd or admin_ytd:
            sga_ytd=(sell_ytd[1] if sell_ytd else 0)+(admin_ytd[1] if admin_ytd else 0)
            comp=(sell_ytd[5] if sell_ytd and sell_ytd[5] is not None else 0)+(admin_ytd[5] if admin_ytd and admin_ytd[5] is not None else 0)
            _append(result,"sga_ytd",sga_ytd,confidence=0.84,source="derived_ytd",comparison_value=comp or None)

    roa=_find_percent(raw,["roa","return on assets","tỷ suất lợi nhuận trên tổng tài sản"])
    roe=_find_percent(raw,["roe","return on equity","tỷ suất lợi nhuận trên vốn chủ sở hữu"])
    if roa is not None: _append(result,"roa",roa,"percent",0.86,"reported_ratio")
    elif values.get("net_income") and values.get("assets"): _append(result,"roa",values["net_income"]/values["assets"]*100,"percent",0.72,"derived")
    if roe is not None: _append(result,"roe",roe,"percent",0.86,"reported_ratio")
    elif values.get("net_income") and values.get("equity"): _append(result,"roe",values["net_income"]/values["equity"]*100,"percent",0.72,"derived")

    quality_score,status,warnings=_quality(values,scope,raw)
    if not result: status="failed"; quality_score=0; warnings.append("No financial line items were extracted.")
    if not year: warnings.append("Could not determine reporting year.")
    return {
        "year":year,
        "period_end":period_end.isoformat() if period_end else None,
        "scope":scope,
        "observations":result,
        "quality_score":quality_score,
        "status":status,
        "warnings":warnings,
        "evidence_summary":{"metrics":sorted({x[0].replace("_ytd","") for x in result}),"observation_count":len(result)},
    }
