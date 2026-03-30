"""
scripts/populate_mobility_data.py

Populates the upward mobility graph tables (mob_occupation, mob_transition)
from the PublicPoolData Employment Stata files and the CTOT Dashboard.

Source files expected at DATA_DIR (override with --data-dir):
  Emsi-dataset.dta                  — 256k transition pairs, ISA skill deltas, wages
  Dashboard-transitions-dataset.dta — ranked frequency of actual worker moves (SOC→SOC)
  Dashboard-trajectories-dataset.dta — 3/5/10yr wage outcome by CensusCode

Crosswalk architecture (no hardcoded SOC map):
  ref_industry_taxonomy.primary_occ_code is the authoritative source for
  internal_industry → SOC.  When a SOC isn't available as an Emsi origin,
  _find_best_origin_soc() walks the SOC hierarchy:
    1. Exact match
    2. Same minor group  (first 5 chars, e.g. "35-30")
    3. Same major group  (first 2 chars, e.g. "35")
  picking the lowest-wage candidate (most entry-level).

dest_industry_keys_json on each mob_occupation:
  Answers "what employers near me hire for this destination role?"
  Built from ref_industry_taxonomy reverse lookup + same-cluster industries.
  Enables the full chain:
    store → SOC → mob_transition → dest_soc → dest_industry_keys → nearby employers

Usage:
  python scripts/populate_mobility_data.py
  python scripts/populate_mobility_data.py --data-dir /path/to/data --dry-run
"""

import argparse
import json
import logging
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from backend.database import get_session, init_db
from backend.models.reference import IndustryTaxonomy, MobOccupation, MobTransition
from config.paths import EMSI_DIR

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Source files belong in data/reference/emsi/ — see config/paths.py
# To migrate: cp ~/Downloads/PublicPoolData/Employment/*.dta data/reference/emsi/
DEFAULT_DATA_DIR = EMSI_DIR

# ── Static lookup tables (Emsi/BLS constants, not industry-specific) ─────────

OCC_FAMILY_NAMES = {
    1:  "Management Occupations",
    2:  "Business and Financial Occupations",
    3:  "Computer, Architecture, Engineering, and Science",
    4:  "Education, Legal, Social Service",
    5:  "Healthcare Occupations",
    6:  "Protective Service",
    7:  "Personal Service",
    8:  "Sales",
    9:  "Office and Administrative Support",
    10: "Construction, Extraction, Maintenance, and Repair",
    11: "Production and Transportation Occupations",
    12: "All other occupations",
}

CLUSTER_NAMES = {
    1:  "All other",
    2:  "Construction",
    3:  "Educ/Legal/Social Services",
    4:  "Engineer/Sci/Arch",
    5:  "Healthcare",
    6:  "IT",
    7:  "Maintenance/Repair",
    8:  "Mgmt/Biz/Financial",
    9:  "Office & Admin Sppt",
    10: "Personal Service",
    11: "Production",
    12: "Protective Services",
    13: "Sales",
    14: "Transportation",
}

