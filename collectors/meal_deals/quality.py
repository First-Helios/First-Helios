"""
collectors/meal_deals/quality.py — Signal quality scoring for meal deals.

Computes a composite 0.0–1.0 score per deal based on 6 factors (see plan K).
Used at ingest to gate new data, and by backfill scripts to triage existing rows.

Gating rules (applied by caller):
  score < 0.20  → reject (skipped at ingest)
  0.20 ≤ score < 0.40 → store but set is_active=False (review)
  score ≥ 0.40  → store as active

Shared between:
  - collectors/meal_deals/ingest.py  (gate new signals)
  - scripts/backfill_signal_quality.py  (score existing rows)
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# ── Scoring weights (sum = 1.00) ────────────────────────────────────────────

W_PRICE = 0.25         # Has usable price
W_TIME = 0.20          # Has time/day window
W_DESCRIPTION = 0.15   # Has meaningful description
W_NAME = 0.15          # Deal name is real (not a sentence)
W_RESTAURANT = 0.10    # Content matches restaurant
W_NOT_ADDON = 0.15     # Not an add-on / modifier

# ── Gating thresholds ──────────────────────────────────────────────────────
REJECT_BELOW = 0.20
REVIEW_BELOW = 0.40

# ── Content checks ─────────────────────────────────────────────────────────

# Boilerplate / marketing copy that isn't a real deal description
_BOILERPLATE_RE = re.compile(
    r"\b("
    r"who\s+doesn['\u2019]?t\s+love"
    r"|check\s+out\s+how\s+you\s+can\s+save"
    r"|wanna\s+save"
    r"|values\s+in\s+action"
    r"|rewards\s+member"
    r"|download\s+(?:the\s+)?app"
    r"|learn\s+more"
    r"|click\s+here"
    r"|sign\s+up"
    r"|enter\s+rewards?\s+code"
    r")\b",
    re.IGNORECASE,
)

# Add-on / modifier / "extra" signals — if present, deal is likely an add-on
_ADDON_RE = re.compile(
    r"(?:\+\s*\$|\b(?:add|extra|upgrade|substitut)\s.{0,20}\$)",
    re.IGNORECASE,
)

# Sentence-fragment markers — if deal name starts with/contains these it's
# a scraped description, not a name
_SENTENCE_FRAGMENT_RE = re.compile(
    r"^(?:a\s+(?:spicy|flavorful|tasty|classic|fresh|rich)|"
    r"your\s+choice\s+of|get\s+\d+%\s+off|"
    r"made\s+with|served\s+with|topped\s+with|comes?\s+with|includ(?:ed|es|ing))",
    re.IGNORECASE,
)

_MENU_NAV_RE = re.compile(
    r"\b("
    r"main\s+content\s+starts\s+here"
    r"|tab\s+to\s+start\s+navigating"
    r"|open\s+menu\s+close\s+menu"
    r"|sample\s+menus?"
    r"|order\s+online"
    r"|happy\s+hour\s+locations"
    r"|locations\s+happy\s+hour"
    r"|food\s*(?:&|and)\s*drinks"
    r"|drink\s+menu"
    r"|bar\s+menu"
    r"|dinner\s+menu"
    r"|brunch\s+menu"
    r"|desserts?"
    r"|cocktails?"
    r")\b",
    re.IGNORECASE,
)

_REVIEWISH_RE = re.compile(
    r"\b("
    r"this\s+is\s+by\s+far"
    r"|favorite\s+place\s+to\s+eat"
    r"|my\s+boyfriend\s+and\s+i"
    r"|don['\u2019]?t\s+miss\s+any\s+sporting\s+action"
    r"|check\s+out\s+our\s+new"
    r"|stay\s+a\s+while"
    r"|yes!\s*we\s+do\s+have"
    r"|we\s+have\s+the\s+games"
    r")\b",
    re.IGNORECASE,
)

_STRONG_OFFER_RE = re.compile(
    r"\b("
    r"bogo"
    r"|buy\s+one\s+get\s+one"
    r"|buy\s+1\s+get\s+1"
    r"|kids\s+eat\s+free"
    r"|half\s+(?:off|price)"
    r"|½\s*(?:off|price)"
    r"|\d{1,2}\s*%\s*off"
    r"|two\s+for\s+one"
    r"|2\s+for\s+1"
    r")\b",
    re.IGNORECASE,
)

_MENUISH_TOKENS = (
    "menu",
    "menus",
    "dinner",
    "drinks",
    "drink",
    "bar",
    "brunch",
    "dessert",
    "desserts",
    "cocktails",
    "food",
    "happy hour",
    "order online",
)


@dataclass
class QualityScore:
    """Breakdown of a signal's quality score.  Sum of components = total."""
    total: float = 0.0
    price: float = 0.0
    time: float = 0.0
    description: float = 0.0
    name: float = 0.0
    restaurant_match: float = 0.0
    not_addon: float = 0.0

    # For logging / debugging
    reasons: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.reasons is None:
            self.reasons = []


