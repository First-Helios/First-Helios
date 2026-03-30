#!/usr/bin/env python3
"""
Reset DB and test all scrapers - Fresh Start Workflow

This script:
1. Initializes a fresh database with schema
2. Populates reference data
3. Regenerates config from OEWS
4. Reports scraper availability
5. Prepares for fresh data ingestion

Usage:
    python scripts/reset_and_test.py
"""

import logging
import sys
import subprocess
from pathlib import Path
from datetime import datetime

# Setup path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.database import Base, get_engine, get_session, init_db
import backend.models.reference  # Register models

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Scraper modules to test (name -> module.main)
SCRAPERS_TO_TEST = {
    "BLS QCEW": "scrapers.qcew_adapter",
    "BLS CBP": "scrapers.cbp_adapter",
    "BLS Main": "scrapers.bls_adapter",
    "JobSpy": "scrapers.jobspy_adapter",
    "Reddit": "scrapers.reddit_adapter",
    "Google Maps Reviews": "scrapers.reviews_adapter",
    "WARN Database": "scrapers.warn_adapter",
    "NLRB Strikes": "scrapers.nlrb_adapter",
}

test_results = {}

def test_scraper_import(name: str, module_name: str) -> bool:
    """Test if a scraper module can be imported and has main()."""
    logger.info(f"\nTesting: {name} ({module_name})")

    try:
        mod = __import__(module_name, fromlist=["main"])
        if hasattr(mod, "main"):
            test_results[name] = {"status": "✓ AVAILABLE", "module": module_name}
            logger.info(f"  ✓ Scraper available - has main() function")
            return True
        else:
            test_results[name] = {"status": "⚠ NO MAIN", "module": module_name}
            logger.warning(f"  ⚠ Module found but no main() function")
            return False
    except ImportError as e:
        test_results[name] = {"status": "✗ NOT FOUND", "error": str(e)[:100]}
        logger.error(f"  ✗ Module not found: {e}")
        return False
    except Exception as e:
        test_results[name] = {"status": "✗ ERROR", "error": str(e)[:100]}
        logger.error(f"  ✗ Error: {e}")
        return False

def main():
    logger.info("\n" + "="*70)
    logger.info("FRESH START: Database Reset & Scraper Validation")
    logger.info("="*70)

    # Step 1: Initialize database
    logger.info("\n[Step 1/4] Initializing database with fresh schema...")
    try:
        init_db()
        logger.info("✓ Database initialized")
    except Exception as e:
        logger.error(f"✗ Database init failed: {e}", exc_info=True)
        return False

    # Step 2: Populate reference data
    logger.info("\n[Step 2/4] Populating reference data...")
    try:
        from scripts.populate_reference_data import populate_all
        populate_all()
        logger.info("✓ Reference data populated")
    except Exception as e:
        logger.error(f"✗ Reference data population failed: {e}", exc_info=True)
        # Don't fail completely - continue

    # Step 3: Regenerate config
    logger.info("\n[Step 3/4] Regenerating config from OEWS...")
    try:
        # Run the script via subprocess to avoid import issues
        result = subprocess.run(
            ["python", "scripts/generate_config_from_oews.py"],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode == 0:
            logger.info("✓ Config regenerated")
        else:
            logger.warning(f"Config generation had issues:\n{result.stderr}")
    except Exception as e:
        logger.error(f"✗ Config generation failed: {e}")

    # Step 4: Test scraper availability
    logger.info("\n[Step 4/4] Checking scraper availability...")
    logger.info("="*70)

    available = 0
    unavailable = 0

    for name, module_name in SCRAPERS_TO_TEST.items():
        if test_scraper_import(name, module_name):
            available += 1
        else:
            unavailable += 1

    # Summary
    logger.info("\n" + "="*70)
    logger.info("Test Summary")
    logger.info("="*70)

    for name, result in test_results.items():
        status = result["status"]
        detail = result.get("error", "")
        if detail:
            logger.info(f"{status:15} {name:30} {detail}")
        else:
            logger.info(f"{status:15} {name:30}")

    logger.info("="*70)
    logger.info(f"Results: {available} available, {unavailable} unavailable out of {len(SCRAPERS_TO_TEST)} scrapers")

    logger.info("\n✓ Database is fresh and ready for data ingestion!")
    logger.info("\nNext steps:")
    logger.info("1. Start server: python server.py")
    logger.info("2. Server will auto-register scheduler jobs from config/chains.yaml")
    logger.info("3. Monitor job runs and data ingestion in logs")
    logger.info("4. Check API responses at http://localhost:8765/api/*")

    if unavailable > 0:
        logger.info(f"\n⚠ Note: {unavailable} scraper(s) are missing or broken.")
        logger.info("  Run them individually to test with `python scrapers/[scraper]_adapter.py`")

    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
