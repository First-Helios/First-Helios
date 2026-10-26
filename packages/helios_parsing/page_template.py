"""Stage [5d] page template and duplicate removal (ADR-0013 Amendment 29; session P8-14).

Generic and stdlib only: no per-site or per-platform rule, no manual entry. The page's
own item layout is learned from the items the pipeline already accepted (wrapper
induction, with the model's accepted output as its seeds), on the ``llm`` stream only:

1. **Seeds.** Accepted rows with a name block and a price block.
2. **Record pattern** of a seed: the tag path of its name block and of its price block
   (the last :data:`~packages.helios_parsing.dom_sections.SIGNATURE_DEPTH` block-level
   tags; classes are not trusted, since a site may style an item line like a description)
   and how the two relate: the block offset, the lowest common block-level ancestor's tag,
   and how many block levels each sits under it.
3. **Template.** Seeds are grouped by exact pattern; a group counts with at least
   :data:`MIN_SUPPORT` seeds and :data:`MIN_SHARE` of them.
4. **Page gate.** At least :data:`MIN_SEEDS` seeds; the template explains
   :data:`GATE_EXPLAINED` of them, and :data:`GATE_AGREE` of the explained seeds share the
   main name path. An ungated page gets its rows back unchanged.
5. **Name candidates.** A block on a template name path: for a same-block pattern
   ("Caesar Salad ..... $9.39") it prints a price after some text; for a split pattern
   (an ``h3`` title over a price ``div``) its class signature is one the seeds use. Its
   *record* is its container (the pattern's common ancestor; for a same-block pattern,
   the line's parent) up to the next candidate.
6. **Actions**, on kept rows named inside another candidate's record:
   - **ATTACH:** a size label printed with its price in a run of two or more labelled
     prices ("Pequeño $12.49 | Mediano $21.99") becomes a variant of the record's dish;
   - **RE-NAME:** a row named by the record title's words but cited on its description is
     re-grounded on the title (dropped when the title already holds it); an accepted
     description row priced inside the record of a title kept unpriced takes the title's
     name;
   - **DROP:** a description-like line (``output._description_like``) that prints no
     price of its own and not the row's amount; a ``|``-separated list of names stays;
   - **ADD:** a template price line no kept row cites, with a name block in the
     pattern's position, becomes an item: one row per printed price, labelled when there
     are several. It is skipped inside a kept item's span, for an add-on, a
     description-like or price-label-only name, below a dish kept unpriced, under a
     wine-list heading (Amendment 15), or when the name and price are already held.

Every row [5d] adds or rewrites is judged again by the unchanged validator and [5b].

**Duplicate removal** (rule "same", :func:`remove_duplicates`): a printed item (name
block, normalized name) the model emitted under two or more of its sections keeps the rows
of its first section when every copy cites the same non-empty set of printed price spans.
Copies citing different prices, and unpriced copies, stay: either may be a second printed
dish the validator grounded onto the first print. With the clash gone, [5c]'s merge guard
no longer holds the survivor back.

:func:`llm_stream` is the ``llm`` stream's whole post-model interpretation, in order:
``rows_of`` → [5]+[5b] → [5d] → [5]+[5b] again → duplicate removal → [5c]. Part of
``resolve.RESOLVER_VERSION`` ("resolve-v4" = [5b] + [5c] + [5d] + duplicate removal).
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from packages.helios_parsing.dom_sections import DomSections, assign, placed_blocks, signature
from packages.helios_parsing.output import (
    _description_like,
    rows_of,
    strip_diet_marks,
    wine_section,
)
from packages.helios_parsing.prices import price_tokens
from packages.helios_parsing.resolve import judge
from packages.helios_parsing.segment import BLOCK_TAGS
from packages.helios_parsing.validator import Row, is_addon, norm_tokens, parse_amount, price_label

if TYPE_CHECKING:
    from collections.abc import Sequence

    from packages.helios_parsing.dom_sections import Placed, Signature
    from packages.helios_parsing.output import ExtractorOutput
    from packages.helios_parsing.prices import PriceToken
    from packages.helios_parsing.segment import Block
    from packages.helios_parsing.validator import Validation, Verdict

MIN_SEEDS = 5  # page gate: accepted rows with a name and a price block
MIN_SUPPORT = 3  # seeds a pattern needs ...
MIN_SHARE = 0.1  # ... and this share of the page's seeds
GATE_EXPLAINED = 0.8  # page gate: share of seeds the template explains
GATE_AGREE = 0.8  # page gate: share of explained seeds on the main name path
MAX_NAME = 100  # an added item's name, in characters
MAX_LABEL_WORDS = 4  # a size label's words
LOOKBACK = 8  # blocks from a row back to its record's candidate
MAX_OFFSET = 5  # a pattern's block offset is clipped to ±this; ADD needs a smaller one
WINE_LOOKBACK = 40  # blocks above an added item searched for a wine-list heading
SHORT_HEADING_WORDS = 4  # an unpriced line this short, named by no item, reads as a heading

_LEADERS = re.compile(r"[.…·•_\-–—|:]{2,}|\s[|•·]\s")
_LETTER = re.compile(r"[^\W\d_]")
_ADDON_LINE = re.compile(r"\s*(?:\+|add\b|extra\b|sub\b|substitute\b)", re.IGNORECASE)
_WORD_START = re.compile(r"(?![\W_]*[/|,;])(?=.*[^\W\d_]{3,})")

Loose = tuple[str, ...]  # a block's last block-level tags
Pattern = tuple[Loose, Loose, int, str, int, int]  # name path, price path, offset, lca, levels


@dataclass(frozen=True, slots=True)
class Template:
    """[5d]'s answer for one page: the new row list and what changed (input row indexes)."""

    rows: tuple[Row, ...]
    gated: bool = False
    seeds: int = 0
    explained: float = 0.0  # share of seeds the template explains
    agree: float = 0.0  # share of explained seeds on the main name path
    patterns: int = 0
    dropped: tuple[int, ...] = ()
    attached: tuple[tuple[int, Row], ...] = ()  # input row, the row as a variant of its dish
    renamed: tuple[tuple[int, Row], ...] = ()  # input row, the row on its title
    added: tuple[Row, ...] = ()


