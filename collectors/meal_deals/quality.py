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

    score.total = round(raw_total, 3)
    return score


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
