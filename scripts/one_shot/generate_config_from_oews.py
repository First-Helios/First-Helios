"""
Generate config/labor_market.yaml from actual OEWS data.

This script reads the Austin-Round Rock-San Marcos, TX MSA OEWS data and
auto-generates the labor market configuration (regions, scoring, QCEW/CBP/OEWS
params). It does NOT touch config/chains.yaml — chain definitions are manually
maintained there.

Data source:
    data/reference/bls/
    "Occupational Employment and Wage Statistics- Area: Austin-Round Rock-San Marcos, TX.ods"
    Coverage: Austin-Round Rock-San Marcos, TX MSA ONLY (BLS area code 12420)

Why this matters:
- OEWS data is the source of truth (638 occupations, 23 industry groups)
- Labor market config should be derived from data, not maintained separately
- Ensures config doesn't drift from reality
- Makes it easy to add new regions (just ingest their OEWS data)

Environment variables required:
    CBP_API_KEY — Census Bureau API key for CBP (County Business Patterns) data
    BLS_API_KEY — BLS v2 API key for QCEW/JOLTS/OEWS/LAUS

Usage:
    python scripts/one_shot/generate_config_from_oews.py
    python scripts/one_shot/generate_config_from_oews.py --output config/labor_market.yaml

Output: config/labor_market.yaml — DO NOT EDIT manually. Chain definitions stay in config/chains.yaml.
"""

import argparse
import logging
import sys
from pathlib import Path
from datetime import datetime

import yaml

_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core.database import get_session, init_db, OEWSRecord

logger = logging.getLogger(__name__)

# SOC code prefixes to industry mapping
SOC_TO_INDUSTRY = {
    "11": {
        "display_name": "Management",
        "naics_codes": ["11-"],
        "search_terms": ["manager", "director", "executive"],
        "avg_wage_range": (45, 65),
    },
    "13": {
        "display_name": "Business & Finance",
        "naics_codes": ["52-"],
        "search_terms": ["accountant", "analyst", "financial", "business"],
        "avg_wage_range": (25, 50),
    },
    "15": {
        "display_name": "IT & Computer",
        "naics_codes": ["51-"],
        "search_terms": ["developer", "engineer", "software", "it", "tech"],
        "avg_wage_range": (40, 70),
    },
    "17": {
        "display_name": "Engineering & Architecture",
        "naics_codes": ["54-"],
        "search_terms": ["engineer", "architect", "design"],
        "avg_wage_range": (35, 60),
    },
    "19": {
        "display_name": "Life & Physical Science",
        "naics_codes": ["54-"],
        "search_terms": ["scientist", "technician", "lab"],
        "avg_wage_range": (25, 55),
    },
    "21": {
        "display_name": "Social Service",
        "naics_codes": ["62-"],
        "search_terms": ["counselor", "social worker", "case manager"],
        "avg_wage_range": (20, 35),
    },
    "23": {
        "display_name": "Legal",
        "naics_codes": ["54-"],
        "search_terms": ["lawyer", "legal", "attorney", "paralegal"],
        "avg_wage_range": (30, 80),
    },
    "25": {
        "display_name": "Education & Training",
        "naics_codes": ["61-"],
        "search_terms": ["teacher", "instructor", "professor", "trainer"],
        "avg_wage_range": (20, 45),
    },
    "27": {
        "display_name": "Arts & Design",
        "naics_codes": ["71-"],
        "search_terms": ["designer", "artist", "creative"],
        "avg_wage_range": (20, 45),
    },
    "29": {
        "display_name": "Healthcare Practitioners",
        "naics_codes": ["62-"],
        "search_terms": ["nurse", "doctor", "physician", "medical", "healthcare"],
        "avg_wage_range": (30, 70),
    },
    "31": {
        "display_name": "Healthcare Support",
        "naics_codes": ["62-"],
        "search_terms": ["cna", "medical assistant", "healthcare support"],
        "avg_wage_range": (15, 30),
    },
    "33": {
        "display_name": "Protective Service",
        "naics_codes": ["92-"],
        "search_terms": ["police", "security", "fire", "guard"],
        "avg_wage_range": (25, 45),
    },
    "35": {
        "display_name": "Food Service",
        "naics_codes": ["72-"],
        "search_terms": ["barista", "cook", "food", "restaurant", "cafe"],
        "avg_wage_range": (13, 25),
    },
    "37": {
        "display_name": "Building & Grounds Maintenance",
        "naics_codes": ["56-"],
        "search_terms": ["cleaning", "maintenance", "groundskeeper"],
        "avg_wage_range": (15, 30),
    },
    "39": {
        "display_name": "Personal Care",
        "naics_codes": ["62-"],
        "search_terms": ["care worker", "childcare", "homemaker"],
        "avg_wage_range": (15, 30),
    },
    "41": {
        "display_name": "Sales",
        "naics_codes": ["44-45"],
        "search_terms": ["sales", "salesperson", "retail"],
        "avg_wage_range": (20, 40),
    },
    "43": {
        "display_name": "Office & Administrative",
        "naics_codes": ["52-"],
        "search_terms": ["clerk", "secretary", "receptionist", "admin"],
        "avg_wage_range": (18, 35),
    },
    "45": {
        "display_name": "Agriculture",
        "naics_codes": ["11-"],
        "search_terms": ["farm", "agricultural", "farming"],
        "avg_wage_range": (15, 35),
    },
    "47": {
        "display_name": "Construction",
        "naics_codes": ["23-"],
        "search_terms": ["construction", "carpenter", "builder"],
        "avg_wage_range": (20, 50),
    },
    "49": {
        "display_name": "Installation & Repair",
        "naics_codes": ["23-"],
        "search_terms": ["technician", "mechanic", "installer", "repair"],
        "avg_wage_range": (20, 45),
    },
    "51": {
        "display_name": "Manufacturing & Production",
        "naics_codes": ["31-33"],
        "search_terms": ["production", "operator", "assembler", "manufacturing"],
        "avg_wage_range": (18, 35),
    },
    "53": {
        "display_name": "Transportation & Material",
        "naics_codes": ["48-49"],
        "search_terms": ["driver", "delivery", "transportation"],
        "avg_wage_range": (15, 35),
    },
}