def _chain(p: Placed) -> list[tuple[int, str]]:
    return [(nid, t) for nid, (t, _) in zip(p.node_ids, p.stack, strict=True) if t in BLOCK_TAGS]


def _loose(p: Placed) -> Loose:
    return tuple(t for t, _ in signature(p))


def _relation(placed: Sequence[Placed], n: int, p: int) -> tuple[int, str, int, int]:
    if n == p:
        return (0, "self", 0, 0)
    a, b = _chain(placed[n]), _chain(placed[p])
    k = 0
    while k < min(len(a), len(b)) and a[k][0] == b[k][0]:
        k += 1
    lca = a[k - 1][1] if k else "root"
    return (max(-MAX_OFFSET, min(MAX_OFFSET, p - n)), lca, len(a) - k, len(b) - k)


def _container(placed: Sequence[Placed], m: int, pat: Pattern) -> int | None:
    """The node id of the record container of a candidate at block ``m`` under ``pat``."""
    chain = _chain(placed[m])
    k = len(chain) - (1 if pat[2] == 0 else pat[4]) - 1
    return chain[k][0] if k >= 0 else None


def _clean_name(text: str, spans: list[tuple[int, int]]) -> str:
    """A name block's text without its price spans and leader runs."""
    out, at = [], 0
    for s, e in sorted(spans):
        out.append(text[at:s])
        at = e
    out.append(text[at:])
    name = _LEADERS.sub(" ", "".join(out))
    return " ".join(name.split()).strip(" .-–—|:•·$")


