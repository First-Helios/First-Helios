"""Stage [0]: the schema.org JSON-LD menu reader (ADR-0013 §1).

A general standard reader, no per-site logic: every ``application/ld+json``
payload is walked for ``MenuItem`` objects (``Menu`` -> ``hasMenuSection`` ->
``hasMenuItem`` -> ``offers``, in whatever nesting or ``@graph`` the page uses).
An item's section is its nearest ``MenuSection`` ancestor; its prices come from
``offers`` (one ``Offer``, a list of them, or an ``AggregateOffer``'s
``lowPrice``). Ported from the spike's ``stage0.py``; its embedded-state walker
and platform fingerprints are not part of Helios.

The reader trusts nothing: ``validator_rows`` turns its items into validator
rows, so a price that isn't printed on the visible page is downgraded to unknown
like any extracted price (the spike found a site whose JSON-LD prices differ
from its page).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from packages.helios_parsing.validator import Row

_LD_SCRIPT = re.compile(
    r"<script[^>]*type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
    re.IGNORECASE | re.DOTALL,
)
_MAX_AMOUNT = Decimal(1000)


@dataclass(frozen=True, slots=True)
class Offer:
    amount: str  # two decimals, e.g. "12.50"
    currency: str | None  # ``priceCurrency`` as given; None when absent


@dataclass(frozen=True, slots=True)
class MenuItem:
    name: str
    section: str | None
    description: str | None
    offers: tuple[Offer, ...]


def json_ld_objects(html: str) -> list[object]:
    """Every parseable ``application/ld+json`` payload, in page order."""
    out: list[object] = []
    for match in _LD_SCRIPT.finditer(html):
        try:
            out.append(json.loads(match.group(1).strip()))
        except ValueError:
            continue
    return out


def _amount(value: object) -> str | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        text = str(value)
    elif isinstance(value, str):
        text = value.strip().lstrip("$").replace(",", "")
    else:
        return None
    try:
        amount = Decimal(text)
    except InvalidOperation:
        return None
    return f"{amount:.2f}" if amount.is_finite() and 0 < amount < _MAX_AMOUNT else None


def _types(obj: dict[str, object]) -> set[str]:
    kind = obj.get("@type")
    if isinstance(kind, str):
        return {kind}
    return {str(k) for k in kind} if isinstance(kind, list) else set()


def _as_list(value: object) -> list[object]:
    if isinstance(value, list):
        return value
    return [] if value is None else [value]


def _offers(value: object) -> tuple[Offer, ...]:
    out: list[Offer] = []
    for offer in _as_list(value):
        if isinstance(offer, dict):
            amount = _amount(offer.get("price")) or _amount(offer.get("lowPrice"))
            currency = offer.get("priceCurrency")
            if amount:
                out.append(Offer(amount, currency.strip() if isinstance(currency, str) else None))
    return tuple(out)


def _walk(obj: object, section: str | None, items: list[MenuItem]) -> None:
    if isinstance(obj, list):
        for value in obj:
            _walk(value, section, items)
        return
    if not isinstance(obj, dict):
        return
    types = _types(obj)
    if "MenuItem" in types:
        description = obj.get("description")
        items.append(
            MenuItem(
                name=str(obj.get("name") or "").strip(),
                section=section,
                description=(description.strip() or None) if isinstance(description, str) else None,
                offers=_offers(obj.get("offers")),
            )
        )
        return
    if "MenuSection" in types:
        section = str(obj.get("name") or "").strip() or section
    for key, value in obj.items():
        if key != "offers":
            _walk(value, section, items)


def menu_items(html: str) -> list[MenuItem]:
    """Every named schema.org ``MenuItem`` in the page's JSON-LD, priced or not."""
    items: list[MenuItem] = []
    for obj in json_ld_objects(html):
        _walk(obj, None, items)
    return [item for item in items if item.name]


def validator_rows(items: list[MenuItem]) -> list[Row]:
    """One row per offer (an unpriced item is one row without a price).

    A missing ``priceCurrency`` is read as USD; any other currency is rejected by
    the validator's sanity check.
    """
    rows: list[Row] = []
    for item in items:
        if not item.offers:
            rows.append(Row(item.name, None, section=item.section))
        rows.extend(
            Row(item.name, offer.amount, section=item.section, currency=offer.currency or "USD")
            for offer in item.offers
        )
    return rows