def _looks_like_menu_or_navigation(text: str | None) -> bool:
    if not text:
        return False

    normalized = " ".join(text.strip().split()).lower()
    if _MENU_NAV_RE.search(normalized):
        return True

    token_hits = sum(1 for token in _MENUISH_TOKENS if token in normalized)
    if token_hits >= 3 and ("menu" in normalized or "happy hour" in normalized):
        return True

    return normalized.count("happy hour") >= 3


def _looks_like_review_or_marketing(text: str | None) -> bool:
    if not text:
        return False

    normalized = " ".join(text.strip().split())
    return bool(_REVIEWISH_RE.search(normalized))


def _score_price(price: float | None, price_type: str | None) -> tuple[float, str | None]:
    """Full credit when price is a non-trivial absolute/discount/percentage."""
    if price is None and price_type != "percentage_off":
        return 0.0, "no price"

    if price_type == "unknown" or price_type is None:
        # Have a number but no classification — partial credit
        return W_PRICE * 0.4, "price_type unknown"

    if price_type == "percentage_off":
        return W_PRICE, None

    if price is not None and price < 1.50:
        # Below the "probably an add-on" floor, half credit
        return W_PRICE * 0.5, "price < 1.50"

    return W_PRICE, None


def _score_time(valid_days: str | None, valid_start: str | None, valid_end: str | None) -> tuple[float, str | None]:
    """Reward any temporal info; full credit when days AND times present."""
    has_days = bool(valid_days)
    has_start = bool(valid_start)
    has_end = bool(valid_end)

    if has_days and (has_start or has_end):
        return W_TIME, None
    if has_days or has_start or has_end:
        return W_TIME * 0.5, None
    return 0.0, "no temporal info"


def _score_description(description: str | None) -> tuple[float, str | None]:
    """Description needs length and must not be pure boilerplate."""
    if not description:
        return 0.0, "no description"
    text = description.strip()
    if _looks_like_menu_or_navigation(text):
        return 0.0, "description is menu/navigation text"
    if _looks_like_review_or_marketing(text):
        return 0.0, "description is marketing/review text"
    if len(text) < 10:
        return 0.0, "description too short"
    if _BOILERPLATE_RE.search(text):
        return 0.0, "description is boilerplate"
    if len(text) < 30:
        return W_DESCRIPTION * 0.5, None
    return W_DESCRIPTION, None


def _score_name(name: str | None) -> tuple[float, str | None]:
    """Name should be short, present, and not a sentence fragment."""
    if not name:
        return 0.0, "no name"
    text = name.strip()
    if _looks_like_menu_or_navigation(text):
        return 0.0, "name is menu/navigation text"
    if _looks_like_review_or_marketing(text):
        return 0.0, "name is marketing/review text"
    if len(text) < 5:
        return 0.0, "name too short"
    if len(text) > 80:
        return W_NAME * 0.25, "name too long"
    if _SENTENCE_FRAGMENT_RE.match(text):
        return 0.0, "name is sentence fragment"
    # Deduct slightly for borderline long names
    if len(text) > 60:
        return W_NAME * 0.6, None
    return W_NAME, None


def _score_restaurant_match(
    restaurant_name: str | None,
    deal_name: str | None,
    description: str | None,
    raw_text: str | None,
) -> tuple[float, str | None]:
    """Full credit if restaurant name appears in deal content OR there's no
    competing restaurant mention.  Cheap heuristic — we're not NER here."""
    if not restaurant_name:
        # Can't check — give neutral credit
        return W_RESTAURANT * 0.5, None

    haystacks = [s for s in (deal_name, description, raw_text) if s]
    if not haystacks:
        return W_RESTAURANT * 0.5, None
    combined = " ".join(haystacks).lower()

    # Extract meaningful tokens from restaurant name (3+ char words, excluding common chain suffixes)
    stop = {"the", "and", "bar", "grill", "cafe", "kitchen", "tavern", "bbq", "pizza", "sub", "subs", "restaurant"}
    tokens = [
        w for w in re.findall(r"[a-z0-9']+", restaurant_name.lower())
        if len(w) >= 3 and w not in stop
    ]
    if not tokens:
        return W_RESTAURANT * 0.5, None

    # Does at least one meaningful token of the restaurant name appear in the content?
    if any(tok in combined for tok in tokens):
        return W_RESTAURANT, None

    return W_RESTAURANT * 0.3, "restaurant name not in content"