def _named_text(block: Block, toks: list[PriceToken]) -> str:
    name = _clean_name(block.text, [(t.start, t.end) for t in toks])
    return name if _LETTER.search(name) and len(name) <= MAX_NAME else ""


def _key(k: int, verdicts: Sequence[Verdict], index: dict[str, int]) -> tuple[int, str]:
    ev = verdicts[k].name_evidence
    assert ev is not None  # noqa: S101 - only kept rows, which ground their name
    return index[ev.block_id], " ".join(norm_tokens(verdicts[k].row.item))


def raw_sections(
    outputs: Sequence[ExtractorOutput], blocks: Sequence[Block]
) -> list[tuple[int, str]]:
    """(block index, model section) of every raw model row, wine rows included, so an ADD
    inside a wine list the pipeline skips is skipped too."""
    index = {b.id: i for i, b in enumerate(blocks)}
    return [
        (index[r.block], s.section)
        for o in outputs
        for s in o.sections
        for r in s.rows
        if r.block in index
    ]


def induce(
    blocks: Sequence[Block],
    placed: Sequence[Placed],
    rows: Sequence[Row],
    verdicts: Sequence[Verdict],
    sections: Sequence[tuple[int, str]] = (),
) -> Template:
    """Stage [5d] over one page: ``placed`` its blocks with DOM context (empty when the
    re-parse differs), ``rows`` and their ``verdicts`` ([5b]'s, one per row), ``sections``
    :func:`raw_sections`."""
    ungated = Template(rows=tuple(rows))
    if not placed or len(placed) != len(blocks):
        return ungated
    index = {b.id: i for i, b in enumerate(blocks)}
    strict = [signature(p) for p in placed]
    paths = [_loose(p) for p in placed]
    prices = price_tokens(list(blocks))
    kept = [
        k for k, v in enumerate(verdicts) if v.decision != "reject" and v.name_evidence is not None
    ]
    seeds: list[tuple[int, int]] = []  # name block, price block
    for k in kept:
        v = verdicts[k]
        if v.decision == "accept" and v.price_evidence is not None:
            seeds.append((_key(k, verdicts, index)[0], index[v.price_evidence.block_id]))
    if len(seeds) < MIN_SEEDS:
        return replace(ungated, seeds=len(seeds))
    support: Counter[Pattern] = Counter(
        (paths[n], paths[p], *_relation(placed, n, p)) for n, p in seeds
    )
    need = max(MIN_SUPPORT, MIN_SHARE * len(seeds))
    # most supported first; ties in a fixed order, so a run never depends on hash order
    template = sorted((p for p, c in support.items() if c >= need), key=lambda q: (-support[q], q))
    explained = sum(support[p] for p in template)
    stats = replace(
        ungated, seeds=len(seeds), explained=explained / len(seeds), patterns=len(template)
    )
    if not template:
        return stats
    by_name: Counter[Loose] = Counter()
    for pat in template:
        by_name[pat[0]] += support[pat]
    stats = replace(stats, agree=by_name.most_common(1)[0][1] / explained)
    if stats.explained < GATE_EXPLAINED or stats.agree < GATE_AGREE:
        return stats
    # Class signatures the seeds' names use, per pattern.
    name_classes: dict[Pattern, set[Signature]] = {}
    for n, p in seeds:
        pat = (paths[n], paths[p], *_relation(placed, n, p))
        if pat in template:
            name_classes.setdefault(pat, set()).add(strict[n])

    def fits(m: int) -> list[Pattern]:
        if blocks[m].in_chrome:
            return []
        out = []
        for pat in template:
            if paths[m] != pat[0]:
                continue
            if pat[2] == 0:
                if prices[m] and _named_text(blocks[m], prices[m]):
                    out.append(pat)
            elif strict[m] in name_classes.get(pat, ()) and not prices[m]:
                out.append(pat)
        return out  # already most supported first

    cand_pats = {m: f for m in range(len(blocks)) if (f := fits(m))}

    def owner(n: int) -> int | None:
        """The candidate whose record holds block ``n``."""
        for m in range(n - 1, max(-1, n - LOOKBACK - 1), -1):
            if m in cand_pats:
                box = _container(placed, m, cand_pats[m][0])
                return m if box is not None and box in placed[n].node_ids else None
        return None

    own_names = {_key(k, verdicts, index) for k in kept}
    title_of: dict[int, str] = {}  # a candidate block -> the item name a kept row gives it
    for k in kept:
        at = _key(k, verdicts, index)[0]
        if at in cand_pats and not _description_like(verdicts[k].row.item):
            title_of.setdefault(at, verdicts[k].row.item)
    priced_titles = {
        _key(k, verdicts, index)[0]
        for k in kept
        if verdicts[k].decision == "accept" and verdicts[k].price_evidence is not None
    }
    drop: set[int] = set()
    attached: list[tuple[int, Row]] = []
    renamed: list[tuple[int, Row]] = []
    for k in kept:
        v = verdicts[k]
        n = _key(k, verdicts, index)[0]
        if n in cand_pats:
            continue
        m = owner(n)
        if m is None:
            continue
        pe = v.price_evidence
        if (
            v.decision == "accept"
            and pe is not None
            and index[pe.block_id] == n
            and len(prices[n]) >= 2
        ):
            tok = next((t for t in prices[n] if t.start == pe.start), None)
            label = price_label(blocks[n].text, prices[n], tok).strip() if tok else ""
            words = set(norm_tokens(v.row.item))
            name = _named_text(blocks[m], prices[m])
            if (
                label
                and len(label.split()) <= MAX_LABEL_WORDS
                and words
                and words <= set(norm_tokens(label))
                and name
            ):
                # ATTACH: the row is the dish's size label; it becomes the dish's variant
                attached.append(
                    (k, replace(v.row, item=name, variant=label, claimed_block=blocks[m].id))
                )
                continue
        amount = v.row.amount
        if prices[n] or (
            amount and re.search(rf"(?<![\d.]){re.escape(amount)}(?![\d])", blocks[n].text)
        ):
            continue  # a line printing its own price is an item line (or several), not a description
        if blocks[n].text.count("|") >= 2:
            continue  # a printed list of names ("Disaronno | Frangelico | ...")
        words = set(norm_tokens(v.row.item))
        if words and words <= set(norm_tokens(blocks[m].text)):
            # RE-NAME: the dish's own title heads this record; the model cited its description
            if (m, " ".join(norm_tokens(v.row.item))) in own_names:
                drop.add(k)  # the title already holds this item: a duplicate
            else:
                renamed.append((k, replace(v.row, claimed_block=blocks[m].id)))
            continue
        if _description_like(blocks[n].text):
            p = index[pe.block_id] if pe is not None else -1
            if (
                v.decision == "accept"
                and m in title_of
                and m not in priced_titles
                and p > m
                and not any(j in cand_pats for j in range(m + 1, p + 1))
            ):
                # RE-NAME: the dish's title is kept unpriced; this description row holds its price
                renamed.append((k, replace(v.row, item=title_of[m], claimed_block=blocks[m].id)))
                continue
            drop.add(k)  # DROP: a description or ingredient line kept as an item
    moved = dict(attached) | dict(renamed)
    named: set[int] = set()
    for k in kept:
        if k in drop:
            continue
        new = moved.get(k)
        named.add(index[new.claimed_block or ""] if new else _key(k, verdicts, index)[0])
    added = _additions(
        blocks,
        placed,
        verdicts,
        [k for k in kept if k not in drop],
        attached,
        sections,
        _Page(index, paths, prices, template, support, cand_pats, named),
    )
    return replace(
        stats,
        rows=tuple(moved.get(k, r) for k, r in enumerate(rows) if k not in drop) + added,
        gated=True,
        dropped=tuple(sorted(drop)),
        attached=tuple(attached),
        renamed=tuple(renamed),
        added=added,
    )


