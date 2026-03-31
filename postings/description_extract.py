"""
postings/description_extract.py — Extract pay and location data from job description text.

Used by ingest_job_posting() as a last-resort fallback when structured fields
(wage_min, raw_address) are absent from the scraped signal.  Only fires when
API-provided values are blank — structured fields always win.

Functions:
    extract_salary(text)  → (wage_min, wage_max, wage_period) or (None, None, None)
    extract_address(text) → (address, method) or None
"""

import html as _html_mod
import re


# ── Salary extraction ────────────────────────────────────────────────────────
#
# Handles formats found in real job descriptions:
#   "$50,000 - $70,000 a year"
#   "$25 an hour"
#   "$18 - $22 an hour"
#   "50K–65K a year"
#   "80,000 USD annually"
#   "Compensation: $120K+"

_SALARY_RE = re.compile(
    r'\$?([\d,]+(?:\.\d+)?[Kk]?)'                            # first number (optional K suffix)
    r'(?:\s*(?:[-–]|to)\s*\$?([\d,]+(?:\.\d+)?[Kk]?))?'     # optional second number (dash or "to")
    r'\s*(?:USD\s*)?(?:a\s+|an\s+|per\s+|/)?'
    r'(year|yr|annual|annually|month|week|wk|hour|hr)\b',     # period keyword (word-boundary: no "years", "weekly", etc.)
    re.IGNORECASE,
)

_PERIOD_MAP = {
    "year": "yearly", "yr": "yearly", "annual": "yearly", "annually": "yearly",
    "month": "monthly",
    "week": "weekly", "wk": "weekly",
    "hour": "hourly", "hr": "hourly",
}

# Plausible wage ranges — filter out false positives from experience
# requirements ("3-5 years"), schedule info ("40 hours per week"), etc.
_WAGE_SANITY: dict[str, tuple[float, float]] = {
    "hourly":  (7.0,    500.0),
    "weekly":  (290.0,  25000.0),
    "monthly": (1200.0, 100000.0),
    "yearly":  (10000.0, 3000000.0),
}


def _clean_num(n: str | None) -> float | None:
    if n is None:
        return None
    try:
        n = n.strip()
        multiplier = 1000 if n[-1:].lower() == "k" else 1
        return float(n.rstrip("Kk").replace(",", "")) * multiplier
    except (TypeError, ValueError):
        return None


def _strip_html(text: str) -> str:
    if "<" in text:
        text = re.sub(r"<[^>]+>", " ", text)
        text = _html_mod.unescape(text)
        text = re.sub(r"\s+", " ", text).strip()
    return text


def extract_salary(text: str) -> tuple[float | None, float | None, str | None]:
    """Parse a salary string from description text.

    Returns (wage_min, wage_max, wage_period) or (None, None, None).

    Examples:
        "$50,000 - $70,000 a year"   → (50000.0, 70000.0, "yearly")
        "$25 an hour"                → (25.0, None, "hourly")
        "50K–65K a year"             → (50000.0, 65000.0, "yearly")
        "no pay info here"           → (None, None, None)
    """
    if not text:
        return None, None, None
    text = _strip_html(text)
    # Try each match in order — first one that passes sanity wins
    for m in _SALARY_RE.finditer(text):
        wage_min = _clean_num(m.group(1))
        wage_max = _clean_num(m.group(2))
        raw_period = (m.group(3) or "").lower()
        wage_period = _PERIOD_MAP.get(raw_period)
        if not wage_period:
            continue
        lo, hi = _WAGE_SANITY.get(wage_period, (0.0, float("inf")))
        # Primary value must be in range; drop out-of-range max but keep min
        if wage_min is not None and not (lo <= wage_min <= hi):
            continue
        if wage_min is None and wage_max is None:
            continue
        if wage_max is not None and not (lo <= wage_max <= hi):
            wage_max = None
        return wage_min, wage_max, wage_period
    return None, None, None


# ── Address extraction ────────────────────────────────────────────────────────
#
# Two-pass extraction:
#   1. pyap  — structured US address parser, requires state abbreviation in text
#   2. regex — street-number + road-type pattern, no state required
#
# Length gates filter out sub-strings that are clearly not real addresses.

_ADDR_MIN_LEN = 15
_ADDR_MAX_LEN = 120

# Street number + named road type; guards against salary fragments and
# zero-prefixed numbers (e.g. "000 employees").
_STREET_RE = re.compile(
    r"(?<![,\d])\b[1-9]\d{2,5}\s+[A-Za-z][A-Za-z0-9\s]{1,40}"
    r"(?:Street\b|St\b|Avenue\b|Ave\b|Boulevard\b|Blvd\b|Road\b|Rd\b|Drive\b|Dr\b|"
    r"Lane\b|Ln\b|Parkway\b|Pkwy\b|Way\b|Court\b|Ct\b|Place\b|Pl\b|Circle\b|Cir\b)"
    r"[^<\n]{0,120}",
    re.IGNORECASE,
)


def extract_address(text: str) -> tuple[str, str] | None:
    """Find the first US street address in plain text.

    Returns (address, method) where method is 'pyap' or 'desc_regex', or None.
    """
    if not text:
        return None
    text = _strip_html(text)

    try:
        import pyap
        found = pyap.parse(text, country="US")
        if found:
            candidate = str(found[0]).strip()
            if _ADDR_MIN_LEN <= len(candidate) <= _ADDR_MAX_LEN:
                return candidate, "pyap"
    except Exception:
        pass

    m = _STREET_RE.search(text)
    if m:
        candidate = m.group(0).strip()
        if _ADDR_MIN_LEN <= len(candidate) <= _ADDR_MAX_LEN:
            return candidate, "desc_regex"

    return None
