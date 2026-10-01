"""Evaluation harness: gold-label format, extraction scoring, loss buckets, corruption injection.

Ported from the menu-model spike (ADR-0013 §8): ``extract.py`` ``cmd_score`` and
``_match``, ``stress/loss.py``, ``stress/compare.py``'s columns and
``eval_validator.py``. Pure: the gold labels, pages and extractor outputs are
read by ``apps.menu_pipeline.evaluate`` from gitignored ``var/``; tests use
synthetic fixtures only.

**Gold-label format** (one JSON object per page, the spike's)::

    {"page_id": "…", "page_label": "menu", "format": "html_list", "reviewed": true,
     "items": [{"name": "Horchata", "block": "b0014", "section": "Drinks",
                "description": null, "promo": false,
                "prices": [{"amount": "2.50", "variant": "Small"}, …]}, …]}

``promo`` (ADR-0013 Amendment 3) marks a promotional row ("BOGO", "half off",
a happy-hour price); absent means ``false``, as on every set labelled before
the amendment. Other keys (the spike's block roles, regions, notes) are ignored.

**Promo entries** (Amendment 5; optional, absent on sets labelled before it):
a page may list each printed promotion once, at its own grain, for the Phase 10
promo classifier. Rows that print a promo price keep their item-level ``promo``
mark. Kinds are checked; nothing is scored beyond a count::

    "promos": [{"text": "Happy hour: half off apps",
                "scope": {"kind": "sections", "targets": ["Appetizers"]},
                "terms": [{"kind": "percent_off", "value": "50"}],
                "conditions": [{"kind": "hours", "text": "Mon-Fri 3-6pm"}],
                "locators": ["blocks:segment-v2:b0042[0:25]"]}]

``scope.kind`` is ``items``, ``sections`` or ``menu`` (no targets); term kinds
are ``PROMO_TERMS``, condition kinds ``PROMO_CONDITIONS``; each locator is a
Capture-targeted span (ADR-0013 §5).

**Scoring** (``score_page``, per page; ``metrics`` over summed counts): each
extracted row is validated against the page and matched to a gold item by
normalized name tokens.

- item recall: gold items with a matching row (``found_raw``), and with one the
  validator kept (``found_kept``);
- usable prices: gold (item, amount) pairs with an accepted row of that amount,
  over all gold prices;
- price accuracy: accepted, gold-matched, priced rows whose amount is one of the
  item's gold amounts;
- validator on real output: a priced row is *correct* when it matches a gold
  item and one of its amounts; false reject = correct rows not accepted, catch =
  wrong rows not accepted;
- promo: accepted priced rows matched to a ``promo`` item (recorded, not gated).

**Loss** (``loss_page``): every gold price lands in exactly one bucket, in this
order: ``item_missed``, ``row_unpriced``, ``wrong_amount``,
``not_accepted:<reason>``, ``accepted``.

**Corruption injection** (``corruption_eval``): gold rows validated as one
extraction (anything not accepted is a false reject), then the same list with
one row corrupted per trial: ``mutated_price``, ``swapped_prices``,
``invented_item`` (caught only when rejected), ``other_section_price``. A
corruption equal to a legitimate price of that item is also counted as
``indistinguishable``.
"""

from __future__ import annotations

import random
import re
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from packages.helios_parsing.validator import Row, norm_tokens, parse_amount, validate

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from packages.helios_parsing.segment import Block

CORRUPTION_SEED = 7
CORRUPTIONS_PER_TYPE = 10  # trials per corruption type per page
SWAP_DISTANCE = 3  # swapped prices come from rows at most this far apart

PROMO_SCOPES = frozenset({"items", "sections", "menu"})
PROMO_TERMS = frozenset({"percent_off", "amount_off", "fixed_price", "bogo", "free_item", "other"})
PROMO_CONDITIONS = frozenset({"days", "hours", "channel", "min_spend", "other"})
_LOCATOR = re.compile(r"blocks:[\w.-]+:b\d{4}\[\d+:\d+\]")


@dataclass(frozen=True, slots=True)
class GoldPrice:
    amount: str
    variant: str | None = None


@dataclass(frozen=True, slots=True)
class GoldItem:
    name: str
    block: str | None
    section: str | None
    prices: tuple[GoldPrice, ...]
    description: str | None = None
    promo: bool = False


@dataclass(frozen=True, slots=True)
class PromoTerm:
    kind: str  # one of PROMO_TERMS
    value: str | None = None  # "50" (percent), "5.00" (amount or fixed price)


