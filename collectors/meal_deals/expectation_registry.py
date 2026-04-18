"""Expectation-only audit registry for replay bundle coverage checks.

This layer answers a different question than the hint registry.

Hints:
  * tell the scraper where it may be worth looking
  * are exploration-only

Expectations:
  * say what an external published source claims should exist
  * are quality-check-only
  * are compared against first-party replay bundles
  * NEVER count as first-party evidence for ingest

The goal is to convert chat-level "we should be able to find this deal" claims
into a durable, replayable audit artifact that can report:

  * found
  * missed
  * not_testable
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from html import unescape
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

DEFAULT_REGISTRY_PATH = Path("config/meal_deal_expectation_registry.json")
SCHEMA_VERSION = "expectation_registry.v1"
EXPECTATION_SCOPE = "quality_check"

_REQUIRED_FIELDS = (
    "id",
    "brand",
    "target_domain",
    "expected_label",
    "source",
    "source_url",
    "first_seen",
    "last_verified",
    "expires_at",
)


@dataclass(frozen=True)
class Expectation:
    """A published-deal expectation used only for replay quality checks."""

    id: str
    brand: str
    target_domain: str
    expected_label: str
    source: str
    source_url: str
    first_seen: date
    last_verified: date
    expires_at: date
    page_path_hints: tuple[str, ...] = ()
    match_any: tuple[str, ...] = ()
    notes: str | None = None
    scope: str = EXPECTATION_SCOPE

    def is_expired(self, *, as_of: date | None = None) -> bool:
        return (as_of or date.today()) > self.expires_at

    @property
    def match_terms(self) -> tuple[str, ...]:
        seen: set[str] = set()
        ordered: list[str] = []
        for raw in (self.expected_label, *self.match_any):
            normalized = _normalize_text(raw)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            ordered.append(normalized)
        return tuple(ordered)


def load_expectations(
    *,
    path: Path | str | None = None,
    as_of: date | None = None,
    include_expired: bool = False,
) -> list[Expectation]:
    """Load and validate the expectation registry."""

    registry_path = Path(path) if path else DEFAULT_REGISTRY_PATH
    if not registry_path.exists():
        logger.debug("[ExpectationRegistry] registry file missing at %s", registry_path)
        return []

    raw = json.loads(registry_path.read_text(encoding="utf-8"))
    version = raw.get("schema_version")
    if version != SCHEMA_VERSION:
        raise ValueError(
            f"expectation registry schema_version {version!r} does not match expected {SCHEMA_VERSION!r}"
        )

    expectations: list[Expectation] = []
    for entry in raw.get("expectations", []):
        missing = [field for field in _REQUIRED_FIELDS if not entry.get(field)]
        if missing:
            raise ValueError(
                f"expectation registry entry {entry.get('id', '<unknown>')} missing required fields: {missing}"
            )

        page_path_hints = _coerce_string_list(entry.get("page_path_hints"), field_name="page_path_hints")
        match_any = _coerce_string_list(entry.get("match_any"), field_name="match_any")

        expectation = Expectation(
            id=entry["id"],
            brand=str(entry["brand"]).lower(),
            target_domain=_normalize_host(str(entry["target_domain"])),
            expected_label=str(entry["expected_label"]),
            source=str(entry["source"]),
            source_url=str(entry["source_url"]),
            first_seen=_parse_date(str(entry["first_seen"])),
            last_verified=_parse_date(str(entry["last_verified"])),
            expires_at=_parse_date(str(entry["expires_at"])),
            page_path_hints=tuple(page_path_hints),
            match_any=tuple(match_any),
            notes=entry.get("notes"),
        )
        if not include_expired and expectation.is_expired(as_of=as_of):
            continue
        expectations.append(expectation)

    return expectations


def find_expectations(
    expectations: Iterable[Expectation],
    *,
    brand: str | None = None,
    target_domain: str | None = None,
) -> list[Expectation]:
    brand_l = brand.lower() if brand else None
    domain_l = _normalize_host(target_domain) if target_domain else None

    matches: list[Expectation] = []
    for expectation in expectations:
        if brand_l and expectation.brand != brand_l:
            continue
        if domain_l and expectation.target_domain != domain_l:
            continue
        matches.append(expectation)
    return matches


def compare_expectations_to_bundles(
    expectations: Iterable[Expectation],
    debug_bundles: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    results = [
        compare_expectation_to_bundles(expectation, debug_bundles)
        for expectation in expectations
    ]
    return sorted(
        results,
        key=lambda item: (
            str(item.get("brand") or ""),
            str(item.get("target_domain") or ""),
            str(item.get("expected_label") or ""),
            str(item.get("expectation_id") or ""),
        ),
    )


def compare_expectation_to_bundles(
    expectation: Expectation,
    debug_bundles: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    candidate_bundles = [
        bundle
        for bundle in debug_bundles.values()
        if _bundle_matches_target_domain(bundle, expectation.target_domain)
    ]

    candidate_bundle_keys = _unique_strings(
        str(bundle.get("site_key") or "")
        for bundle in candidate_bundles
        if bundle.get("site_key")
    )
    candidate_site_urls = _unique_strings(
        str(bundle.get("site_url") or "")
        for bundle in candidate_bundles
        if bundle.get("site_url")
    )

    fetched_hint_urls: list[str] = []
    discovered_hint_urls: list[str] = []
    matched_signals: list[dict[str, Any]] = []
    matched_pages: list[dict[str, Any]] = []

    for bundle in candidate_bundles:
        bundle_urls = _bundle_urls(bundle)
        fetched_hint_urls.extend(
            url for url in bundle_urls["fetched"]
            if _url_matches_path_hints(url, expectation.page_path_hints)
        )
        discovered_hint_urls.extend(
            url for url in bundle_urls["discovered_only"]
            if _url_matches_path_hints(url, expectation.page_path_hints)
        )
        matched_signals.extend(_matching_signals(bundle, expectation.match_terms))
        matched_pages.extend(_matching_pages(bundle, expectation.match_terms))

    fetched_hint_urls = _unique_strings(fetched_hint_urls)
    discovered_hint_urls = _unique_strings(discovered_hint_urls)
    matched_signals = _dedupe_match_records(matched_signals, keys=("deal_name", "source_url"))
    matched_pages = _dedupe_match_records(matched_pages, keys=("url", "fetch_type"))

    page_hint_status = _page_hint_status(
        page_path_hints=expectation.page_path_hints,
        fetched_hint_urls=fetched_hint_urls,
        discovered_hint_urls=discovered_hint_urls,
    )

    if matched_signals or matched_pages:
        status = "found"
        if matched_signals and matched_pages:
            reason = "signal_and_page_match"
        elif matched_signals:
            reason = "signal_match"
        else:
            reason = "page_html_match"
    elif not candidate_bundles:
        status = "not_testable"
        reason = "no_matching_bundle"
    elif expectation.page_path_hints:
        if fetched_hint_urls:
            status = "missed"
            reason = "page_hint_fetched_but_phrase_missing"
        elif discovered_hint_urls:
            status = "not_testable"
            reason = "page_hint_discovered_only"
        else:
            status = "not_testable"
            reason = "page_hint_missing"
    elif _bundles_have_fetched_content(candidate_bundles):
        status = "missed"
        reason = "bundle_present_but_phrase_missing"
    else:
        status = "not_testable"
        reason = "bundle_has_no_fetched_content"

    return {
        "expectation_id": expectation.id,
        "brand": expectation.brand,
        "target_domain": expectation.target_domain,
        "expected_label": expectation.expected_label,
        "status": status,
        "reason": reason,
        "scope": expectation.scope,
        "source": expectation.source,
        "source_url": expectation.source_url,
        "page_path_hints": list(expectation.page_path_hints),
        "match_terms": list(expectation.match_terms),
        "page_hint_status": page_hint_status,
        "candidate_bundle_count": len(candidate_bundles),
        "candidate_bundle_keys": candidate_bundle_keys,
        "candidate_site_urls": candidate_site_urls,
        "fetched_page_hint_urls": fetched_hint_urls,
        "discovered_page_hint_urls": discovered_hint_urls,
        "matched_signals": matched_signals,
        "matched_pages": matched_pages,
        "notes": expectation.notes,
    }


def build_expectation_report(
    expectations: Iterable[Expectation],
    debug_bundles: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    results = compare_expectations_to_bundles(expectations, debug_bundles)
    status_counts = Counter(result["status"] for result in results)
    reason_counts = Counter(result["reason"] for result in results)
    hint_status_counts = Counter(result["page_hint_status"] for result in results)
    brand_counts = Counter(result["brand"] for result in results)

    return {
        "summary": {
            "expectations": len(results),
            "debug_bundles": len(debug_bundles),
            "status_counts": dict(status_counts),
            "reason_counts": dict(reason_counts),
            "page_hint_status_counts": dict(hint_status_counts),
            "brands": dict(brand_counts),
        },
        "results": results,
    }


def _bundle_matches_target_domain(bundle: dict[str, Any], target_domain: str) -> bool:
    site_url = str(bundle.get("site_url") or "")
    host = _normalize_host(urlparse(site_url).netloc or site_url)
    if not host:
        site_key = str(bundle.get("site_key") or "")
        host = _normalize_host(site_key)
    return host == target_domain or host.endswith(f".{target_domain}")


def _bundle_urls(bundle: dict[str, Any]) -> dict[str, list[str]]:
    fetched_urls: list[str] = []
    discovered_only: list[str] = []

    site_url = bundle.get("site_url")
    if isinstance(site_url, str) and site_url:
        fetched_urls.append(site_url)

    pages = bundle.get("pages") if isinstance(bundle.get("pages"), dict) else {}
    for page in pages.values():
        if not isinstance(page, dict):
            continue
        page_url = page.get("url")
        if isinstance(page_url, str) and page_url:
            fetched_urls.append(page_url)

    signals = bundle.get("signals") if isinstance(bundle.get("signals"), list) else []
    for signal in signals:
        if not isinstance(signal, dict):
            continue
        source_url = signal.get("source_url")
        if isinstance(source_url, str) and source_url:
            fetched_urls.append(source_url)

    discovered_pages = bundle.get("discovered_pages") if isinstance(bundle.get("discovered_pages"), list) else []
    for page_url in discovered_pages:
        if isinstance(page_url, str) and page_url:
            discovered_only.append(page_url)

    hinted_pages = bundle.get("hinted_pages") if isinstance(bundle.get("hinted_pages"), list) else []
    for page in hinted_pages:
        if not isinstance(page, dict):
            continue
        page_url = page.get("url")
        if isinstance(page_url, str) and page_url:
            discovered_only.append(page_url)

    return {
        "fetched": _unique_strings(fetched_urls),
        "discovered_only": _unique_strings(discovered_only),
    }


def _matching_signals(bundle: dict[str, Any], match_terms: tuple[str, ...]) -> list[dict[str, Any]]:
    if not match_terms:
        return []

    matches: list[dict[str, Any]] = []
    signals = bundle.get("signals") if isinstance(bundle.get("signals"), list) else []
    for signal in signals:
        if not isinstance(signal, dict):
            continue
        text = _normalize_text(
            " ".join(
                str(signal.get(field) or "")
                for field in ("deal_name", "deal_description", "raw_scraped_text")
            )
        )
        matched_terms = [term for term in match_terms if term and term in text]
        if not matched_terms:
            continue
        matches.append(
            {
                "deal_name": str(signal.get("deal_name") or ""),
                "source_url": str(signal.get("source_url") or ""),
                "matched_terms": matched_terms,
            }
        )
    return matches


def _matching_pages(bundle: dict[str, Any], match_terms: tuple[str, ...]) -> list[dict[str, Any]]:
    if not match_terms:
        return []

    matches: list[dict[str, Any]] = []
    pages = bundle.get("pages") if isinstance(bundle.get("pages"), dict) else {}
    for page in pages.values():
        if not isinstance(page, dict):
            continue
        html = page.get("html")
        if not isinstance(html, str) or not html:
            continue
        text = _normalize_text(html)
        matched_terms = [term for term in match_terms if term and term in text]
        if not matched_terms:
            continue
        matches.append(
            {
                "url": str(page.get("url") or ""),
                "fetch_type": str(page.get("fetch_type") or "unknown"),
                "matched_terms": matched_terms,
            }
        )
    return matches


def _bundles_have_fetched_content(bundles: list[dict[str, Any]]) -> bool:
    for bundle in bundles:
        pages = bundle.get("pages") if isinstance(bundle.get("pages"), dict) else {}
        signals = bundle.get("signals") if isinstance(bundle.get("signals"), list) else []
        if pages or signals:
            return True
    return False


def _page_hint_status(
    *,
    page_path_hints: tuple[str, ...],
    fetched_hint_urls: list[str],
    discovered_hint_urls: list[str],
) -> str:
    if not page_path_hints:
        return "not_applicable"
    if fetched_hint_urls:
        return "fetched"
    if discovered_hint_urls:
        return "discovered_only"
    return "missing"


def _url_matches_path_hints(url: str, path_hints: tuple[str, ...]) -> bool:
    if not path_hints:
        return False
    parsed = urlparse(url or "")
    path = (parsed.path or "").lower()
    normalized_url = url.lower()
    for hint in path_hints:
        normalized_hint = _normalize_path_hint(hint)
        if not normalized_hint:
            continue
        if normalized_hint in path or normalized_hint in normalized_url:
            return True
    return False


def _normalize_host(value: str | None) -> str:
    if not value:
        return ""
    candidate = str(value).strip().lower()
    parsed = urlparse(candidate if "://" in candidate else f"https://{candidate}")
    host = (parsed.netloc or parsed.path or "").lower().strip()
    if host.startswith("www."):
        host = host[4:]
    return host.rstrip("/")


def _normalize_path_hint(value: str) -> str:
    candidate = str(value or "").strip().lower()
    if not candidate:
        return ""
    parsed = urlparse(candidate)
    if parsed.scheme or parsed.netloc:
        candidate = parsed.path or candidate
    if not candidate.startswith("/"):
        candidate = f"/{candidate.lstrip('/')}"
    return candidate.rstrip("/") or "/"


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    text = unescape(str(value)).lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _coerce_string_list(value: Any, *, field_name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list of strings")
    output: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"{field_name} must be a list of strings")
        cleaned = item.strip()
        if cleaned:
            output.append(cleaned)
    return output


def _unique_strings(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _dedupe_match_records(records: list[dict[str, Any]], *, keys: tuple[str, ...]) -> list[dict[str, Any]]:
    seen: set[tuple[str, ...]] = set()
    ordered: list[dict[str, Any]] = []
    for record in records:
        signature = tuple(str(record.get(key) or "") for key in keys)
        if signature in seen:
            continue
        seen.add(signature)
        ordered.append(record)
    return ordered