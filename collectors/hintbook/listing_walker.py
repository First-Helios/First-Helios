"""
Shared article-listing walker.

Most food-deal aggregators follow a WordPress-style pattern: a listing page
with article cards (h2/h3 links), each pointing to a per-deal post. This
helper keeps adapters small and consistent.
"""

from __future__ import annotations

from datetime import date
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from collectors.hintbook.fetcher import fetch
from collectors.hintbook.models import (
    AggregatorRecord,
    ExpectationProposal,
    HarvestReport,
    HintProposal,
    utcnow,
)
from collectors.hintbook.parsing import (
    derive_flags,
    extract_outbound_domain,
    first_price,
    first_promo_code,
    normalize_brand_hint,
    parse_valid_through,
    text_of,
)


def _article_links(soup: BeautifulSoup, base: str, aggregator_host: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for h in soup.find_all(["h2", "h3"]):
        a = h.find("a", href=True)
        if not a:
            continue
        href = urljoin(base, a["href"])
        host = urlparse(href).netloc.lower()
        if aggregator_host not in host:
            continue
        if href in seen:
            continue
        seen.add(href)
        out.append((text_of(a), href))
    # Fallback for sites that put card links at a[class*=card] or a[class*=deal]
    if len(out) < 3:
        for a in soup.find_all("a", href=True):
            cls = " ".join(a.get("class", []))
            if not any(tok in cls.lower() for tok in ("card", "deal", "post")):
                continue
            href = urljoin(base, a["href"])
            host = urlparse(href).netloc.lower()
            if aggregator_host not in host:
                continue
            if href in seen:
                continue
            seen.add(href)
            out.append((text_of(a)[:200] or href, href))
    return out


def parse_article_html(
    html: str, article_url: str, aggregator_name: str, aggregator_host: str, industry: str,
) -> AggregatorRecord | None:
    """Public entry point for parsing a single aggregator article/listing HTML.

    Used by both the live listing walker and by offline replay paths (e.g.
    Spirit Pool dev-capture bundles) that want to extract the same
    AggregatorRecord shape without re-fetching the web.
    """
    return _parse_article(html, article_url, aggregator_name, aggregator_host, industry)


def derive_proposals_from_record(
    record: AggregatorRecord,
) -> tuple[HintProposal | None, ExpectationProposal | None]:
    """Public entry point to derive registry proposals from an AggregatorRecord."""
    return _derive_proposals(record)


def _parse_article(
    html: str, article_url: str, aggregator_name: str, aggregator_host: str, industry: str,
) -> AggregatorRecord | None:
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    headline = text_of(h1) or text_of(soup.find("title"))
    if not headline:
        return None

    article_tag = soup.find("article") or soup.find("main") or soup
    body_parts: list[str] = []
    for p in article_tag.find_all("p", limit=8):
        t = text_of(p)
        if len(t) > 30:
            body_parts.append(t)
        if sum(len(x) for x in body_parts) > 600:
            break
    body_excerpt = " ".join(body_parts)[:600]

    brand_hint = normalize_brand_hint(headline)
    target_domain, target_url = extract_outbound_domain(
        article_tag if hasattr(article_tag, "find_all") else soup,
        aggregator_host,
        brand_hint=brand_hint,
    )

    return AggregatorRecord(
        aggregator=aggregator_name,
        fetched_at=utcnow(),
        source_url=article_url,
        industry=industry,
        brand_hint=brand_hint,
        target_domain=target_domain,
        target_first_party_url=target_url,
        headline=headline[:240],
        body_excerpt=body_excerpt,
        price_hint=first_price(body_excerpt) or first_price(headline),
        promo_code=first_promo_code(body_excerpt),
        valid_through=parse_valid_through(body_excerpt),
        flags=derive_flags(f"{headline} {body_excerpt}"),
    )


def _derive_proposals(
    record: AggregatorRecord,
) -> tuple[HintProposal | None, ExpectationProposal | None]:
    if not record.brand_hint or not record.target_domain:
        return None, None

    slug = None
    if record.target_first_party_url:
        path = urlparse(record.target_first_party_url).path
        if path and path != "/" and len(path) < 80:
            slug = path

    hint: HintProposal | None = None
    if slug and slug.strip("/"):
        hint = HintProposal(
            brand=record.brand_hint,
            hint_type="corporate_promo_slug",
            slug=slug,
            target_domain=record.target_domain,
            source=record.aggregator,
            source_url=record.source_url,
            first_seen=date.today(),
            verified_against_url=None,
            notes=f"Outbound link from aggregator article: {record.headline[:120]}",
        )

    match_any: list[str] = []
    if record.price_hint:
        match_any.append(f"${record.price_hint:.2f}")
    if record.promo_code:
        match_any.append(record.promo_code)
    for flag_kw in ("bogo", "happy hour", "kids eat free", "free", "% off", "buy one"):
        if flag_kw in (record.headline + " " + record.body_excerpt).lower():
            match_any.append(flag_kw)

    expectation = ExpectationProposal(
        brand=record.brand_hint,
        target_domain=record.target_domain,
        expected_label=record.headline[:200],
        match_any=tuple(dict.fromkeys(match_any)),
        source=record.aggregator,
        source_url=record.source_url,
        first_seen=date.today(),
        page_path_hints=(slug,) if slug else (),
        notes=None,
    )
    return hint, expectation


def run_listing_walk(
    *,
    report: HarvestReport,
    adapter_name: str,
    aggregator_host: str,
    seeds: list[str],
    industry: str = "food",
    max_articles: int = 60,
    ttl_hours: float = 24.0,
) -> None:
    """Walk listing seeds, parse article pages, append to report."""
    report.adapters_run.append(adapter_name)
    discovered: list[tuple[str, str]] = []
    for seed in seeds:
        html, status, err = fetch(seed, ttl_hours=ttl_hours)
        if html is None:
            report.adapters_failed.append({
                "adapter": adapter_name, "url": seed, "status": status, "error": err,
            })
            continue
        soup = BeautifulSoup(html, "html.parser")
        discovered.extend(_article_links(soup, seed, aggregator_host))

    seen: set[str] = set()
    unique: list[tuple[str, str]] = []
    for headline, url in discovered:
        if url in seen:
            continue
        seen.add(url)
        unique.append((headline, url))
    unique = unique[:max_articles]

    for headline, url in unique:
        html, status, err = fetch(url, ttl_hours=ttl_hours)
        if html is None:
            report.adapters_failed.append({
                "adapter": adapter_name, "url": url, "status": status, "error": err,
            })
            continue
        rec = _parse_article(html, url, adapter_name, aggregator_host, industry)
        if rec is None:
            continue
        report.records.append(rec)
        hint, expectation = _derive_proposals(rec)
        if hint:
            report.hint_proposals.append(hint)
        if expectation:
            report.expectation_proposals.append(expectation)