@dataclass(frozen=True, slots=True)
class PromoCondition:
    kind: str  # one of PROMO_CONDITIONS
    text: str


@dataclass(frozen=True, slots=True)
class GoldPromo:
    """One printed promotion (Amendment 5): its scope, terms, conditions and spans."""

    text: str
    scope: str  # one of PROMO_SCOPES
    targets: tuple[str, ...]  # item or section names; empty for the whole menu
    terms: tuple[PromoTerm, ...]
    conditions: tuple[PromoCondition, ...]
    locators: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GoldPage:
    page_id: str
    page_label: str  # "menu" | "not_menu" | "js_only" | "empty"
    format: str | None  # layout family, e.g. "html_list", "html_cards"
    reviewed: bool
    items: tuple[GoldItem, ...]
    promos: tuple[GoldPromo, ...] = ()

    @property
    def scorable(self) -> bool:
        """A reviewed menu page with at least one priced item."""
        return self.reviewed and self.page_label == "menu" and any(it.prices for it in self.items)


def gold_page(label: Mapping[str, Any]) -> GoldPage:
    """A gold label from its JSON object."""
    return GoldPage(
        page_id=str(label["page_id"]),
        page_label=str(label["page_label"]),
        format=label.get("format"),
        reviewed=bool(label.get("reviewed")),
        items=tuple(
            GoldItem(
                name=it["name"],
                block=it.get("block"),
                section=it.get("section"),
                prices=tuple(
                    GoldPrice(amount=p["amount"], variant=p.get("variant")) for p in it["prices"]
                ),
                description=it.get("description"),
                promo=bool(it.get("promo", False)),
            )
            for it in label.get("items") or []
        ),
        promos=tuple(_gold_promo(p) for p in label.get("promos") or []),
    )


def _checked(kind: str, allowed: frozenset[str], what: str) -> str:
    if kind not in allowed:
        raise ValueError(f"promo {what} kind {kind!r} is not one of {sorted(allowed)}")
    return kind


def _gold_promo(promo: Mapping[str, Any]) -> GoldPromo:
    scope = promo["scope"]
    locators = tuple(promo["locators"])
    if not locators or not all(_LOCATOR.fullmatch(loc) for loc in locators):
        raise ValueError(f"promo {promo['text']!r} needs blocks:<segmenter>:bNNNN[s:e] locators")
    return GoldPromo(
        text=promo["text"],
        scope=_checked(scope["kind"], PROMO_SCOPES, "scope"),
        targets=tuple(scope.get("targets") or ()),
        terms=tuple(
            PromoTerm(_checked(t["kind"], PROMO_TERMS, "term"), t.get("value"))
            for t in promo.get("terms") or []
        ),
        conditions=tuple(
            PromoCondition(_checked(c["kind"], PROMO_CONDITIONS, "condition"), c["text"])
            for c in promo.get("conditions") or []
        ),
        locators=locators,
    )


def gold_rows(page: GoldPage) -> list[Row]:
    """One row per gold (item, price), in label order: a perfect extraction."""
    return [
        Row(
            item=it.name,
            amount=p.amount,
            variant=p.variant,
            section=it.section,
            claimed_block=it.block,
        )
        for it in page.items
        for p in it.prices
    ]


def _block_no(block_id: str | None) -> int:
    return int(block_id[1:]) if block_id and block_id[1:].isdigit() else 0


def match(row: Row, items: Sequence[GoldItem]) -> int | None:
    """The gold item (its index) a row names.

    The item with the same name tokens, the one printed nearest the claimed block
    when a dish is listed twice; else an item in the claimed block whose tokens
    are a subset or superset of the row's.
    """
    key = frozenset(norm_tokens(row.item))
    same = [i for i, it in enumerate(items) if frozenset(norm_tokens(it.name)) == key]
    if same:
        claim = _block_no(row.claimed_block)
        return min(same, key=lambda i: abs(_block_no(items[i].block) - claim))
    for i, it in enumerate(items):
        gold_key = frozenset(norm_tokens(it.name))
        if it.block == row.claimed_block and key and (key <= gold_key or gold_key <= key):
            return i
    return None