@dataclass(frozen=True, slots=True)
class _Page:
    """What ADD reads of an induced page."""

    index: dict[str, int]
    paths: list[Loose]
    prices: list[list[PriceToken]]
    template: list[Pattern]  # most supported first
    support: Counter[Pattern]
    cand_pats: dict[int, list[Pattern]]
    named: set[int]  # name blocks of kept rows, after the moves


def _additions(
    blocks: Sequence[Block],
    placed: Sequence[Placed],
    verdicts: Sequence[Verdict],
    kept: list[int],
    attached: list[tuple[int, Row]],
    raw: Sequence[tuple[int, str]],
    pg: _Page,
) -> tuple[Row, ...]:
    """ADD: template price lines no kept row cites become items."""
    index, prices, named, cand_pats = pg.index, pg.prices, pg.named, pg.cand_pats
    # (block, section) of kept rows; a None section sorts as "" (ties keep row order)
    sections = sorted(
        ((_key(k, verdicts, index)[0], verdicts[k].row.section) for k in kept),
        key=lambda x: (x[0], x[1] or ""),
    )
    # Spans a kept item already covers (its name block to its price block).
    covered: set[int] = set()
    for k in kept:
        v = verdicts[k]
        if v.price_evidence is not None and v.name_evidence is not None:
            a, b = index[v.name_evidence.block_id], index[v.price_evidence.block_id]
            covered |= set(range(min(a, b), max(a, b) + 1))
    # (name tokens, amount) the page already holds: a menu printed twice (desktop and
    # mobile copies, tabs) is one menu; the same dish at the same price is not added again.
    held = {
        (frozenset(norm_tokens(verdicts[k].row.item)), parse_amount(verdicts[k].row.amount))
        for k in kept
    } | {(frozenset(norm_tokens(r.item)), parse_amount(r.amount)) for _, r in attached}
    raw_at = sorted(raw)
    priced_named = {
        _key(k, verdicts, index)[0]
        for k in kept
        if verdicts[k].decision == "accept" and verdicts[k].price_evidence is not None
    }
    unpriced_named = named - priced_named

    def under_wine(m: int) -> bool:
        """The nearest heading-like line above (an h1-h6 block, or a short unpriced line no
        item names) is a wine-list heading: wine lists are out of scope (Amendment 15)."""
        for j in range(m - 1, max(-1, m - WINE_LOOKBACK), -1):
            b = blocks[j]
            if prices[j] or j in named or b.in_chrome:
                continue
            if b.heading or (len(b.text.split()) <= SHORT_HEADING_WORDS and j not in cand_pats):
                return wine_section(b.text)
        return False

    def skipped(m: int, q: int, pat: Pattern) -> bool:
        if not 0 <= m < len(blocks) or pat not in cand_pats.get(m, ()):
            return True  # no name block in the template position
        if _relation(placed, m, q) != pat[2:]:
            return True  # the name and price blocks relate otherwise
        if m in named or q in covered or m in covered:
            return True  # inside a kept item (so no kept row cites its price)
        if any(is_addon(blocks[q], t) for t in prices[q]) or _ADDON_LINE.match(blocks[m].text):
            return True
        name = _named_text(blocks[m], prices[m])
        if not name or not _WORD_START.match(name) or _description_like(name):
            return True  # the name is not a title
        if len(prices[m]) >= 2 and set(norm_tokens(name)) <= {
            w for t in prices[m] for w in norm_tokens(price_label(blocks[m].text, prices[m], t))
        }:
            return True  # a price line ("Medium $2.99, Large $3.99"), not a name
        if any(j in unpriced_named for j in (m - 1, m - 2)):
            return True  # the price belongs to the dish named just above, kept unpriced
        return under_wine(m)

    picks: dict[int, int] = {}  # price block -> name block
    for pat in pg.template:
        if abs(pat[2]) >= MAX_OFFSET:
            continue
        for q in range(len(blocks)):
            if q in picks or not prices[q] or pg.paths[q] != pat[1] or blocks[q].in_chrome:
                continue
            if not skipped(q - pat[2], q, pat):
                picks[q] = q - pat[2]
    added: list[Row] = []
    for q, m in sorted(picks.items(), key=lambda x: x[1]):
        name = _named_text(blocks[m], prices[m])
        if any((frozenset(norm_tokens(name)), t.amount) in held for t in prices[q]):
            continue  # the same name and price are already held
        raw_sec = None
        for at, sec in raw_at:
            if at > m:
                break
            raw_sec = sec
        if wine_section(raw_sec):
            continue
        section = None
        for at, s in sections:
            if at > m:
                break
            section = s
        multi = len(prices[q]) > 1
        for t in prices[q]:
            label = price_label(blocks[q].text, prices[q], t).strip() if multi else ""
            if q == m and label and set(norm_tokens(label)) >= set(norm_tokens(name)):
                label = ""  # the name itself, not a size label
            if len(label.split()) > MAX_LABEL_WORDS:
                label = ""
            added.append(
                Row(
                    item=name,
                    amount=str(t.amount),
                    variant=label or None,
                    section=section,
                    claimed_block=blocks[m].id,
                )
            )
    return tuple(strip_diet_marks(added))