def query_oews_data(session, area_code: str = "12420"):
    """
    Query OEWS database to get all occupations by industry.

    Returns: dict of {soc_prefix: {occ_code: occ_title, wage_info}}
    """
    records = session.query(OEWSRecord).filter(
        OEWSRecord.area_code == area_code
    ).all()

    # Group by SOC prefix (2-digit)
    industries = {}
    for record in records:
        if not record.occ_code or len(record.occ_code) < 2:
            continue

        soc_prefix = record.occ_code[:2]
        if soc_prefix not in industries:
            industries[soc_prefix] = {
                "occupations": [],
                "avg_wage": 0,
                "total_employment": 0,
            }

        industries[soc_prefix]["occupations"].append({
            "code": record.occ_code,
            "title": record.occ_title,
            "wage_median": record.wage_median_hourly,
            "employment": record.employment or 0,
        })

        if record.wage_median_hourly:
            industries[soc_prefix]["avg_wage"] = record.wage_median_hourly
        if record.employment:
            industries[soc_prefix]["total_employment"] = record.employment

    return industries


def generate_config_section(industries_data: dict) -> dict:
    """
    Generate industries section of chains.yaml from OEWS data.

    Returns: dict with industries configuration
    """

    config_industries = {}

    for soc_prefix in sorted(industries_data.keys()):
        if soc_prefix == "00":
            continue  # Skip "All Occupations"

        if soc_prefix not in SOC_TO_INDUSTRY:
            logger.warning(f"SOC {soc_prefix} not in mapping, skipping")
            continue

        template = SOC_TO_INDUSTRY[soc_prefix]
        occ_data = industries_data[soc_prefix]

        config_industries[f"soc_{soc_prefix}"] = {
            "display_name": template["display_name"],
            "naics_codes": template["naics_codes"],
            "soc_group": f"{soc_prefix}-",
            "occupations_in_austin": len(occ_data["occupations"]),
            "avg_wage_hourly": round(occ_data["avg_wage"], 2),
            "search_terms": template["search_terms"],
            "sentiment_keywords": {
                "negative": ["understaffed", "short staffed", "burnout", "overworked"],
                "positive": ["fully staffed", "great team", "well managed"],
            },
        }

    return config_industries


def generate_qcew_section() -> dict:
    """Generate QCEW configuration section."""
    return {
        "qcew": {
            "county_fips": {
                "travis": "48453",
                "williamson": "48491",
                "hays": "48209",
                "bastrop": "48021",
                "caldwell": "48055",
            },
            "fetch_all_industries": True,
            "comment": "Generated from OEWS data. Set fetch_all_industries=true to ingest all industries.",
            "ownership_code": "5",
        }
    }


def generate_cbp_section() -> dict:
    """Generate CBP configuration section."""
    return {
        "cbp": {
            "api_key": None,  # set via CBP_API_KEY env var
            "zip_codes": [
                "78701", "78702", "78703", "78704", "78705", "78745", "78748",
                "78749", "78750", "78751", "78752", "78753", "78756", "78757",
                "78758", "78759", "78660", "78664", "78665", "78681", "78634",
                "78641", "78613", "78717", "78626",
            ],
            "fetch_all_industries": True,
            "comment": "Generated from OEWS data. Fetches all industries at ZIP level.",
        }
    }