def score_page(page: GoldPage, blocks: list[Block], rows: list[Row]) -> Counter[str]:
    """Counts for one page's extracted (repaired, stitched) rows; sum pages, then ``metrics``."""
    c: Counter[str] = Counter(pages=1)
    items = page.items
    found_raw: set[int] = set()
    found_kept: set[int] = set()
    found_price: set[tuple[int, Decimal]] = set()
    for v in validate(blocks, rows).verdicts:
        g = match(v.row, items)
        amt = parse_amount(v.row.amount)
        gold_amts = {parse_amount(p.amount) for p in items[g].prices} if g is not None else set()
        correct = g is not None and (amt in gold_amts if gold_amts else amt is None)
        c["rows"] += 1
        c[f"decision:{v.decision}"] += 1
        if g is not None:
            found_raw.add(g)
            if v.decision != "reject":
                found_kept.add(g)
        if v.decision == "accept":
            if g is not None and amt is not None:
                c["accepted_matched_priced"] += 1
                c["accepted_price_exact"] += int(amt in gold_amts)
                if amt in gold_amts:
                    found_price.add((g, amt))
                if items[g].promo:
                    c["promo_rows_stored"] += 1
            elif g is None:
                c["accepted_unmatched"] += 1
        if amt is None:  # a missing price is a recall miss, not a corruption to catch
            c["unpriced_rows"] += 1
            continue
        c["correct" if correct else "wrong"] += 1
        if correct and v.decision != "accept":
            c["false_reject"] += 1
            c.update(f"false_reject_reason:{r.split(' ')[0]}" for r in v.reasons)
        if not correct and v.decision != "accept":
            c["caught"] += 1
        if not correct and v.decision == "accept":
            c["wrong_accepted"] += 1
            c["wrong_accepted_price"] += int(g is not None)
    c["gold_items"] += len(items)
    c["gold_prices"] += sum(len(it.prices) for it in items)
    c["gold_promo_items"] += sum(1 for it in items if it.promo)
    c["gold_promos"] += len(page.promos)
    c["found_raw"] += len(found_raw)
    c["found_kept"] += len(found_kept)
    c["found_price"] += len(found_price)
    return c


def _rate(c: Counter[str], num: str, den: str) -> float | None:
    return c[num] / c[den] if c[den] else None


def metrics(c: Counter[str]) -> dict[str, float | None]:
    """The §8 extraction numbers from summed ``score_page`` counts."""
    return {
        "item_recall": _rate(c, "found_raw", "gold_items"),
        "item_recall_kept": _rate(c, "found_kept", "gold_items"),
        "usable_prices": _rate(c, "found_price", "gold_prices"),
        "price_accuracy": _rate(c, "accepted_price_exact", "accepted_matched_priced"),
        "validator_false_reject": _rate(c, "false_reject", "correct"),
        "validator_catch": _rate(c, "caught", "wrong"),
    }


def loss_page(page: GoldPage, blocks: list[Block], rows: list[Row]) -> Counter[str]:
    """Where each of the page's gold prices went (one bucket per gold price)."""
    by_item: dict[int, list[tuple[Decimal | None, str, tuple[str, ...]]]] = {}
    for v in validate(blocks, rows).verdicts:
        g = match(v.row, page.items)
        if g is not None:
            by_item.setdefault(g, []).append((parse_amount(v.row.amount), v.decision, v.reasons))
    buckets: Counter[str] = Counter()
    for i, it in enumerate(page.items):
        found = by_item.get(i, [])
        for p in it.prices:
            amt = parse_amount(p.amount)
            if not found:
                bucket = "item_missed"
            elif all(a is None for a, _, _ in found):
                bucket = "row_unpriced"
            elif not any(a == amt for a, _, _ in found):
                bucket = "wrong_amount"
            elif any(a == amt and d == "accept" for a, d, _ in found):
                bucket = "accepted"
            else:
                reasons = next(r for a, _, r in found if a == amt)
                bucket = "not_accepted:" + (reasons[0].split(" ")[0] if reasons else "?")
            buckets[bucket] += 1
    return buckets


def _mutate(amount: Decimal, rng: random.Random) -> Decimal:
    choice = rng.choice(["+0.50", "-0.50", "+1.00", "-1.00", "digit"])
    if choice == "digit":
        cents = int(amount * 100)
        last = cents % 10
        new_last = rng.choice([d for d in range(10) if d != last])
        return Decimal(cents - last + new_last) / 100
    new = amount + Decimal(choice)
    return new if new > 0 else amount + Decimal("1.00")


def _with_amount(row: Row, amount: str | None) -> Row:
    return Row(row.item, amount, row.variant, row.section, "USD", row.claimed_block)


