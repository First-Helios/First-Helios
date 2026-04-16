"""
collectors/meal_deals/temporal.py — Day/time-range extraction for meal deals.

Shared between website_scraper.py and chain_deals.py.  Handles:
  • Day ranges: "Mon-Fri", "Monday-Friday", "Monday – Friday" (en/em dash),
    "Mon thru Fri", "Monday through Friday", "Mon to Fri"
  • Day aliases: "weekdays", "weekends", "daily", "every day", "all week"
  • Comma-separated day lists: "Mon, Tue, Wed"
  • Time ranges: "3pm-6pm", "11:00 AM – 2:00 PM", "3-6:30PM", "11am to 1pm"
  • "Close" as end-of-day sentinel (stored as "Close" string)

Normalizes output to canonical forms:
  • Day ranges → "Mon-Fri"-style (3-letter title case)
  • Individual days → "Mon" / "Tue" / "Wed" ...
  • Time ranges → ("3:00 PM", "6:00 PM") tuples, 12-hour with AM/PM

Returns (None, None) when nothing is found so callers can keep going.
"""

from __future__ import annotations

import re

# ── Day constants ──────────────────────────────────────────────────────────

_DAY_ABBREV = {
    "monday": "Mon", "mon": "Mon",
    "tuesday": "Tue", "tue": "Tue", "tues": "Tue",
    "wednesday": "Wed", "wed": "Wed", "weds": "Wed",
    "thursday": "Thu", "thu": "Thu", "thur": "Thu", "thurs": "Thu",
    "friday": "Fri", "fri": "Fri",
    "saturday": "Sat", "sat": "Sat",
    "sunday": "Sun", "sun": "Sun",
}

_WEEK_ORDER = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# Any single day token (word-boundary anchored)
_SINGLE_DAY_RE = re.compile(
    r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday"
    r"|mon|tues?|wed(?:s|nesday)?|thu(?:r|rs)?|fri|sat|sun)\b",
    re.IGNORECASE,
)

# Day ranges: "Mon-Fri", "Mon - Fri", "Mon – Fri", "Mon — Fri",
# "Mon thru Fri", "Monday through Friday", "Mon to Fri"
_DAY_RANGE_RE = re.compile(
    r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday"
    r"|mon|tues?|wed(?:s|nesday)?|thu(?:r|rs)?|fri|sat|sun)"
    r"\s*(?:-|–|—|to|thru|through)\s*"
    r"(monday|tuesday|wednesday|thursday|friday|saturday|sunday"
    r"|mon|tues?|wed(?:s|nesday)?|thu(?:r|rs)?|fri|sat|sun)\b",
    re.IGNORECASE,
)

# Day aliases: weekdays, weekends, daily, every day, all week
_WEEKDAYS_RE = re.compile(r"\b(?:weekdays?|every\s+weekday)\b", re.IGNORECASE)
_WEEKENDS_RE = re.compile(r"\b(?:weekends?)\b", re.IGNORECASE)
_DAILY_RE = re.compile(
    r"\b(?:daily|everyday|every\s+day|all\s+(?:week|days?)|7\s*days?\s*a\s*week)\b",
    re.IGNORECASE,
)


# ── Time constants ─────────────────────────────────────────────────────────

# A single clock time, optionally followed by am/pm
_SINGLE_TIME_RE = re.compile(
    r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)\b",
    re.IGNORECASE,
)

# Time range — requires explicit range separator so we don't grab unrelated
# times (e.g. the timestamp on a blog post).  Accepts:
#   "3pm-6pm", "3-6pm", "3:00PM – 6:30PM", "11am to 1pm",
#   "3PM – Close", "3pm til close"
_TIME_RANGE_RE = re.compile(
    r"(\d{1,2}(?::\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.)?)"
    r"\s*(?:-|–|—|to|til|till|until)\s*"
    r"(\d{1,2}(?::\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.)?|close|closing)",
    re.IGNORECASE,
)


# ── Public API ─────────────────────────────────────────────────────────────