def _score_not_addon(
    price_type: str | None,
    deal_name: str | None,
    description: str | None,
    raw_text: str | None,
) -> tuple[float, str | None]:
    """Full credit unless the text reads like an add-on/modifier."""
    # Composite text to scan
    text = " ".join(s for s in (deal_name, description, raw_text) if s)
    if not text:
        return W_NOT_ADDON, None

    if _ADDON_RE.search(text):
        return 0.0, "add-on / modifier detected"

    # If price_type is absolute or percentage_off we trust the pipeline did its job
    if price_type in ("absolute", "percentage_off", "discount_amount"):
        return W_NOT_ADDON, None

    # Unknown price_type and nothing flagged — half credit
    return W_NOT_ADDON * 0.7, None


def compute_signal_quality(
    *,
    deal_name: str | None = None,
    deal_description: str | None = None,
    price: float | None = None,
    price_type: str | None = None,
    discount_percentage: float | None = None,
    valid_days: str | None = None,
    valid_start_time: str | None = None,
    valid_end_time: str | None = None,
    restaurant_name: str | None = None,
    raw_scraped_text: str | None = None,
) -> QualityScore:
    """Compute 0.0–1.0 composite quality score with per-factor breakdown.

    Keyword-only so callers don't confuse positional args.  All fields are
    optional — missing fields count as 0 for their factor.
    """
    score = QualityScore()

    pv, r = _score_price(price, price_type)
    score.price = pv
    if r:
        score.reasons.append(f"price: {r}")

    tv, r = _score_time(valid_days, valid_start_time, valid_end_time)
    score.time = tv
    if r:
        score.reasons.append(f"time: {r}")

    dv, r = _score_description(deal_description)
    score.description = dv
    if r:
        score.reasons.append(f"description: {r}")

    nv, r = _score_name(deal_name)
    score.name = nv
    if r:
        score.reasons.append(f"name: {r}")

    rv, r = _score_restaurant_match(restaurant_name, deal_name, deal_description, raw_scraped_text)
    score.restaurant_match = rv
    if r:
        score.reasons.append(f"restaurant: {r}")

    av, r = _score_not_addon(price_type, deal_name, deal_description, raw_scraped_text)
    score.not_addon = av
    if r:
        score.reasons.append(f"addon: {r}")

    raw_total = (
        score.price + score.time + score.description + score.name
        + score.restaurant_match + score.not_addon
    )

    # If add-on context was detected and we don't have a strong absolute
    # price ≥ $2, cap the total at 0.25 so it lands in "reject" territory.
    # The add-on penalty (0.15) alone isn't enough to tip borderline signals
    # that otherwise look legitimate (e.g. "Add bacon for +$1").
    if score.not_addon == 0.0 and not (price_type == "absolute" and (price or 0) >= 2.0):
        raw_total = min(raw_total, 0.25)
        score.reasons.append("addon: score capped (no absolute price)")

    combined_text = " ".join(
        part for part in (deal_name, deal_description, raw_scraped_text) if part
    )
    has_temporal_evidence = bool(valid_days or valid_start_time or valid_end_time)
    has_offer_evidence = bool(
        price is not None
        or discount_percentage is not None
        or price_type in ("absolute", "discount_amount", "percentage_off")
        or _STRONG_OFFER_RE.search(combined_text)
    )
    if not has_temporal_evidence and not has_offer_evidence:
        raw_total = min(raw_total, 0.35)
        score.reasons.append("evidence: missing price/discount and temporal info")

    score.total = round(raw_total, 3)
    return score


