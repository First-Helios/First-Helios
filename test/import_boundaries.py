"""Static import checks for the active ADR-0004 boundaries (no imports executed)."""

from __future__ import annotations

import ast
from importlib.util import resolve_name
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

_CORE = "packages.helios_core"
_REGISTRY = f"{_CORE}.db.model_registry"


def _within(name: str, package: str) -> bool:
    return name == package or name.startswith(package + ".")


def imported_names(source: str, path: Path) -> list[tuple[int, str]]:
    """Resolve ordinary/from imports, including aliases and package initializers.

    A from-import's named members matter: `from provider import models` must
    not hide behind the parent package. Star imports retain the package name.
    Dynamic imports and attribute access through arbitrary aliases are outside
    this small static check.
    """
    package = ".".join(path.parts[:-1])
    imports: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imports.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                module = resolve_name("." * node.level + module, package)
            imports.extend(
                (node.lineno, module if alias.name == "*" else f"{module}.{alias.name}")
                for alias in node.names
            )
    return imports


def boundary_violations(source: str, path: Path) -> list[str]:
    """Return line/target diagnostics for foundation and parser violations."""
    owner = ".".join(path.with_suffix("").parts)
    violations: list[str] = []
    for line, target in imported_names(source, path):
        forbidden = False
        if _within(owner, "packages.helios_parsing"):
            forbidden = _within(target, "sqlalchemy") or _within(target, _CORE)
        elif any(_within(owner, f"{_CORE}.{part}") for part in ("db", "provenance", "identity")):
            forbidden = any(
                _within(target, package)
                for package in ("apps", f"{_CORE}.domains", f"{_CORE}.gold")
            )
            if _within(owner, f"{_CORE}.db"):
                forbidden |= any(
                    _within(target, f"{_CORE}.{part}") for part in ("provenance", "identity")
                )
            if _within(owner, f"{_CORE}.provenance"):
                forbidden |= _within(target, f"{_CORE}.identity")
            if _within(owner, f"{_CORE}.identity") and _within(target, f"{_CORE}.provenance"):
                forbidden |= not _within(target, f"{_CORE}.provenance.contracts")
            # Registration is not a backdoor provider API.
            forbidden |= _within(target, _REGISTRY)
            registry_model = any(
                _within(target, f"{_CORE}.{part}.models")
                for part in ("provenance", "identity", "gold")
            ) or (
                _within(target, f"{_CORE}.domains")
                and len(target.split(".")) >= 5
                and target.split(".")[4] == "models"
            )
            if owner == _REGISTRY and registry_model:
                forbidden = False
        if forbidden:
            violations.append(f"{path}:{line}: {target}")
    return violations