def remove_duplicates(verdicts: Sequence[Verdict]) -> tuple[Verdict, ...]:
    """The verdicts without the rows of extra copies of a printed item (rule "same").

    A printed item is its name block and normalized name; a copy is its rows under one of
    the model's sections. The first section's rows (reading order) stay, and the others go
    only when every copy cites the same non-empty set of printed price spans."""
    groups: dict[tuple[str, str], dict[str, list[int]]] = {}
    for k, v in enumerate(verdicts):
        if v.decision == "reject" or v.name_evidence is None:
            continue
        key = (v.name_evidence.block_id, " ".join(norm_tokens(v.row.item)))
        groups.setdefault(key, {}).setdefault(v.row.section or "", []).append(k)
    drop: set[int] = set()
    for by_section in groups.values():
        if len(by_section) < 2:
            continue
        spans = {
            frozenset(
                pe.locator
                for k in ks
                if verdicts[k].decision == "accept" and (pe := verdicts[k].price_evidence)
            )
            for ks in by_section.values()
        }
        if len(spans) > 1:
            continue  # a copy cites another printed price: a second dish, not a copy
        if not next(iter(spans)):
            continue  # no copy cites a price: a second print may be grounded onto the first
        first = min(by_section.values(), key=min)
        drop |= {k for ks in by_section.values() if ks is not first for k in ks}
    return tuple(v for k, v in enumerate(verdicts) if k not in drop)


@dataclass(frozen=True, slots=True)
class LlmStream:
    """The ``llm`` stream's interpretation of one page: what Menu stores and why."""

    validation: Validation  # the verdicts shape files (duplicates removed)
    template: Template  # [5d]'s answer
    duplicates: int  # rows duplicate removal took out
    sections: DomSections  # [5c]'s answer on the final verdicts


def llm_stream(blocks: Sequence[Block], outputs: Sequence[ExtractorOutput], html: str) -> LlmStream:
    """``rows_of`` → [5]+[5b] → [5d] → [5]+[5b] → duplicate removal → [5c], on one page."""
    rows = rows_of(outputs, blocks)
    first = judge(blocks, rows)
    placed = placed_blocks(html)
    if tuple(p.block for p in placed) != tuple(blocks):
        placed = []
    template = induce(blocks, placed, rows, first.verdicts, raw_sections(outputs, blocks))
    judged = judge(blocks, list(template.rows)) if template.gated else first
    kept = remove_duplicates(judged.verdicts)
    return LlmStream(
        validation=replace(judged, verdicts=kept),
        template=template,
        duplicates=len(judged.verdicts) - len(kept),
        sections=assign(html, blocks, kept, placed or None),
    )