def compute_deal_value_score(
    *,
    price: float | None = None,
    price_type: str | None = None,
    discount_percentage: float | None = None,
    deal_name: str | None = None,
    deal_description: str | None = None,
    raw_scraped_text: str | None = None,
) -> float:
    """Compute 0.0–1.0 offer-strength score representing consumer value.

    This is *separate* from signal_quality (data completeness).  A deal can
    have perfect signal quality but weak value (e.g. "$1 off"), or strong
    value but incomplete data.

    Tier mapping (returned score → label):
      0.90–1.00  Tier 5 — BOGO / buy-one-get-one / 2-for-1
      0.70–0.89  Tier 4 — ≥40% off; half off; absolute ≤$3 drink/taco/item
      0.50–0.69  Tier 3 — 20–39% off; $3–$5 off; absolute $4–$8
      0.30–0.49  Tier 2 — 10–19% off; $2–$3 off
      0.10–0.29  Tier 1 — <10% off; $1 off generic
      0.00       Tier 0 — unknown / no price info
    """
    combined = " ".join(
        s for s in (deal_name, deal_description, raw_scraped_text) if s
    ).lower()

    # ── Tier 5: BOGO ────────────────────────────────────────────────────────
    _BOGO_RE = re.compile(
        r"\b(?:bogo|buy\s+one\s+get\s+one|buy\s+1\s+get\s+1|2\s+for\s+1|two\s+for\s+one"
        r"|get\s+one\s+free|buy\s+(?:one|1)\s+.{0,20}free)\b",
        re.IGNORECASE,
    )
    if _BOGO_RE.search(combined):
        return 0.95

    # ── Tier 4–5: percentage off ─────────────────────────────────────────────
    pct = discount_percentage
    if pct is None and price_type == "percentage_off" and price:
        pct = price  # some rows store the % in price field

    # Also parse percentage from text if column is missing
    if pct is None:
        _PCT_TEXT_RE = re.compile(r"(\d{1,3})\s*%\s*off", re.IGNORECASE)
        _HALF_RE = re.compile(r"\bhalf\s+(?:off|price)\b|½\s*(?:off|price)", re.IGNORECASE)
        m = _PCT_TEXT_RE.search(combined)
        if m:
            pct = float(m.group(1))
        elif _HALF_RE.search(combined):
            pct = 50.0

    if pct is not None:
        if pct >= 75:
            return 0.92
        if pct >= 50:
            return 0.85
        if pct >= 40:
            return 0.78
        if pct >= 30:
            return 0.65
        if pct >= 20:
            return 0.55
        if pct >= 15:
            return 0.40
        if pct >= 10:
            return 0.32
        return 0.18  # <10% off

    # ── Absolute price: item costs $X ───────────────────────────────────────
    # Key insight: "$1 drinks" (absolute) >> "$1 off" (discount)
    if price_type == "absolute" and price is not None:
        if price <= 1.50:
            return 0.88   # $1 drinks, $1 tacos — extremely high value
        if price <= 3.00:
            return 0.80   # $2–$3 items — still great
        if price <= 5.00:
            return 0.68   # $4–$5 items — good happy hour pricing
        if price <= 8.00:
            return 0.58   # $6–$8 — decent deal
        if price <= 15.00:
            return 0.45   # $9–$15 — moderate
        return 0.30        # >$15 — unclear if it's really a deal

    # ── Discount amount: saves $X off menu price ─────────────────────────────
    # "$1 off" is weak. "$10 off" is meaningful. "$5 off" is moderate.
    if price_type == "discount_amount" and price is not None:
        if price >= 10.0:
            return 0.70
        if price >= 5.0:
            return 0.58
        if price >= 3.0:
            return 0.42
        if price >= 2.0:
            return 0.30
        return 0.15   # $1 off — weak

    # ── Fallback: parse discount amount from text ─────────────────────────────
    _DOLLAR_OFF_RE = re.compile(r"\$\s*(\d+(?:\.\d{1,2})?)\s*off\b", re.IGNORECASE)
    m = _DOLLAR_OFF_RE.search(combined)
    if m:
        amt = float(m.group(1))
        if amt >= 10:
            return 0.68
        if amt >= 5:
            return 0.55
        if amt >= 3:
            return 0.40
        if amt >= 2:
            return 0.28
        return 0.15

    # ── No extractable offer value ────────────────────────────────────────────
    return 0.0


def gate_decision(score: float) -> tuple[str, bool]:
    """Return (decision, is_active) for a given quality score.

    decision: "reject" | "review" | "active"
    is_active: the value to set on the meal_deal row (False for review).
    """
    if score < REJECT_BELOW:
        return "reject", False
    if score < REVIEW_BELOW:
        return "review", False
    return "active", True
