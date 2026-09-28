"""Pure validation and canonical provenance values (ADR-0011)."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit


def canonicalize_http_url(url: str) -> str:
    """Return a deliberately conservative canonical HTTP(S) URL.

    Scheme and host case, an empty path, default ports, and fragments are not
    resource identity.  Path escaping, query ordering, and trailing slashes
    are left untouched because normalizing those can merge distinct source
    resources.
    """
    candidate = url.strip()
    if not candidate or any(character.isspace() for character in candidate):
        raise ValueError("canonical URL must be nonblank and contain no whitespace")

    parsed = urlsplit(candidate)
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"} or parsed.hostname is None:
        raise ValueError("canonical URL must be an absolute HTTP(S) URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("canonical URL must not contain user information")

    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("canonical URL has an invalid port") from exc

    try:
        host = parsed.hostname.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise ValueError("canonical URL has an invalid host") from exc
    if ":" in host:
        host = f"[{host}]"

    default_port = (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    netloc = host if port is None or default_port else f"{host}:{port}"
    path = parsed.path or "/"
    return urlunsplit((scheme, netloc, path, parsed.query, ""))


def canonicalize_source_url(url: str) -> str:
    """Normalize an acquisition location without making it an identity key."""
    candidate = url.strip()
    scheme = candidate.split(":", 1)[0].lower()
    if scheme in {"http", "https"}:
        return canonicalize_http_url(candidate)
    if scheme == "repo":
        path = candidate[5:]
        if (
            not path
            or path.startswith("/")
            or "\\" in path
            or any(part in {"", ".", ".."} for part in path.split("/"))
            or any(c.isspace() for c in path)
        ):
            raise ValueError("repo endpoint requires a relative POSIX path")
        return f"repo:{path}"
    if scheme == "s3":
        # '?' is a glob character here, not an HTTP query delimiter.
        match = re.fullmatch(r"s3://([A-Za-z0-9.-]+)/(.+)", candidate, re.IGNORECASE)
        if match is None or any(c.isspace() for c in candidate) or "#" in candidate:
            raise ValueError("s3 endpoint requires a bucket and key prefix")
        bucket, path = match.groups()
        glob = re.search(r"[*?\[]", path)
        if glob:
            path = (
                path[: glob.start()].rsplit("/", 1)[0] + "/" if "/" in path[: glob.start()] else ""
            )
        if not path or any(p in {".", ".."} for p in path.split("/")):
            raise ValueError("s3 endpoint requires a nonempty key prefix")
        return f"s3://{bucket.lower()}/{path.rstrip('/')}/"
    raise ValueError("source URL must use http, https, s3, or repo")


_SEGMENT = re.compile(r"\.([A-Za-z_][A-Za-z_0-9]*)|\[([0-9]+)\]|\[('(?:[^'\\]+)'(?:,'[^'\\]+')*)\]")


def excerpt_hash(payload: object, locator: str) -> str:
    """Hash the canonical JSON array selected by the restricted JSONPath."""
    if not locator.startswith("$") or len(locator) == 1:
        raise ValueError("Evidence locator requires a JSONPath field path")
    values: list[Any] = [payload]
    offset = 1
    while offset < len(locator):
        match = _SEGMENT.match(locator, offset)
        if match is None:
            raise ValueError("unsupported Evidence JSONPath")
        name, index, names = match.groups()
        keys = [name] if name else re.findall(r"'([^']+)'", names or "")
        if len(keys) > 1 and match.end() != len(locator):
            raise ValueError("JSONPath union must be the last segment")
        selected: list[Any] = []
        for value in values:
            if index is not None:
                if isinstance(value, list) and int(index) < len(value):
                    selected.append(value[int(index)])
            elif isinstance(value, dict):
                selected.extend(value[key] for key in keys if key in value)
        values = selected
        offset = match.end()
    if not values:
        raise ValueError("Evidence locator selects no values")
    encoded = json.dumps(
        values, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
    return "sha256:" + hashlib.sha256(encoded.encode()).hexdigest()


REJECTION_REASONS = frozenset({"blank_name", "name_without_letters_or_digits", "name_too_long"})
SKIP_REASONS = frozenset(
    {
        "robots_disallowed",
        "robots_unavailable",
        "crawl_delay_too_long",
        "non_public_host",
        "redirect_refused",
        "platform_root",
        "social_link",
    }
)
FAILURE_REASONS = frozenset({"network_error", "too_large", "not_html", "no_menu_found"})


def validate_outcome(outcome: str, reason: str | None) -> None:
    valid = (
        (outcome == "succeeded" and reason is None)
        or (outcome == "rejected" and reason in REJECTION_REASONS)
        or (outcome == "skipped" and reason in SKIP_REASONS)
        or (
            outcome == "failed"
            and (
                reason in FAILURE_REASONS
                or re.fullmatch(r"http_[45][0-9]{2}", reason or "") is not None
            )
        )
    )
    if not valid:
        raise ValueError("invalid capture outcome/reason pair")