def generate_oews_section() -> dict:
    """Generate OEWS configuration section."""
    return {
        "oews": {
            "area_code": "12420",
            "fetch_all_occupations": True,
            "comment": "Generated from OEWS data. Includes all 638 Austin-Round Rock-San Marcos, TX MSA occupations (area code 12420).",
        }
    }


def generate_target_industries_section() -> dict:
    """Generate target industries selection."""
    return {
        "target_industries": {
            "mode": "all",
            "comment": "Generate from OEWS data. Set to 'all' for multi-industry analysis.",
        }
    }


def generate_full_config(oews_industries: dict) -> dict:
    """
    Generate labor_market.yaml configuration from OEWS data.

    Does NOT include chains — those are manually maintained in config/chains.yaml.
    """

    config = {
        "_comment": (
            "AUTO-GENERATED from OEWS data by scripts/one_shot/generate_config_from_oews.py\n"
            "Source: Austin-Round Rock-San Marcos, TX MSA OEWS data (area code 12420) ONLY.\n"
            "Do not edit manually — regenerate from data using the script.\n"
            "Chain definitions are in config/chains.yaml (manually maintained).\n"
            f"Generated: {datetime.now().isoformat()}"
        ),
        "regions": {
            "austin_tx": {
                "display_name": "Austin, TX",
                "center_lat": 30.2672,
                "center_lng": -97.7431,
                "radius_mi": 25,
                "location_string": "Austin, TX",
                "state": "TX",
            }
        },
        "target_industries": "all",
        "industries": generate_config_section(oews_industries),
    }

    # Add data source configs
    config.update(generate_qcew_section())
    config.update(generate_cbp_section())
    config.update(generate_oews_section())

    # Add scoring and targeting (static weights, not derived from OEWS)
    config.update({
        "scoring": {
            "weights": {
                "demand_pressure": 0.35,
                "wage_competitiveness": 0.25,
                "churn_signal": 0.25,
                "qualitative": 0.15,
            },
            "posting_age_decay": {
                "fresh_days": 7,
                "stale_days": 90,
            },
            "tiers": {
                "critical": {"min_percentile": 67, "label": "critical"},
                "elevated": {"min_percentile": 33, "label": "elevated"},
                "adequate": {"min_percentile": 0, "label": "adequate"},
            },
            "baseline": {
                "reference_period": "2025-Q3",
                "reindex_on_new_qcew": True,
            },
            "seasonal": {
                "enabled": True,
                "peak_months": [5, 6, 7],
                "trough_months": [1, 2],
            },
        },
        "targeting": {
            "weights": {
                "staffing_stress": 0.40,
                "wage_gap": 0.30,
                "isolation": 0.20,
                "local_alternatives": 0.10,
            },
            "tiers": {
                "prime": {"min_score": 67, "label": "prime"},
                "strong": {"min_score": 33, "label": "strong"},
                "moderate": {"min_score": 0, "label": "moderate"},
            },
            "local_radius_mi": 1.0,
        },
    })

    return config


def main():
    parser = argparse.ArgumentParser(
        description="Generate config/labor_market.yaml from OEWS data"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(_PROJECT_ROOT) / "config" / "labor_market.yaml",
        help="Output path (default: config/labor_market.yaml)",
    )
    parser.add_argument(
        "--area-code",
        default="12420",
        help="OEWS area code (default: 12420 for Austin MSA)",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    try:
        # Query OEWS data
        logger.info(f"Querying OEWS data for area code {args.area_code}...")
        engine = init_db()
        session = get_session(engine)

        oews_industries = query_oews_data(session, args.area_code)
        logger.info(f"Found {len(oews_industries)} industry groups in OEWS")

        for soc_prefix, data in sorted(oews_industries.items()):
            if soc_prefix != "00":
                occupations = len(data["occupations"])
                avg_wage = data["avg_wage"]
                logger.info(
                    f"  SOC {soc_prefix}-xxxx: {occupations} occupations, "
                    f"avg wage ${avg_wage:.2f}/hr"
                )

        # Generate config
        logger.info("Generating configuration...")
        config = generate_full_config(oews_industries)

        # Write config
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w") as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False)

        logger.info(f"✓ Configuration generated: {args.output}")
        logger.info(f"  Industries: {len([k for k in config['industries'].keys()])}")
        logger.info("  (chains.yaml untouched — chain definitions are manually maintained)")

        session.close()
        return 0

    except Exception as e:
        logger.error(f"Failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