def corruption_eval(
    pages: Sequence[tuple[GoldPage, list[Block]]], seed: int = CORRUPTION_SEED
) -> Counter[str]:
    """Validator false rejects on gold rows and catch rate on injected corruptions.

    Counts: ``correct_rows``, ``false_reject``, ``false_reject_reason:<reasons>``,
    and per corruption type ``n:<type>``, ``caught:<type>``,
    ``indistinguishable:<type>``. One random stream over the pages in the given
    order, so a seed and a page order reproduce a run.
    """
    rng = random.Random(seed)  # noqa: S311 - reproducible sampling, not security
    c: Counter[str] = Counter()
    all_names = [(page.page_id, r.item) for page, _ in pages for r in gold_rows(page)]
    for page, blocks in pages:
        rows = [r for r in gold_rows(page) if r.amount is not None]
        if not rows:
            continue
        clean = validate(blocks, rows).verdicts
        for v in clean:
            c["correct_rows"] += 1
            if v.decision != "accept":
                c["false_reject"] += 1
                c[f"false_reject_reason:{','.join(v.reasons)}"] += 1
        accepted = {
            i: parse_amount(r.amount)
            for i, (r, v) in enumerate(zip(rows, clean, strict=True))
            if v.decision == "accept"
        }
        idx = list(accepted)  # corrupt only rows the validator accepts when clean
        if not idx:
            continue

        def own_prices(i: int, rows: list[Row] = rows) -> set[Decimal]:
            return {a for r in rows if r.item == rows[i].item and (a := parse_amount(r.amount))}

        def trial(
            corrupt: list[Row],
            at: list[int],
            kind: str,
            legit: list[set[Decimal]],
            blocks: list[Block] = blocks,
        ) -> None:
            verdicts = validate(blocks, corrupt).verdicts
            for k, i in enumerate(at):
                c[f"n:{kind}"] += 1
                decision = verdicts[i].decision
                # an invented item is caught only when rejected; a wrong price when not accepted
                caught = decision == "reject" if kind == "invented_item" else decision != "accept"
                if caught:
                    c[f"caught:{kind}"] += 1
                elif parse_amount(corrupt[i].amount) in legit[k]:
                    c[f"indistinguishable:{kind}"] += 1

        for _ in range(min(CORRUPTIONS_PER_TYPE, len(idx))):
            i = rng.choice(idx)
            amt = accepted[i]
            if amt is None:
                continue
            corrupt = list(rows)
            corrupt[i] = _with_amount(rows[i], f"{_mutate(amt, rng):.2f}")
            trial(corrupt, [i], "mutated_price", [own_prices(i)])

        for _ in range(min(CORRUPTIONS_PER_TYPE, len(idx))):
            i = rng.choice(idx)
            near = [
                j
                for j in idx
                if 0 < abs(j - i) <= SWAP_DISTANCE
                and rows[j].item != rows[i].item
                and accepted[j] != accepted[i]
            ]
            if not near:
                continue
            j = rng.choice(near)
            corrupt = list(rows)
            corrupt[i] = _with_amount(rows[i], rows[j].amount)
            corrupt[j] = _with_amount(rows[j], rows[i].amount)
            trial(corrupt, [i, j], "swapped_prices", [own_prices(i), own_prices(j)])

        page_tokens = {t for b in blocks for t in norm_tokens(b.text)}
        foreign = [
            n for p, n in all_names if p != page.page_id and not set(norm_tokens(n)) <= page_tokens
        ]
        for _ in range(min(CORRUPTIONS_PER_TYPE, len(foreign))):
            name = rng.choice(foreign)
            pos = rng.randrange(len(rows) + 1)
            invented = Row(name, rows[rng.choice(idx)].amount)
            trial([*rows[:pos], invented, *rows[pos:]], [pos], "invented_item", [set()])

        for _ in range(min(CORRUPTIONS_PER_TYPE, len(idx))):
            i = rng.choice(idx)
            others = [
                j
                for j in idx
                if rows[j].section != rows[i].section and accepted[j] not in own_prices(i)
            ]
            if not others:
                continue
            j = rng.choice(others)
            corrupt = list(rows)
            corrupt[i] = _with_amount(rows[i], rows[j].amount)
            trial(corrupt, [i], "other_section_price", [own_prices(i)])
    return c


def corruption_metrics(c: Counter[str]) -> dict[str, float | None]:
    """False-reject and catch rates from ``corruption_eval`` counts."""
    caught = sum(n for k, n in c.items() if k.startswith("caught:"))
    total = sum(n for k, n in c.items() if k.startswith("n:"))
    return {
        "false_reject": c["false_reject"] / c["correct_rows"] if c["correct_rows"] else None,
        "catch": caught / total if total else None,
    }