ISA_COLS = [
    "isaProbSolvdiff", "isa2waycommdiff", "isaTeachdiff", "isaMgPpldiff",
    "isaGrossMotordiff", "isaEquipRepMntdiff", "isaSensPercdiff", "isaQuantdiff",
    "isaFocAttndiff", "isaServPersddiff", "isaCreatvtydiff", "isaFineMotordiff",
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_dta(path: Path) -> pd.DataFrame:
    try:
        import pyreadstat
        df, _ = pyreadstat.read_dta(str(path))
        logger.info("Loaded %s  (%d rows)", path.name, len(df))
        return df
    except ImportError:
        logger.info("pyreadstat unavailable, falling back to pandas for %s", path.name)
        return pd.read_stata(str(path))


def _load_industry_soc_map(session) -> dict[str, str]:
    """Read ref_industry_taxonomy → {industry_key: primary_occ_code}.

    This replaces the old hardcoded INDUSTRY_SOC_MAP.  The taxonomy table is
    the single source of truth for what SOC code represents each industry's
    front-line role.
    """
    rows = session.query(IndustryTaxonomy).all()
    result = {r.industry_key: r.primary_occ_code for r in rows if r.primary_occ_code}
    logger.info(
        "Loaded %d industry→SOC mappings from ref_industry_taxonomy (%d industries had no SOC)",
        len(result),
        sum(1 for r in rows if not r.primary_occ_code),
    )
    return result


def _find_best_origin_soc(
    target_soc: str,
    available_origins: set[str],
    wage_lookup: dict[str, float],
) -> str | None:
    """Return the best available Emsi origin SOC for a given target SOC code.

    Walk the SOC hierarchy from most-specific to broadest, picking the
    lowest-wage (most entry-level) candidate at each level.

    Hierarchy:
      1. Exact match          e.g. "35-3023"
      2. Minor group (5-char) e.g. "35-30"  → matches 35-3011, 35-3031, …
      3. Major group (2-char) e.g. "35"     → all food prep occupations
    """
    if target_soc in available_origins:
        return target_soc

    for prefix_len in (5, 2):
        prefix = target_soc[:prefix_len]
        candidates = [s for s in available_origins if s[:prefix_len] == prefix]
        if candidates:
            return min(candidates, key=lambda s: wage_lookup.get(s, 9999.0))

    return None


def _agg_trajectories(df_traj: pd.DataFrame) -> dict[int, dict]:
    """Aggregate Dashboard-trajectories by (CensusCode, YearsAfterStart).

    Returns { census_code: { "3yr": {...}, "5yr": {...}, "10yr": {...},
                              "job_zone": int } }
    """
    result: dict[int, dict] = {}
    for _, row in df_traj.iterrows():
        code = int(row["CensusCode"]) if pd.notna(row.get("CensusCode")) else None
        if code is None:
            continue
        yrs = int(row["YearsAfterStart"]) if pd.notna(row.get("YearsAfterStart")) else None
        if yrs not in (3, 5, 10):
            continue
        if code not in result:
            jz = row.get("JobZone")
            result[code] = {"job_zone": int(jz) if pd.notna(jz) else None}
        result[code][f"{yrs}yr"] = {
            "med_wage_growth":  row.get("WtMedWageGrowth"),
            "pct_earn_25plus":  row.get("PctWage25ormore"),
            "pct_same_cluster": row.get("PctSameCluster"),
        }
    return result


def _build_dest_industry_keys(
    soc_code: str,
    cluster_name: str | None,
    soc_to_industries: dict[str, list[str]],
    cluster_to_industries: dict[str, list[str]],
    soc_prefix5_to_industries: dict[str, list[str]],
    soc_prefix2_to_industries: dict[str, list[str]],
) -> list[str]:
    """Return internal_industry keys that are likely to hire workers with this SOC.

    Priority (each level adds industries not already included):
      1. Exact SOC match against ref_industry_taxonomy.primary_occ_code
      2. Same Emsi occupational cluster (broader industry bucket)
      3. Same SOC minor group (first 5 chars, e.g. "35-30") — programmatic
      4. Same SOC major group (first 2 chars, e.g. "35") — programmatic fallback

    All levels are derived from ref_industry_taxonomy data, not external maps.
    Deduplicates while preserving order (most specific first).
    """
    seen: set[str] = set()
    keys: list[str] = []

    def _add(source: list[str]) -> None:
        for k in source:
            if k not in seen:
                seen.add(k)
                keys.append(k)

    _add(soc_to_industries.get(soc_code, []))
    if cluster_name:
        _add(cluster_to_industries.get(cluster_name, []))
    _add(soc_prefix5_to_industries.get(soc_code[:5], []))
    _add(soc_prefix2_to_industries.get(soc_code[:2], []))
    return keys


# ── Main ──────────────────────────────────────────────────────────────────────

def run(data_dir: Path, dry_run: bool = False) -> None:
    # ── Init DB and load crosswalk ────────────────────────────────────────────
    engine = init_db()
    session = get_session(engine)

    try:
        industry_soc_map = _load_industry_soc_map(session)

        # ── Load source files ─────────────────────────────────────────────────
        df_emsi  = _load_dta(data_dir / "Emsi-dataset.dta")
        df_trans = _load_dta(data_dir / "Dashboard-transitions-dataset.dta")
        df_traj  = _load_dta(data_dir / "Dashboard-trajectories-dataset.dta")

        # ── Build trajectory lookup ───────────────────────────────────────────
        traj_lookup = _agg_trajectories(df_traj)
        logger.info("Trajectory lookup built for %d Census codes", len(traj_lookup))

        # ── Merge Emsi + transitions on (origin, dest) SOC ───────────────────
        df_trans_keyed = df_trans.rename(columns={
            "SOCCode":           "oesCode_origin",
            "TransitionSOCCode": "oesCode_dest",
            "TransitionOrder":   "transition_order",
            "Cluster":           "cluster_code",
        })
        merged = df_emsi.merge(
            df_trans_keyed[[
                "oesCode_origin", "oesCode_dest",
                "transition_order", "cluster_code", "CensusCode",
            ]],
            on=["oesCode_origin", "oesCode_dest"],
            how="left",
        )
        logger.info(
            "Merged Emsi (%d rows): %d with transition_order, %d without",
            len(df_emsi),
            merged["transition_order"].notna().sum(),
            merged["transition_order"].isna().sum(),
        )

        # ── Build unique occupation table from Emsi ───────────────────────────
        origin_meta = (
            df_emsi[["oesCode_origin", "occ_title_origin", "occ_family_origin", "h_median_origin"]]
            .drop_duplicates("oesCode_origin")
            .rename(columns={
                "oesCode_origin":    "soc_code",
                "occ_title_origin":  "title",
                "occ_family_origin": "occ_family_code",
                "h_median_origin":   "median_hourly_wage",
            })
        )
        dest_meta = (
            df_emsi[["oesCode_dest", "occ_title_dest", "occ_family_dest", "h_median_dest"]]
            .drop_duplicates("oesCode_dest")
            .rename(columns={
                "oesCode_dest":    "soc_code",
                "occ_title_dest":  "title",
                "occ_family_dest": "occ_family_code",
                "h_median_dest":   "median_hourly_wage",
            })
        )
        occ_df = (
            pd.concat([origin_meta, dest_meta])
            .drop_duplicates("soc_code")
            .reset_index(drop=True)
        )

        # Attach cluster_code from transitions (available for origin SOCs)
        cluster_map = (
            df_trans[["SOCCode", "CensusCode", "Cluster"]]
            .drop_duplicates("SOCCode")
            .rename(columns={"SOCCode": "soc_code", "Cluster": "cluster_code"})
        )
        occ_df = occ_df.merge(cluster_map, on="soc_code", how="left")

        logger.info("Unique occupations: %d", len(occ_df))

        # ── Build available-origin set + wage lookup for SOC fallback ─────────
        available_origins: set[str] = set(occ_df.loc[
            occ_df["soc_code"].isin(set(df_emsi["oesCode_origin"])), "soc_code"
        ])
        wage_lookup: dict[str, float] = dict(zip(
            occ_df["soc_code"],
            occ_df["median_hourly_wage"].fillna(9999.0),
        ))

        # Log which industry SOC codes needed fallback
        for ind, soc in sorted(industry_soc_map.items()):
            best = _find_best_origin_soc(soc, available_origins, wage_lookup)
            if best != soc:
                logger.info(
                    "  SOC fallback: %-28s %s → %s (%s)",
                    ind, soc,
                    best or "NONE",
                    wage_lookup.get(best, "?") if best else "",
                )

        # ── Build crosswalk structures for dest_industry_keys_json ───────────
        # 1. Exact SOC match: primary_occ_code == soc_code
        soc_to_industries: dict[str, list[str]] = defaultdict(list)
        for ind, soc in industry_soc_map.items():
            soc_to_industries[soc].append(ind)

        # 2. Cluster match: industries whose primary SOC is in the same Emsi cluster
        soc_cluster: dict[str, str] = {}
        for _, row in occ_df.iterrows():
            cc = int(row["cluster_code"]) if pd.notna(row.get("cluster_code")) else None
            name = CLUSTER_NAMES.get(cc)
            if name:
                soc_cluster[row["soc_code"]] = name

        cluster_to_industries: dict[str, list[str]] = defaultdict(list)
        for ind, soc in industry_soc_map.items():
            cname = soc_cluster.get(soc)
            if cname:
                cluster_to_industries[cname].append(ind)

        # 3. SOC-hierarchy match (programmatic fallback derived entirely from the taxonomy):
        #    For each industry, record its primary_occ_code's 5-char minor group and
        #    2-char major group. Any destination SOC sharing the same prefix will match.
        #    e.g. fast_food → 35-3023 → prefix "35-30" and "35"
        #    so "35-3031" (Waiters) inherits fast_food through the "35-30" prefix.
        soc_prefix5_to_industries: dict[str, list[str]] = defaultdict(list)
        soc_prefix2_to_industries: dict[str, list[str]] = defaultdict(list)
        for ind, soc in industry_soc_map.items():
            soc_prefix5_to_industries[soc[:5]].append(ind)
            soc_prefix2_to_industries[soc[:2]].append(ind)

        logger.info(
            "Crosswalk built: %d exact, %d clusters, %d minor-group prefixes, "
            "%d major-group prefixes",
            len(soc_to_industries),
            len(cluster_to_industries),
            len(soc_prefix5_to_industries),
            len(soc_prefix2_to_industries),
        )

        # ── Upsert mob_occupation ─────────────────────────────────────────────
        occ_upserted = 0
        for _, row in occ_df.iterrows():
            soc = row["soc_code"]
            if pd.isna(soc):
                continue

            fam_code  = int(row["occ_family_code"]) if pd.notna(row.get("occ_family_code")) else None
            cen_code  = int(row["CensusCode"])       if pd.notna(row.get("CensusCode"))       else None
            clus_code = int(row["cluster_code"])     if pd.notna(row.get("cluster_code"))     else None
            clus_name = CLUSTER_NAMES.get(clus_code)

            traj = traj_lookup.get(cen_code, {})
            t3   = traj.get("3yr",  {})
            t5   = traj.get("5yr",  {})
            t10  = traj.get("10yr", {})

            # primary internal_industry for this SOC (origin side)
            primary_industry = next(
                (ind for ind, s in industry_soc_map.items() if s == soc), None
            )

            # dest_industry_keys: which industries hire workers at this SOC
            dest_keys = _build_dest_industry_keys(
                soc, clus_name,
                soc_to_industries, cluster_to_industries,
                soc_prefix5_to_industries, soc_prefix2_to_industries,
            )

            vals = dict(
                census_code=cen_code,
                title=str(row["title"]) if pd.notna(row.get("title")) else soc,
                occ_family_code=fam_code,
                occ_family_name=OCC_FAMILY_NAMES.get(fam_code),
                cluster_code=clus_code,
                cluster_name=clus_name,
                median_hourly_wage=float(row["median_hourly_wage"]) if pd.notna(row.get("median_hourly_wage")) else None,
                job_zone=traj.get("job_zone"),
                internal_industry=primary_industry,
                dest_industry_keys_json=json.dumps(dest_keys) if dest_keys else None,
                traj_med_wage_growth_3yr=t3.get("med_wage_growth"),
                traj_med_wage_growth_5yr=t5.get("med_wage_growth"),
                traj_med_wage_growth_10yr=t10.get("med_wage_growth"),
                traj_pct_earn_25plus_3yr=t3.get("pct_earn_25plus"),
                traj_pct_earn_25plus_5yr=t5.get("pct_earn_25plus"),
                traj_pct_earn_25plus_10yr=t10.get("pct_earn_25plus"),
                traj_pct_same_cluster_3yr=t3.get("pct_same_cluster"),
            )

            existing = session.query(MobOccupation).filter_by(soc_code=soc).first()
            if existing:
                for k, v in vals.items():
                    setattr(existing, k, v)
            else:
                session.add(MobOccupation(soc_code=soc, **vals))
            occ_upserted += 1

        if not dry_run:
            session.commit()
        logger.info("mob_occupation: %d rows upserted", occ_upserted)

        # ── Upsert mob_transition ─────────────────────────────────────────────
        trans_upserted = 0
        trans_skipped  = 0

        existing_pairs: set[tuple] = {
            (r.origin_soc, r.dest_soc)
            for r in session.query(MobTransition.origin_soc, MobTransition.dest_soc).all()
        }

        batch: list[MobTransition] = []

        for _, row in merged.iterrows():
            origin = row.get("oesCode_origin")
            dest   = row.get("oesCode_dest")
            if pd.isna(origin) or pd.isna(dest):
                trans_skipped += 1
                continue

            isa_vals  = {col: float(row[col]) for col in ISA_COLS if pd.notna(row.get(col))}
            avg_gap   = sum(abs(v) for v in isa_vals.values()) / len(isa_vals) if isa_vals else None
            wage_chg  = float(row["med_wage_diff"])   if pd.notna(row.get("med_wage_diff"))   else None
            wage_dir  = int(row["category"])          if pd.notna(row.get("category"))        else None
            t_order   = int(row["transition_order"])  if pd.notna(row.get("transition_order")) else None
            fam_o     = int(row["occ_family_origin"]) if pd.notna(row.get("occ_family_origin")) else None
            fam_d     = int(row["occ_family_dest"])   if pd.notna(row.get("occ_family_dest"))   else None
            same_clus = (fam_o == fam_d) if (fam_o and fam_d) else None
            lic_new   = bool(row["lic_new"]) if pd.notna(row.get("lic_new")) else False

            common = dict(
                transition_order=t_order,
                wage_change_dollars=wage_chg,
                wage_direction=wage_dir,
                pct_upward=float(row["PctUp"])      if pd.notna(row.get("PctUp"))      else None,
                pct_lateral=float(row["PctLateral"]) if pd.notna(row.get("PctLateral")) else None,
                pct_downward=float(row["PctDown"])   if pd.notna(row.get("PctDown"))    else None,
                avg_skill_gap=avg_gap,
                skill_gap_json=json.dumps(isa_vals),
                requires_new_license=lic_new,
                same_cluster=same_clus,
            )

            if (origin, dest) in existing_pairs:
                existing = (
                    session.query(MobTransition)
                    .filter_by(origin_soc=origin, dest_soc=dest)
                    .first()
                )
                if existing:
                    for k, v in common.items():
                        setattr(existing, k, v)
            else:
                batch.append(MobTransition(origin_soc=origin, dest_soc=dest, **common))
                existing_pairs.add((origin, dest))

            trans_upserted += 1

            if len(batch) >= 5000:
                if not dry_run:
                    session.bulk_save_objects(batch)
                    session.commit()
                batch.clear()
                logger.info("  ... %d transitions committed", trans_upserted)

        if batch and not dry_run:
            session.bulk_save_objects(batch)
            session.commit()

        logger.info(
            "mob_transition: %d upserted, %d skipped",
            trans_upserted, trans_skipped,
        )

        # ── Summary: SOC coverage per industry ───────────────────────────────
        logger.info("\nIndustry → best origin SOC coverage:")
        for ind, soc in sorted(industry_soc_map.items()):
            best = _find_best_origin_soc(soc, available_origins, wage_lookup)
            status = "exact" if best == soc else (f"fallback→{best}" if best else "MISSING")
            logger.info("  %-28s %s  [%s]", ind, soc, status)

        if dry_run:
            logger.info("DRY RUN — no changes written")
        else:
            logger.info("Done.")

    except Exception as e:
        session.rollback()
        logger.error("Failed: %s", e)
        raise
    finally:
        session.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Populate mobility graph tables")
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run(Path(args.data_dir), dry_run=args.dry_run)
