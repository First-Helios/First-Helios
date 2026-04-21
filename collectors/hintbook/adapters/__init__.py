"""Adapter base contract.

Each adapter exposes:
    NAME: str
    HOMEPAGE: str
    SEED_URLS: list[str]
    def collect(report: HarvestReport) -> None

The collector fetches its seeds, parses them, and appends AggregatorRecords,
HintProposals, ExpectationProposals, and (for broader-industry scans)
IndustrySamples directly onto the report.
"""

from __future__ import annotations

from typing import Protocol

from collectors.hintbook.models import HarvestReport


class HintbookAdapter(Protocol):
    NAME: str
    HOMEPAGE: str
    SEED_URLS: list[str]

    def collect(self, report: HarvestReport) -> None: ...
