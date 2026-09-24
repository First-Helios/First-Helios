"""Positive and negative examples for the same checker used on repository files."""

from pathlib import Path

import pytest

from test.import_boundaries import boundary_violations


@pytest.mark.parametrize(
    ("path", "source"),
    [
        ("identity/commands.py", "import packages.helios_core.provenance.models as p"),
        ("identity/commands.py", "from packages.helios_core.provenance import models"),
        ("identity/commands.py", "from packages.helios_core.provenance import Source"),
        ("identity/commands.py", "from packages.helios_core import provenance as p"),
        ("identity/commands.py", "from ..provenance.models import Source"),
        ("identity/commands.py", "from .. import provenance"),
        ("identity/commands.py", "from ..provenance import *"),
        ("identity/__init__.py", "from ..provenance import Source"),
        ("identity/internal/check.py", "from ...provenance import models"),
        ("identity/commands.py", "from ..provenance import contracts, models"),
        ("identity/commands.py", "import apps.api.main"),
        ("identity/commands.py", "from apps import api"),
        ("identity/commands.py", "from ..domains import menu"),
        ("identity/commands.py", "from .. import gold"),
        ("identity/commands.py", "from ..db import model_registry"),
        ("provenance/contracts.py", "from ..identity.contracts import EligibleSubject"),
        ("provenance/models.py", "import packages.helios_core.domains.menu"),
        ("db/session.py", "from ..identity import models"),
        ("db/session.py", "import packages.helios_core.provenance.models"),
        ("db/internal/helper.py", "from ...identity.models import Subject"),
        ("db/model_registry_copy.py", "from ..identity.models import Subject"),
        ("db/model_registry.py", "from ..identity.commands import create_place"),
        ("db/model_registry.py", "import apps.api"),
        ("db/model_registry.py", "from ..domains.menu.commands import write_menu"),
        ("gold/refresh.py", "import apps.api"),
        ("gold/refresh.py", "from ..db import model_registry"),
        ("gold/refresh.py", "from ..identity.models import Subject"),
        ("gold/refresh.py", "from ..identity import Subject"),
        ("gold/refresh.py", "from ..provenance import models"),
        ("gold/refresh.py", "from ..domains.menu.models import MenuPage"),
        ("gold/refresh.py", "from ..domains.menu.commands import persist_menu"),
        ("gold/refresh.py", "from ..domains import menu"),
        ("gold/internal/helper.py", "from ...domains.menu import models"),
    ],
)
def test_forbidden_foundation_imports(path: str, source: str) -> None:
    assert boundary_violations(source, Path("packages/helios_core") / path)


@pytest.mark.parametrize(
    ("path", "source"),
    [
        (
            "identity/commands.py",
            "from packages.helios_core.provenance.contracts import EvidenceRef",
        ),
        ("identity/commands.py", "import packages.helios_core.provenance.contracts as p"),
        ("identity/commands.py", "from ..provenance import contracts as p"),
        ("identity/__init__.py", "from ..provenance.contracts import EvidenceRef"),
        ("identity/internal/check.py", "from ...provenance import contracts"),
        ("identity/commands.py", "from .models import Subject"),
        ("identity/commands.py", "from . import models"),
        ("identity/commands.py", "from ..db.base import Base"),
        ("provenance/models.py", "from ..db import base"),
        ("db/session.py", "from ..config import get_settings"),
        ("db/model_registry.py", "from ..identity.models import Subject"),
        ("db/model_registry.py", "import packages.helios_core.provenance.models as p"),
        ("db/model_registry.py", "from ..provenance import models"),
        ("db/model_registry.py", "from ..domains.menu.models import MenuPage"),
        ("db/model_registry.py", "from ..gold import models"),
        ("identity/commands.py", "import apps_extra, sqlalchemy_utils"),
        ("gold/refresh.py", "from ..domains.menu.selection import select_price"),
        ("gold/catalog.py", "from ..domains.menu.enumeration import enumerate_current_requests"),
        ("gold/refresh.py", "from ..domains.menu.contracts import NodeKind"),
        ("gold/refresh.py", "from ..identity.contracts import ResolvedScope"),
        ("gold/refresh.py", "from ..provenance.contracts import get_record_version"),
        ("gold/models.py", "from ..db.base import Base"),
        ("gold/catalog.py", "from .refresh import refresh_current_menu"),
    ],
)
def test_allowed_foundation_imports(path: str, source: str) -> None:
    assert not boundary_violations(source, Path("packages/helios_core") / path)


@pytest.mark.parametrize(
    "source",
    [
        "import sqlalchemy.orm as orm",
        "from sqlalchemy import orm",
        "from ..helios_core.identity import Subject",
        "from .. import helios_core",
    ],
)
def test_parser_imports_are_checked(source: str) -> None:
    assert boundary_violations(source, Path("packages/helios_parsing/__init__.py"))


def test_parser_can_import_its_own_helpers_and_standard_library() -> None:
    assert not boundary_violations(
        "from . import helpers\nfrom decimal import Decimal\nimport sqlalchemy_utils",
        Path("packages/helios_parsing/parser.py"),
    )
