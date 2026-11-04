"""Chek tekshiruvi: OCR matnini tahlil qilish (sof funksiyalar) + OCR/dHash yordamchilari."""
import io, os, re
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo(os.getenv("TZ_NAME", "Asia/Tashkent"))
except Exception:
    TZ = timezone(timedelta(hours=5))  # tzdata yo'q bo'lsa Toshkent (UTC+5)
KW = re.compile(r"(so['’`ʻ]?m|сум|uzs|sum|summa|сумма|итого|amount)", re.I)
NUM = re.compile(r"\d{1,3}(?:[ \u00a0.,]\d{3})+(?:[.,]\d{1,2})?|\d{4,}(?:[.,]\d{1,2})?")  # >= 1000
CARD16 = re.compile(r"(?<!\d)(?:\d{4}[ -]?){3}\d{4}(?!\d)")
MASK = re.compile(r"[*•xX·]{2,}[ -]?(\d{4})(?!\d)")
DATE1 = re.compile(r"(?<!\d)(\d{1,2})[./](\d{1,2})[./](\d{4})(?!\d)")
DATE2 = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")
TIME = re.compile(r"(?<!\d)(\d{1,2}):(\d{2})(?::(\d{2}))?(?!\d)")
FAILS = {"duplicate_receipt", "amount_mismatch", "too_old", "future_date"}


def _num(m):
    m = m.replace("\u00a0", " ")
    d = re.search(r"[.,](\d{1,2})$", m)
    if d and not re.search(r"[.,]\d{3}$", m): m = m[:d.start()]
    return int(re.sub(r"\D", "", m) or 0)


def amounts(text):
    """(kalit so'z bor qatordagi sonlar, qolgan sonlar) — karta, sana va vaqt chiqarib tashlanadi."""
    for rx in (CARD16, MASK, DATE1, DATE2, TIME): text = rx.sub(" ", text)
    kw, other = [], []
    for line in text.splitlines():
        (kw if KW.search(line) else other).extend(_num(m) for m in NUM.findall(line))
    return kw, other


def found_dt(text):
    try:
        if m := DATE1.search(text): d = (int(m[3]), int(m[2]), int(m[1]))
        elif m := DATE2.search(text): d = (int(m[1]), int(m[2]), int(m[3]))
        else: return None
        tm = TIME.search(text)
        h, mi, s = (int(tm[1]), int(tm[2]), int(tm[3] or 0)) if tm else (23, 59, 59)
        return datetime(*d, h, mi, s, tzinfo=TZ)
    except ValueError:
        return None


def evaluate(text, amount, card_number, cfg, dup=False, now=None):
    """-> {verdict: pass|review|fail, reasons[], found{amount, card_last4, datetime}}"""
    now = now or datetime.now(TZ)
    if dup: return {"verdict": "fail", "reasons": ["duplicate_receipt"], "found": {}}
    if len(text.strip()) < 8: return {"verdict": "review", "reasons": ["low_quality"], "found": {}}
    reasons, found = [], {}
    kw, other = amounts(text)
    if kw:
        if amount in kw: found["amount"] = amount
        else: reasons.append("amount_mismatch"); found["amount"] = kw[0]
    elif amount in other: found["amount"] = amount
    else: reasons.append("amount_not_found")
    l4 = re.sub(r"\D", "", card_number or "")[-4:]
    seen = MASK.findall(text) + [re.sub(r"\D", "", m.group())[-4:] for m in CARD16.finditer(text)]
    if seen: found["card_last4"] = seen[0]
    if len(l4) == 4:
        if l4 in seen or re.search(rf"(?<!\d){l4}(?!\d)", text): pass
        elif seen: reasons.append("card_mismatch")
        elif cfg.get("require_card_match"): reasons.append("card_not_found")
    dt = found_dt(text)
    if not dt: reasons.append("date_not_found")
    else:
        found["datetime"] = dt.isoformat()
        age = (now - dt).total_seconds() / 60
        if age > cfg.get("max_age_minutes", 60): reasons.append("too_old")
        elif age < -10: reasons.append("future_date")
    verdict = "fail" if FAILS & set(reasons) else ("review" if reasons else "pass")
    return {"verdict": verdict, "reasons": reasons, "found": found}


def ocr_text(data):
    import pytesseract
    from PIL import Image
    img = Image.open(io.BytesIO(data)).convert("L")
    try: return pytesseract.image_to_string(img, lang="rus+eng", timeout=20)
    except pytesseract.TesseractError: return pytesseract.image_to_string(img, lang="eng", timeout=20)


def analyze(data, amount, card_number, cfg, dup=False):
    """Hech qachon istisno ko'tarmaydi: xato bo'lsa ocr_failed -> review."""
    if dup: return evaluate("", amount, card_number, cfg, True)
    try: return evaluate(ocr_text(data), amount, card_number, cfg)
    except Exception:
        return {"verdict": "review", "reasons": ["ocr_failed"], "found": {}}


def dhash(data):
    from PIL import Image
    px = list(Image.open(io.BytesIO(data)).convert("L").resize((9, 8)).getdata())
    bits = 0
    for r in range(8):
        for c in range(8): bits = (bits << 1) | (px[r * 9 + c] > px[r * 9 + c + 1])
    return f"{bits:016x}"


def hamming(a, b): return bin(int(a, 16) ^ int(b, 16)).count("1")
