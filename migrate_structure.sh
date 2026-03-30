#!/bin/bash
set -e
cd /home/fortune/CodeProjects/First-Helios

# ─── SCRAPERS → COLLECTORS (tracked: git mv, untracked: mv) ──────────────────
echo "=== Reorganizing scrapers/ → collectors/ ==="
mkdir -p collectors/job_boards
mkdir -p collectors/labor_data
mkdir -p collectors/employer_data
mkdir -p collectors/sentiment
mkdir -p collectors/reference

# Root utilities — tracked
git mv scrapers/__init__.py        collectors/__init__.py
git mv scrapers/base.py            collectors/base.py
git mv scrapers/geocoding.py       collectors/geocoding.py
git mv scrapers/playwright_fallback.py collectors/playwright_fallback.py
# Root utilities — untracked
mv scrapers/cache.py               collectors/cache.py

# Job boards — tracked
git mv scrapers/jobspy_adapter.py  collectors/job_boards/jobspy_adapter.py
# Job boards — untracked
mv scrapers/jobicy_adapter.py      collectors/job_boards/jobicy_adapter.py
mv scrapers/juju_adapter.py        collectors/job_boards/juju_adapter.py
mv scrapers/serpapi_adapter.py     collectors/job_boards/serpapi_adapter.py
mv scrapers/theirstack_adapter.py  collectors/job_boards/theirstack_adapter.py
mv scrapers/activejobs_adapter.py  collectors/job_boards/activejobs_adapter.py
mv scrapers/workday_gov_adapter.py collectors/job_boards/workday_gov_adapter.py
mv scrapers/usajobs_adapter.py     collectors/job_boards/usajobs_adapter.py

# Labor data — tracked
git mv scrapers/bls_adapter.py     collectors/labor_data/bls_adapter.py
git mv scrapers/cbp_adapter.py     collectors/labor_data/cbp_adapter.py
git mv scrapers/qcew_adapter.py    collectors/labor_data/qcew_adapter.py
# Labor data — untracked
mv scrapers/nlrb_adapter.py        collectors/labor_data/nlrb_adapter.py
mv scrapers/warn_adapter.py        collectors/labor_data/warn_adapter.py

# Employer data — tracked
git mv scrapers/alltheplaces_adapter.py collectors/employer_data/alltheplaces_adapter.py
git mv scrapers/osm_adapter.py          collectors/employer_data/osm_adapter.py
git mv scrapers/overture_adapter.py     collectors/employer_data/overture_adapter.py

# Sentiment — tracked
git mv scrapers/careers_api.py     collectors/sentiment/careers_api.py
git mv scrapers/reddit_adapter.py  collectors/sentiment/reddit_adapter.py
git mv scrapers/reviews_adapter.py collectors/sentiment/reviews_adapter.py

# Reference — untracked
mv scrapers/manual_ingest.py       collectors/reference/manual_ingest.py
mv scrapers/oews_manual_ingest.py  collectors/reference/oews_manual_ingest.py
mv scrapers/revelio_ingest.py      collectors/reference/revelio_ingest.py
mv scrapers/texaswages_ingest.py   collectors/reference/texaswages_ingest.py

rmdir scrapers

# Add __init__.py to each new subdir
touch collectors/job_boards/__init__.py
touch collectors/labor_data/__init__.py
touch collectors/employer_data/__init__.py
touch collectors/sentiment/__init__.py
touch collectors/reference/__init__.py

echo "=== Renaming other directories (all untracked — plain mv) ==="
mv listings  postings
mv Data_analysis notebooks
mv archieve  archive
mv dev_toolkit dev
mv future_plans/web_scraping dev/experiments
rmdir future_plans

echo "=== Moving doc clutter into docs/ ==="
mv CLAUDE_DATA_ENGINEERING_HANDOFF.md docs/CLAUDE_DATA_ENGINEERING_HANDOFF.md
mkdir -p docs/todos
mv Todos/StaffingEngine.md docs/todos/StaffingEngine.md
rmdir Todos

echo "=== Import path rewrites ==="
PY_FILES=$(find . -name "*.py" \
  -not -path "./.git/*" \
  -not -path "./.venv/*" \
  -not -path "./migrate_structure.sh")

# listings → postings
echo "$PY_FILES" | xargs sed -i \
  's/from listings\./from postings./g; s/import listings\./import postings./g'

# scrapers utilities → collectors root
for mod in base cache geocoding playwright_fallback; do
  echo "$PY_FILES" | xargs sed -i \
    "s/from scrapers\.${mod}/from collectors.${mod}/g; s/import scrapers\.${mod}/import collectors.${mod}/g"
done

# scrapers → collectors.job_boards
for mod in jobspy_adapter jobicy_adapter usajobs_adapter juju_adapter \
           serpapi_adapter theirstack_adapter activejobs_adapter workday_gov_adapter; do
  echo "$PY_FILES" | xargs sed -i \
    "s/from scrapers\.${mod}/from collectors.job_boards.${mod}/g; s/import scrapers\.${mod}/import collectors.job_boards.${mod}/g"
done

# scrapers → collectors.labor_data
for mod in bls_adapter qcew_adapter cbp_adapter nlrb_adapter warn_adapter; do
  echo "$PY_FILES" | xargs sed -i \
    "s/from scrapers\.${mod}/from collectors.labor_data.${mod}/g; s/import scrapers\.${mod}/import collectors.labor_data.${mod}/g"
done

# scrapers → collectors.employer_data
for mod in overture_adapter alltheplaces_adapter osm_adapter; do
  echo "$PY_FILES" | xargs sed -i \
    "s/from scrapers\.${mod}/from collectors.employer_data.${mod}/g; s/import scrapers\.${mod}/import collectors.employer_data.${mod}/g"
done

# scrapers → collectors.sentiment
for mod in reviews_adapter reddit_adapter careers_api; do
  echo "$PY_FILES" | xargs sed -i \
    "s/from scrapers\.${mod}/from collectors.sentiment.${mod}/g; s/import scrapers\.${mod}/import collectors.sentiment.${mod}/g"
done

# scrapers → collectors.reference
for mod in manual_ingest oews_manual_ingest revelio_ingest texaswages_ingest; do
  echo "$PY_FILES" | xargs sed -i \
    "s/from scrapers\.${mod}/from collectors.reference.${mod}/g; s/import scrapers\.${mod}/import collectors.reference.${mod}/g"
done

echo "=== Staging everything ==="
git add -A

echo ""
echo "=== Verifying no stale references remain ==="
echo -n "  'from scrapers.'  : "
grep -r "from scrapers\." . --include="*.py" --exclude-dir=".git" --exclude-dir=".venv" 2>/dev/null || echo "none"
echo -n "  'from listings.'  : "
grep -r "from listings\." . --include="*.py" --exclude-dir=".git" --exclude-dir=".venv" 2>/dev/null || echo "none"

echo ""
echo "=== Final structure ==="
ls -1

echo ""
echo "=== Done — run: git status ==="
