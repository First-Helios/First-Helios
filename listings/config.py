"""
listings/config.py — Runtime configuration for the job-first layer.

All values can be overridden via environment variables.
"""

import os

# How long a job posting stays "active" after its posted_date.
# If posted_date is unavailable, scraped_at is used as the base.
POSTING_TTL_DAYS = int(os.environ.get("POSTING_TTL_DAYS", 30))

# Maximum distance (metres) between a posting's geocoded location and a
# candidate LocalEmployer row to accept the match via fingerprint+proximity.
# 150 m (≈ half a city block) accounts for Nominatim resolving to the street
# midpoint rather than the building entrance.
PROXIMITY_THRESHOLD_M = float(os.environ.get("PROXIMITY_THRESHOLD_M", 150))

# Decimal-degree equivalent of PROXIMITY_THRESHOLD_M.
# 1 degree latitude ≈ 111 320 m.
PROXIMITY_THRESHOLD_DEG = PROXIMITY_THRESHOLD_M / 111_320   # ≈ 0.00135°

# Minimum confidence score to store a match result (vs. leaving it unmatched).
MIN_MATCH_CONFIDENCE = float(os.environ.get("MIN_MATCH_CONFIDENCE", 0.5))
