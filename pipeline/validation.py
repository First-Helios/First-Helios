"""
pipeline/validation.py — Per-intent scraper output contracts.

Each contract defines what a valid ScraperSignal list must look like for a given
intent before it is handed to ingest_signals().  Catching bad output here keeps
garbage out of the DB and gives the agent pilot clear error messages.

Usage
-----
    from pipeline.validation import validate_scraper_output

    result = validate_scraper_output("poi_chain_locations", signals)
    if not result.valid:
        logger.error("Bad scraper output: %s", result.errors)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ValidationResult:
    """Outcome of validate_scraper_output()."""
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    records_checked: int = 0


@dataclass
class OutputContract:
    """Rules that every ScraperSignal in a batch must satisfy.

    Fields
    ------
    required_signal_types   at least one signal must have one of these types
    required_signal_fields  every signal must have these attributes non-empty
    min_signals             batch must contain at least this many signals
                            (0 = empty batch is acceptable)
    """
    required_signal_types: set[str]
    required_signal_fields: list[str]
    min_signals: int = 0


# ── Per-intent contracts ──────────────────────────────────────────────────────
#
# Covers the three highest-traffic intents (required by test) plus all others
# that have live external adapters.

SCRAPER_OUTPUT_CONTRACTS: dict[str, OutputContract] = {

    "poi_chain_locations": OutputContract(
        required_signal_types={"listing"},
        required_signal_fields=["store_num", "chain", "source", "signal_type"],
        min_signals=0,          # zero stores in region is valid (sparse brand)
    ),

    "poi_local_density": OutputContract(
        required_signal_types={"listing"},
        required_signal_fields=["store_num", "chain", "source", "signal_type"],
        min_signals=0,
    ),

    "job_posting_volume": OutputContract(
        required_signal_types={"listing"},
        required_signal_fields=["store_num", "chain", "source", "signal_type"],
        min_signals=0,
    ),

    "sentiment_check": OutputContract(
        required_signal_types={"sentiment", "review_score"},
        required_signal_fields=["store_num", "chain", "source", "signal_type"],
        min_signals=0,
    ),

    "wage_baseline": OutputContract(
        required_signal_types={"wage"},
        required_signal_fields=["store_num", "chain", "source", "signal_type"],
        min_signals=0,
    ),

    "economic_context": OutputContract(
        required_signal_types={"wage"},
        required_signal_fields=["store_num", "chain", "source", "signal_type"],
        min_signals=0,
    ),
}


def validate_scraper_output(intent_key: str, signals: list) -> ValidationResult:
    """Validate a batch of ScraperSignals against the contract for *intent_key*.

    Args:
        intent_key  Intent enum value string (e.g. "poi_chain_locations")
        signals     List of ScraperSignal instances returned by an adapter

    Returns:
        ValidationResult — .valid is True only if all checks pass.
    """
    contract = SCRAPER_OUTPUT_CONTRACTS.get(intent_key)
    if contract is None:
        return ValidationResult(
            valid=False,
            errors=[
                f"No output contract registered for intent '{intent_key}'. "
                f"Add one to pipeline/validation.py SCRAPER_OUTPUT_CONTRACTS."
            ],
        )

    errors: list[str] = []
    warnings: list[str] = []

    # Minimum count check
    if len(signals) < contract.min_signals:
        errors.append(
            f"intent '{intent_key}' requires >= {contract.min_signals} signals, "
            f"got {len(signals)}"
        )

    # Per-signal field checks
    for i, sig in enumerate(signals):
        for field_name in contract.required_signal_fields:
            value = getattr(sig, field_name, None)
            if not value:
                errors.append(
                    f"Signal[{i}] missing required field '{field_name}' "
                    f"(store_num={getattr(sig, 'store_num', '?')!r})"
                )

    # Signal type check — warn if none of the expected types appear
    if signals and contract.required_signal_types:
        found_types = {getattr(sig, "signal_type", None) for sig in signals}
        if not found_types & contract.required_signal_types:
            warnings.append(
                f"intent '{intent_key}': expected signal_type in "
                f"{contract.required_signal_types}, found {found_types}"
            )

    return ValidationResult(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
        records_checked=len(signals),
    )
