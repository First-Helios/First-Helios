"""
backend/tracked_request.py

Thin wrapper around requests.get / requests.post that automatically logs
every call through rate_manager.  Drop-in replacement for scrapers.

Usage:
    from backend.tracked_request import tracked_get, tracked_post

    resp = tracked_get(
        "bls_v1", "series_fetch",
        url, headers=headers, timeout=30,
    )

Also provides `check_budget()` for pre-flight checks and
`log_external()` for non-requests calls (DuckDB, geopy, libraries).
"""

import logging
import time
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)

# Late import to avoid circular
_mgr = None


def _get_mgr():
    global _mgr
    if _mgr is None:
        from backend.rate_manager import rate_manager
        _mgr = rate_manager
    return _mgr


def check_budget(source_key: str, count: int = 1) -> bool:
    """Return True if the daily budget has room."""
    return _get_mgr().can_request(source_key, count)


def tracked_get(
    source_key: str,
    request_type: str,
    url: str,
    *,
    params: Optional[dict] = None,
    data_items: Optional[int] = None,
    **kwargs,
) -> requests.Response:
    """requests.get() with automatic rate tracking.

    Raises the same exceptions requests.get would raise.
    """
    mgr = _get_mgr()
    t0 = time.time()
    error_msg = None
    status_code = None
    resp_bytes = None
    success = False

    try:
        resp = requests.get(url, params=params, **kwargs)
        status_code = resp.status_code
        resp_bytes = len(resp.content) if resp.content else 0
        success = resp.ok
        if not resp.ok:
            error_msg = f"HTTP {resp.status_code}"
        return resp
    except Exception as e:
        error_msg = str(e)[:500]
        raise
    finally:
        latency = int((time.time() - t0) * 1000)
        mgr.log_request(
            source_key=source_key,
            request_type=request_type,
            url=url,
            method="GET",
            status_code=status_code,
            success=success,
            error_message=error_msg,
            latency_ms=latency,
            response_bytes=resp_bytes,
            data_items=data_items,
        )


def tracked_post(
    source_key: str,
    request_type: str,
    url: str,
    *,
    json_body: Optional[dict] = None,
    data: Optional[Any] = None,
    data_items: Optional[int] = None,
    **kwargs,
) -> requests.Response:
    """requests.post() with automatic rate tracking."""
    mgr = _get_mgr()
    t0 = time.time()
    error_msg = None
    status_code = None
    resp_bytes = None
    success = False

    try:
        resp = requests.post(url, json=json_body, data=data, **kwargs)
        status_code = resp.status_code
        resp_bytes = len(resp.content) if resp.content else 0
        success = resp.ok
        if not resp.ok:
            error_msg = f"HTTP {resp.status_code}"
        return resp
    except Exception as e:
        error_msg = str(e)[:500]
        raise
    finally:
        latency = int((time.time() - t0) * 1000)
        mgr.log_request(
            source_key=source_key,
            request_type=request_type,
            url=url,
            method="POST",
            status_code=status_code,
            success=success,
            error_message=error_msg,
            latency_ms=latency,
            response_bytes=resp_bytes,
            data_items=data_items,
        )


def log_external(
    source_key: str,
    request_type: str,
    *,
    url: Optional[str] = None,
    method: str = "GET",
    success: bool = True,
    error_message: Optional[str] = None,
    latency_ms: Optional[int] = None,
    response_bytes: Optional[int] = None,
    data_items: Optional[int] = None,
    params: Optional[dict] = None,
) -> dict:
    """Log a non-requests external call (geopy, DuckDB, praw, jobspy, etc)."""
    return _get_mgr().log_request(
        source_key=source_key,
        request_type=request_type,
        url=url,
        method=method,
        success=success,
        error_message=error_message,
        latency_ms=latency_ms,
        response_bytes=response_bytes,
        data_items=data_items,
        params=params,
    )
