"""Section-name lexicon: arm A of the course-labeller comparison (ADR-0016 §4).

Pure Python, generic word rules over the section name only; the rules are a
versioned config file (``config/course_lexicon_v1.json``) written from the
vocabulary and the training split. A name is normalized (accents folded,
lowercase, apostrophes dropped, punctuation to spaces, a plural ``s`` stripped
per token), then every rule phrase that occurs as a run of tokens matches,
longer phrases first: a token a longer phrase has used is not matched again
("ice cream" is not "cream", "extra side" is not "extra").

The matched courses resolve in a fixed way that mirrors the guide's precedence
(``docs/course-labelling-guide.md`` §2):

1. ``other``, then ``kids``, wins outright.
2. A non-alcoholic marker ("zero proof", "mocktail") makes it ``drink``.
3. ``breakfast`` yields to a drink word ("brunch cocktails" is ``alcohol``)
   and otherwise wins over the dish courses ("breakfast sides").
4. Exactly one course left is the label; none or several (a mixed heading such
   as "sides & desserts") abstains.

The labeller version is ``<version>@<sha256 prefix of the file>``.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from typing import TYPE_CHECKING

from packages.helios_parsing.course_eval import COURSES

if TYPE_CHECKING:
    from pathlib import Path

NON_ALCOHOLIC = "non_alcoholic"  # a marker, not a course: resolves to `drink`
_KINDS = (*COURSES, NON_ALCOHOLIC)
_DRINKS = frozenset({"alcohol", "drink"})
_APOSTROPHES = re.compile(r"['’‘`]")
_NON_WORD = re.compile(r"[^0-9a-z]+")


def _stem(token: str) -> str:
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):  # noqa: PLR2004
        return token[:-1]
    return token


def normalize(name: str) -> tuple[str, ...]:
    """The name's tokens: accents folded, lowercase, apostrophes dropped, plural ``s`` off."""
    folded = unicodedata.normalize("NFKD", name)
    text = "".join(ch for ch in folded if not unicodedata.combining(ch)).lower()
    text = _NON_WORD.sub(" ", _APOSTROPHES.sub("", text))
    return tuple(_stem(token) for token in text.split())


@dataclass(frozen=True, slots=True)
class Lexicon:
    version: str  # the labeller version, `<name>@<file sha256 prefix>`
    phrases: tuple[tuple[tuple[str, ...], str], ...]  # (tokens, kind), longest first

    @classmethod
    def load(cls, path: Path) -> Lexicon:
        data = path.read_bytes()
        raw = json.loads(data)
        phrases: list[tuple[tuple[str, ...], str]] = []
        for kind, words in raw["rules"].items():
            if kind not in _KINDS:
                raise ValueError(f"{path}: {kind!r} is not a course or marker")
            phrases.extend((normalize(word), kind) for word in words)
        if any(not tokens for tokens, _ in phrases):
            raise ValueError(f"{path}: a rule normalizes to nothing")
        seen: dict[tuple[str, ...], str] = {}
        for tokens, kind in phrases:
            if seen.setdefault(tokens, kind) != kind:
                raise ValueError(f"{path}: {' '.join(tokens)!r} names two courses")
        ordered = sorted(seen.items(), key=lambda pair: (-len(pair[0]), pair[0]))
        digest = hashlib.sha256(data).hexdigest()[:12]
        return cls(version=f"{raw['version']}@{digest}", phrases=tuple(ordered))

    def matches(self, name: str) -> list[str]:
        """The kinds the name's phrases name, longer phrases first, each token used once."""
        tokens = normalize(name)
        used = [False] * len(tokens)
        found: list[str] = []
        for phrase, kind in self.phrases:
            width = len(phrase)
            for start in range(len(tokens) - width + 1):
                span = range(start, start + width)
                if tokens[start : start + width] == phrase and not any(used[i] for i in span):
                    for i in span:
                        used[i] = True
                    found.append(kind)
        return found

    def label(self, name: str) -> str | None:
        """The section's course, or ``None`` (abstain)."""
        kinds = set(self.matches(name))
        for decisive in ("other", "kids"):
            if decisive in kinds:
                return decisive
        if NON_ALCOHOLIC in kinds:
            return "drink"
        if "breakfast" in kinds:
            if kinds & _DRINKS:
                kinds.discard("breakfast")
            else:
                return "breakfast"
        return kinds.pop() if len(kinds) == 1 else None