def extract_days(text: str) -> str | None:
    """Extract a day / day-range string from free-form text.

    Priority (most specific wins):
      1. Explicit range ("Mon-Fri", "Monday through Friday")
      2. Aliases ("weekdays", "weekends", "daily")
      3. Comma-separated list of days ("Mon, Tue, Wed")
      4. Single day ("Tuesday")

    Returns a normalized string like "Mon-Fri", "Tue", "Weekdays", "Daily",
    or None if no day info found.
    """
    if not text:
        return None

    # 1. Explicit range
    rng = _DAY_RANGE_RE.search(text)
    if rng:
        start = _DAY_ABBREV.get(rng.group(1).lower())
        end = _DAY_ABBREV.get(rng.group(2).lower())
        if start and end and start != end:
            return f"{start}-{end}"
        if start:  # degenerate "Mon-Mon"
            return start

    # 2. Aliases
    if _DAILY_RE.search(text):
        return "Daily"
    if _WEEKDAYS_RE.search(text):
        return "Mon-Fri"
    if _WEEKENDS_RE.search(text):
        return "Sat-Sun"

    # 3. Comma- or "and"-separated list
    listed: list[str] = []
    for m in _SINGLE_DAY_RE.finditer(text):
        abbrev = _DAY_ABBREV.get(m.group(1).lower())
        if abbrev and abbrev not in listed:
            listed.append(abbrev)
        if len(listed) >= 7:
            break

    if len(listed) >= 2:
        # If the days form a contiguous span in week order, render as range
        indices = sorted(_WEEK_ORDER.index(d) for d in listed)
        if indices == list(range(indices[0], indices[-1] + 1)):
            return f"{_WEEK_ORDER[indices[0]]}-{_WEEK_ORDER[indices[-1]]}"
        # Preserve insertion order otherwise
        return ", ".join(listed)

    if listed:
        return listed[0]

    return None


def extract_times(text: str) -> tuple[str | None, str | None]:
    """Extract a (start_time, end_time) pair from free-form text.

    Prefers explicit ranges using "-", "–", "—", "to", "til", "until".
    Recognizes "Close"/"Closing" as end-of-day and returns it literally.
    Inherits am/pm from the other endpoint when only one is labeled
    (e.g. "3-6pm" → start=3:00 PM, end=6:00 PM).

    Returns (None, None) if no time info found.
    Returns (start, None) if only a single time is present (no range).
    """
    if not text:
        return None, None

    rng = _TIME_RANGE_RE.search(text)
    if rng:
        raw_start = rng.group(1).strip()
        raw_end = rng.group(2).strip()

        # Close / closing sentinel
        if raw_end.lower() in ("close", "closing"):
            start = _normalize_time(raw_start, fallback_ampm=None)
            return start, "Close"

        # Normalize both; if one lacks am/pm, inherit from the other
        start_has_ampm = bool(re.search(r"(am|pm|a\.m\.|p\.m\.)", raw_start, re.IGNORECASE))
        end_has_ampm = bool(re.search(r"(am|pm|a\.m\.|p\.m\.)", raw_end, re.IGNORECASE))

        end_ampm = _extract_ampm(raw_end)
        start_ampm = _extract_ampm(raw_start)

        start = _normalize_time(raw_start, fallback_ampm=end_ampm if not start_has_ampm else None)
        end = _normalize_time(raw_end, fallback_ampm=start_ampm if not end_has_ampm else None)
        if start or end:
            return start, end

    # Fall back: single time mention (no range)
    single = _SINGLE_TIME_RE.search(text)
    if single:
        return _normalize_time(single.group(0), fallback_ampm=None), None

    return None, None


# ── Helpers ────────────────────────────────────────────────────────────────

def _extract_ampm(token: str) -> str | None:
    m = re.search(r"(am|pm|a\.m\.|p\.m\.)", token, re.IGNORECASE)
    if not m:
        return None
    return "AM" if m.group(1).lower().startswith("a") else "PM"


def _normalize_time(token: str, fallback_ampm: str | None) -> str | None:
    """Normalize a single time token to 'H:MM AM/PM' form."""
    m = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?", token, re.IGNORECASE)
    if not m:
        return None

    hour = int(m.group(1))
    minute = int(m.group(2)) if m.group(2) else 0
    ampm_raw = m.group(3)

    if ampm_raw:
        ampm = "AM" if ampm_raw.lower().startswith("a") else "PM"
    elif fallback_ampm:
        ampm = fallback_ampm
    else:
        # No am/pm at all — assume PM for 1-11 (typical happy-hour range) and
        # leave 12 as-is.  This is a heuristic but matches common menu copy.
        ampm = "PM" if 1 <= hour <= 11 else "AM"

    if hour < 1 or hour > 12:
        # "13:00" style — convert to 12-hour
        if 13 <= hour <= 23:
            hour -= 12
            ampm = "PM"
        elif hour == 0:
            hour = 12
            ampm = "AM"
        else:
            return None

    return f"{hour}:{minute:02d} {ampm}"
