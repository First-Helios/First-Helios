"""
Typed configuration access for all ChainStaffingTracker modules.

Loads config/chains.yaml once at import time and provides accessor functions
so no module ever needs to parse YAML or hardcode values.

Usage:
    from config.loader import get_config, get_region, get_chain, get_scoring_weights
"""

import logging
import os
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent / "chains.yaml"
_config: dict[str, Any] | None = None


def _load() -> dict[str, Any]:
    """Load and cache the YAML config. Called once on first access."""
    global _config
    if _config is None:
        with open(_CONFIG_PATH, "r") as f:
            _config = yaml.safe_load(f)
        logger.info("[Config] Loaded %s", _CONFIG_PATH)
    return _config


def get_config() -> dict[str, Any]:
    """Return the full config dict."""
    return _load()


# ── Region helpers ───────────────────────────────────────────────────────────

def get_region(region_key: str) -> dict[str, Any]:
    """Return config block for a region, e.g. 'austin_tx'."""
    cfg = _load()
    return cfg["regions"][region_key]


def get_all_regions() -> dict[str, dict[str, Any]]:
    """Return all region configs keyed by region name."""
    return _load()["regions"]


# ── Chain helpers ────────────────────────────────────────────────────────────

def get_chain(chain_key: str) -> dict[str, Any]:
    """Return config block for a chain, e.g. 'starbucks'."""
    cfg = _load()
    return cfg["chains"][chain_key]


def get_all_chains() -> dict[str, dict[str, Any]]:
    """Return all chain configs keyed by chain name."""
    return _load()["chains"]


def get_chains_for_industry(industry: str) -> dict[str, dict[str, Any]]:
    """Return chain configs where industry matches."""
    return {
        k: v for k, v in get_all_chains().items()
        if v.get("industry") == industry
    }


# ── Industry helpers ─────────────────────────────────────────────────────────

def get_industry(industry_key: str) -> dict[str, Any]:
    """Return config block for an industry, e.g. 'coffee_cafe'."""
    cfg = _load()
    return cfg["industries"][industry_key]


def get_all_industries() -> dict[str, dict[str, Any]]:
    """Return all industry configs."""
    return _load()["industries"]


# ── Scoring helpers ──────────────────────────────────────────────────────────

def get_scoring_weights() -> dict[str, float]:
    """Return scoring source weights, e.g. {'careers_api': 0.40, ...}."""
    return _load()["scoring"]["weights"]


def get_posting_age_decay() -> dict[str, int]:
    """Return {'fresh_days': 7, 'stale_days': 90}."""
    return _load()["scoring"]["posting_age_decay"]


def get_score_tiers() -> dict[str, dict[str, Any]]:
    """Return tier definitions with min_percentile thresholds."""
    return _load()["scoring"]["tiers"]


# ── Targeting helpers ────────────────────────────────────────────────────────

def get_targeting_weights() -> dict[str, float]:
    """Return targeting component weights."""
    return _load()["targeting"]["weights"]


def get_targeting_tiers() -> dict[str, dict[str, Any]]:
    """Return targeting tier definitions."""
    return _load()["targeting"]["tiers"]


def get_local_radius_mi() -> float:
    """Return radius in miles for local employer density calculation."""
    return _load()["targeting"]["local_radius_mi"]


# ── Rate limit helpers ───────────────────────────────────────────────────────

def get_rate_limit(source: str) -> dict[str, Any]:
    """Return rate limit config for a source, e.g. 'careers_api'."""
    return _load()["rate_limits"].get(source, {"delay_seconds": 1.0})


# ── HTTP helpers ─────────────────────────────────────────────────────────────

def get_http_config() -> dict[str, Any]:
    """Return HTTP config (timeout, retries, user agent)."""
    return _load()["http"]


# ── BLS helpers ──────────────────────────────────────────────────────────────

def get_bls_series() -> dict[str, dict[str, str]]:
    """Return BLS time series IDs and descriptions."""
    return _load()["bls_series"]


def get_bls_series_by_category(category: str) -> dict[str, dict[str, str]]:
    """Return BLS series filtered by category (ces, jolts, laus)."""
    return {
        k: v for k, v in get_bls_series().items()
        if v.get("category") == category
    }


# ── QCEW helpers ─────────────────────────────────────────────────────────────

def get_qcew_config() -> dict[str, Any]:
    """Return QCEW configuration (county FIPS, NAICS codes, ownership)."""
    return _load()["qcew"]


def get_qcew_county_fips() -> dict[str, str]:
    """Return mapping of county name → FIPS code."""
    return _load()["qcew"]["county_fips"]


def get_qcew_naics_codes() -> dict[str, str]:
    """Return mapping of internal key → NAICS code."""
    return _load()["qcew"]["naics_codes"]


# ── Census CBP helpers ───────────────────────────────────────────────────────

def get_cbp_config() -> dict[str, Any]:
    """Return Census CBP configuration."""
    cfg = _load()["cbp"]
    # Allow env var override for API key
    if cfg.get("api_key") is None:
        cfg["api_key"] = os.environ.get("CBP_API_KEY")
    return cfg


def get_cbp_zip_codes() -> list[str]:
    """Return list of ZIP codes for CBP queries."""
    return _load()["cbp"]["zip_codes"]


def get_cbp_naics_codes() -> dict[str, str]:
    """Return CBP NAICS code mapping."""
    return _load()["cbp"]["naics_codes"]


# ── OEWS helpers ─────────────────────────────────────────────────────────────

def get_oews_config() -> dict[str, Any]:
    """Return OEWS configuration (area code, occupations)."""
    return _load()["oews"]


def get_oews_occupations() -> dict[str, dict[str, str]]:
    """Return OEWS occupation definitions."""
    return _load()["oews"]["occupations"]


# ── Scoring baseline & seasonal helpers ──────────────────────────────────────

def get_baseline_config() -> dict[str, Any]:
    """Return baseline indexing configuration."""
    return _load()["scoring"].get("baseline", {})


def get_seasonal_config() -> dict[str, Any]:
    """Return seasonal adjustment configuration."""
    return _load()["scoring"].get("seasonal", {})


# ── Scheduler helpers ────────────────────────────────────────────────────────

def get_scheduler_config() -> dict[str, Any]:
    """Return scheduler job definitions."""
    return _load()["scheduler"]
