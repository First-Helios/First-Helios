"""The ``llama-server`` HTTP client for stage [4] (ADR-0013 §1, §2; slice 5).

One chunk is one chat-completion request with the spike's measured settings:
greedy decoding (``temperature`` 0), prompt v2.3 as the system message, the
compact GBNF ``grammar``, the chunk's token cap as ``max_tokens``, the
system-prompt KV prefix reused per slot (``cache_prompt``) and no thinking.
A chunk that prints prices but comes back (nearly) empty is asked once more
with the nudge from :func:`~packages.helios_parsing.prompt.sparse_retry`; the
second answer is kept and the first recorded.

Readiness (session P5-4, X1): the caller waits on ``/health`` (503 while the
model loads) and checks ``/props``: the served file must be the manifest's
GGUF and the server must have the slots the run uses. The file's hash is not
re-checked here; Compose's ``llama-model-check`` verifies it before the server
starts (ADR-0013 Amendment 6 item 3).

Failures (X3): a request that times out, fails in transport or answers 5xx is
sent once more; after that the chunk fails (:class:`ChunkFailed`) and the page
is not written. A generation cut off at the token cap is not a failure: its
complete rows are recovered (``finish == "length"``, counted as truncated).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

import httpx

from packages.helios_parsing.output import ExtractorOutput, parse_output
from packages.helios_parsing.prompt import GRAMMAR, SYSTEM_PROMPT, sparse_retry, token_cap

if TYPE_CHECKING:
    from collections.abc import Callable

DEFAULT_SERVER = "http://llama-server:8080"  # the Compose service (no host port)
REQUEST_TIMEOUT_S = 1800.0  # the spike's per-request timeout; a 3,072-token chunk on the Pi
READY_TIMEOUT_S = 300.0
READY_POLL_S = 5.0
SLOTS = 2  # llama-server --parallel 2; the run keeps this many requests in flight
RETRIES = 1  # extra attempts after a timeout, transport error or 5xx


class LlamaServerError(RuntimeError):
    """``llama-server`` is unusable for this run."""


class ServerNotReady(LlamaServerError):
    """``/health`` did not answer 200 in time."""


class WrongModel(LlamaServerError):
    """``/props`` names a different model file or slot count than the run expects."""


class ChunkFailed(LlamaServerError):
    """A chunk's request still failed after its retry."""


def http_client(timeout_s: float = REQUEST_TIMEOUT_S) -> httpx.Client:
    """An ``httpx`` client with the extraction timeouts (connect fails fast)."""
    return httpx.Client(timeout=httpx.Timeout(timeout_s, connect=10.0))


@dataclass(frozen=True, slots=True)
class Attempt:
    """One completion as the server returned it."""

    raw: str
    finish: str | None  # "stop", or "length" when the token cap cut it off
    prompt_tokens: int
    generated_tokens: int
    wall_s: float

    def record(self) -> dict[str, Any]:
        return {
            "raw": self.raw,
            "finish": self.finish,
            "prompt_tokens": self.prompt_tokens,
            "generated_tokens": self.generated_tokens,
            "wall_s": round(self.wall_s, 2),
        }


@dataclass(frozen=True, slots=True)
class ChunkResult:
    """A chunk's kept answer, parsed; ``first`` is the sparse retry's first attempt."""

    output: ExtractorOutput
    attempt: Attempt
    first: Attempt | None = None
    resent: int = 0  # requests sent again after a timeout, transport error or 5xx

    @property
    def truncated(self) -> bool:
        return self.attempt.finish == "length"

    def record(self) -> dict[str, Any]:
        """The harness's chunk record (``{"raw": …}``, ``apps.menu_pipeline.evaluate``)."""
        out = self.attempt.record()
        if self.first is not None:
            out["retry"] = {"first": self.first.record()}
        return out


class LlamaClient:
    """Chunk extraction against one ``llama-server`` (thread-safe: ``httpx.Client`` is)."""

    def __init__(
        self,
        client: httpx.Client,
        *,
        base_url: str = DEFAULT_SERVER,
        retries: int = RETRIES,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client = client
        self._base = base_url.rstrip("/")
        self._retries = retries
        self._sleep = sleep
        self._clock = clock

    def wait_ready(self, timeout_s: float = READY_TIMEOUT_S, poll_s: float = READY_POLL_S) -> None:
        """Return once ``/health`` answers 200; raise :class:`ServerNotReady` after ``timeout_s``."""
        deadline = self._clock() + timeout_s
        last = "no answer"
        while True:
            try:
                response = self._client.get(f"{self._base}/health", timeout=10.0)
            except httpx.TransportError as error:
                last = type(error).__name__
            else:
                if response.status_code == httpx.codes.OK:
                    return
                last = f"HTTP {response.status_code}"
            if self._clock() >= deadline:
                raise ServerNotReady(
                    f"{self._base}/health not ready after {timeout_s:.0f} s ({last})"
                )
            self._sleep(poll_s)

    def check_model(self, model_file: str, *, slots: int = SLOTS) -> None:
        """Refuse a server whose ``/props`` names another model file or slot count."""
        response = self._client.get(f"{self._base}/props", timeout=10.0)
        response.raise_for_status()
        props = response.json()
        served = PurePosixPath(str(props.get("model_path") or "")).name
        if served != model_file:
            raise WrongModel(
                f"llama-server serves {served or 'no model'!r}, expected {model_file!r}"
            )
        if props.get("total_slots") != slots:
            raise WrongModel(f"llama-server has {props.get('total_slots')} slots, expected {slots}")

    def extract_chunk(self, chunk: str) -> ChunkResult:
        """One chunk's rows, re-asked once when a priced chunk comes back (nearly) empty."""
        cap = token_cap(chunk)  # the retry keeps the chunk's own cap (the nudge is not a line)
        first, resent = self._complete(chunk, cap)
        output = parse_output(first.raw)
        nudged = sparse_retry(chunk, output)
        if nudged is None:
            return ChunkResult(output, first, resent=resent)
        second, more = self._complete(nudged, cap)
        return ChunkResult(parse_output(second.raw), second, first, resent + more)

    def _complete(self, user: str, max_tokens: int) -> tuple[Attempt, int]:
        body = {
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ],
            "temperature": 0,
            "max_tokens": max_tokens,
            "grammar": GRAMMAR,
            "cache_prompt": True,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        error = "no attempt"
        for attempt in range(self._retries + 1):
            started = self._clock()
            try:
                response = self._client.post(f"{self._base}/v1/chat/completions", json=body)
            except httpx.TransportError as exc:  # includes timeouts
                error = type(exc).__name__
                continue
            if response.status_code >= httpx.codes.INTERNAL_SERVER_ERROR:
                error = f"HTTP {response.status_code}"
                continue
            if response.status_code != httpx.codes.OK:
                raise ChunkFailed(f"HTTP {response.status_code}: {response.text[:200]}")
            try:
                result = response.json()
                choice = result["choices"][0]
                raw = str(choice["message"]["content"] or "")
            except (ValueError, KeyError, IndexError, TypeError) as exc:
                raise ChunkFailed(f"unreadable completion: {exc!r}") from exc
            timings = result.get("timings") or {}
            return (
                Attempt(
                    raw=raw,
                    finish=choice.get("finish_reason"),
                    prompt_tokens=int(timings.get("prompt_n") or 0),
                    generated_tokens=int(timings.get("predicted_n") or 0),
                    wall_s=self._clock() - started,
                ),
                attempt,
            )
        raise ChunkFailed(f"chunk failed after {self._retries + 1} attempts ({error})")
