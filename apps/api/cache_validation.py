"""HTTP validation of freshly read JSON, without a resident response cache (ADR-0023)."""

from __future__ import annotations

import hashlib
import json
import re
from typing import TYPE_CHECKING, Any

from fastapi.routing import APIRoute
from starlette.responses import Response

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from starlette.requests import Request

_TAG = r'(?:W/)?"[\x21\x23-\x7e\x80-\xff]*"'
_TAG_LIST = re.compile(rf"\s*{_TAG}\s*(?:,\s*{_TAG}\s*)*")
_TAGS = re.compile(_TAG)


def _matches(condition: str, etag: str) -> bool:
    """GET uses weak comparison. Commas inside an opaque tag are not separators."""
    if condition.strip() == "*":
        return True
    if _TAG_LIST.fullmatch(condition) is None:
        return False
    return any(
        tag.removeprefix("W/") == etag.removeprefix("W/") for tag in _TAGS.findall(condition)
    )


def _without_ages(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _without_ages(item) for key, item in value.items() if key != "age_seconds"}
    if isinstance(value, list):
        return [_without_ages(item) for item in value]
    return value


class ValidatedRoute(APIRoute):
    """Validate after the route reads/serializes current data, including empty menus.

    Gold refresh minima cannot detect every correction/withdrawal. Hash all
    stable fields instead; only ages and history's request-time as_of are
    presentation clocks. Weak validators deliberately preserve that distinction.
    """

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def validated(request: Request) -> Response:
            response = await handler(request)
            if request.method != "GET" or response.status_code != 200:
                return response
            value = _without_ages(json.loads(bytes(response.body)))
            if self.path.endswith("/price-history"):
                value.pop("as_of", None)
            representation = json.dumps(
                {
                    "path": request.url.path,
                    "query": sorted(request.query_params.multi_items()),
                    "body": value,
                },
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode()
            etag = f'W/"{hashlib.sha256(representation).hexdigest()}"'
            response.headers["ETag"] = etag
            response.headers["Cache-Control"] = "public, no-cache"
            if _matches(request.headers.get("If-None-Match", ""), etag):
                return Response(
                    status_code=304,
                    headers={
                        name: value
                        for name, value in response.headers.items()
                        if name.lower() not in {"content-type", "content-length"}
                    },
                )
            return response

        return validated
