# Data Dictionary — Collector Sources

Field-level reference for every external data source feeding First-Helios.
All sources produce a `ScraperSignal` (see [ScraperSignal fields](#scrapersignal-common-fields)) which flows into the job posting ingest pipeline.

---

## ScraperSignal — Common Fields

Every adapter returns `list[ScraperSignal]`. These fields are the same regardless of source.

| Field | Type | Description |
|---|---|---|
| `store_num` | str | Tag string — e.g. `THEIRSTACK-austin_tx`. Not a real store number for job-board sources. |
| `chain` | str | Adapter identifier — e.g. `theirstack`, `serpapi_google_jobs`, `active_jobs_db` |
| `source` | str | Source key used for rate tracking — matches `API_SOURCE_REGISTRY` entry |
| `signal_type` | str | Always `"listing"` for job-board adapters |
| `value` | float | Always `1.0` for job-board adapters (count signal) |
| `metadata` | dict | Source-specific fields — see per-source tables below |
| `observed_at` | datetime | `date_posted` from API if available, else UTC now |
| `wage_min` | float \| None | Minimum salary — yearly unless `wage_period="hourly"` |
| `wage_max` | float \| None | Maximum salary |
| `wage_period` | str \| None | `"hourly"` or `"yearly"` |
| `role_title` | str \| None | Job title string |
| `source_url` | str \| None | Best available apply/listing URL |

### metadata keys shared by all job-board adapters

| Key | Type | Description |
|---|---|---|
| `company` | str | Employer name as returned by the API |
| `employer` | str | Duplicate of `company` — used by ingest pipeline |
| `job_url` | str \| None | Primary apply or listing URL |
| `date_posted` | str \| None | ISO 8601 string of the posted date |
| `location` | str \| None | Raw location string from API (e.g. `"Austin, TX"`) |
| `address` | str \| None | Best geocodable address extracted from the record |
| `address_method` | str \| None | How `address` was obtained — see Address Methods below |
| `job_excerpt` | str \| None | First 500 characters of job description (HTML stripped) |
| `category` | str \| None | Industry or job category |
| `job_type` | str \| None | Employment type — `"Full-time"`, `"Part-time"`, `"Contract"`, etc. |
| `is_remote` | bool \| None | `True` if listing is marked remote; `None` if unknown |
| `source_platform` | str | Human-readable platform name |
| `external_path` | str | Stable dedup key — `source:id` or SHA-256 hash of identifying fields |

### Address Methods

`address_method` describes how the `address` field was populated:

| Value | Meaning |
|---|---|
| `pyap` | Parsed by `pyap` library — full structured US address with state abbreviation |
| `regex` | Extracted by `_STREET_RE` fallback — street number + road type, no state required |
| `location_field` | Taken directly from API location field (e.g. `"Austin, TX 78704"`) |
| `city_state` | Assembled from structured city + state_code fields |
| `fallback_city` | City matched to Austin-area list, `, TX` appended |
| `provided_coords` | API returned lat/lng — no address string needed |
| `None` | No geocodable address found |

---

## TheirStack (`theirstack`)

**Endpoint:** `POST https://api.theirstack.com/v1/jobs/search`
**Auth:** `Authorization: Bearer $THEIRSTACK_API_KEY`
**Budget:** ~200 calls/month cap. Current config: 6 calls/day (4-hour intervals).
**Cache TTL:** 240 min (matches poll interval)
**Collection strategy:** Broad — no title/keyword filters. Location patterns cover Austin, Round Rock, Cedar Park, Georgetown, Pflugerville. Limit 25 results per call.

### TheirStack API response fields mapped to ScraperSignal

| API Field | Signal Field | Notes |
|---|---|---|
| `id` | `external_path` | `theirstack:<id>` — SHA-256 fallback if missing |
| `job_title` | `role_title` | |
| `company_object.name` or `company_name` | `metadata.company` | `company_object.name` preferred |
| `final_url` | `source_url` | Employer-site URL — preferred over board URL |
| `url` | `source_url` | Listing page URL — used if `final_url` absent |
| `source_url` | `source_url` | Board URL — last fallback |
| `job_location` | `metadata.location` | Raw location string |
| `long_location` | `metadata.address` | Richest location string — may include zip code |
| `location` / `short_location` | `metadata.address` | City-level fallback |
| `locations[0].city + state_code` | `metadata.address` | Structured geo fallback |
| `company_object.city + state` | `metadata.address` | Company-level fallback |
| `latitude` / `longitude` | signal coords | Passed directly to ingest when present |
| `remote` | `metadata.is_remote` | Boolean |
| `company_object.industry` | `metadata.category` | |
| `company_object.num_employees` | `metadata.company_size` | Coerced to int |
| `date_posted` or `discovered_at` | `observed_at` | `date_posted` preferred |
| `min_annual_salary_usd` | `wage_min` | Yearly |
| `max_annual_salary_usd` | `wage_max` | Yearly |
| `job_description` | `metadata.job_excerpt` | HTML stripped, truncated to 500 chars |

### apply_urls

`metadata.apply_urls` is a list `[final_url, listing_url, board_url]` with None entries removed. Gives ingest pipeline all available links ranked by preference.

---

## SerpAPI Google Jobs (`serpapi_google_jobs`)

**Endpoint:** `GET https://serpapi.com/search.json?engine=google_jobs`
**Auth:** `api_key=$SERPAPI_KEY` (query param)
**Budget:** 250 searches/month. Current config: 8 calls/day (3-hour intervals), rotating through 20 industry queries.
**Cache TTL:** 180 min per query (per-industry keys: `serpapi_google_jobs__<safe_query>`)
**Collection strategy:** One call per run, `start=0`, `location=Austin, Texas, United States`. Query rotates through `config/search_rotation.yaml` — each run targets a different industry.

### SerpAPI response fields mapped to ScraperSignal

| API Field | Signal Field | Notes |
|---|---|---|
| `job_id` | `external_path` | `serpapi:<job_id>` — SHA-256 fallback |
| `title` | `role_title` | |
| `company_name` | `metadata.company` | |
| `location` | `metadata.location` | Raw location string — may include `"(+N others)"` suffix (stripped) |
| `apply_options[0].link` | `source_url` | Direct job-board link — preferred |
| `source_link` | `source_url` | Fallback |
| `share_link` | `source_url` | Google Jobs share URL — last fallback |
| `description` | `metadata.job_excerpt` | Truncated to 500 chars; also searched for street address |
| `detected_extensions.salary` | `wage_min/max/period` | Parsed from string e.g. `"$50,000 - $70,000 a year"` |
| `detected_extensions.schedule_type` | `metadata.job_type` | `"Full-time"`, `"Remote"`, etc. |
| `detected_extensions.posted_at` | `observed_at` | Parsed with dateutil |

### SerpAPI salary string parsing

`_parse_salary()` handles these formats:

| Input | wage_min | wage_max | wage_period |
|---|---|---|---|
| `"$50,000 - $70,000 a year"` | 50000.0 | 70000.0 | yearly |
| `"$25 an hour"` | 25.0 | None | hourly |
| `"$18 - $22 an hour"` | 18.0 | 22.0 | hourly |
| `"80K - 100K annually"` | 80000.0 | 100000.0 | yearly |

### is_remote detection (SerpAPI)

Checked in order — first match wins:
1. `detected_extensions.schedule_type` contains `"Remote"`
2. `location` contains `"Remote"` or `"Anywhere"`
3. `description` contains word `"remote"` (case-insensitive)

---

## RapidAPI Active Jobs DB (`rapidapi_activejobs`)

**Endpoint:** `GET https://active-jobs-db.p.rapidapi.com/active-ats-7d` (primary)
**Auth:** `X-RapidAPI-Key: $RAPIDAPI_KEY` + `X-RapidAPI-Host` headers
**Budget:** 25 requests/month, 250 jobs/month hard caps. Current config: 1 call/day.
**Cache TTL:** 1440 min (24 hours)
**Collection strategy:** One call, `limit=100`. Three candidate endpoints tried in order until one returns data. Results filtered to Austin/Round Rock bounding box (lat 30.0–30.75, lng -98.3 to -97.4) or city string match.

### Endpoint discovery order

| Priority | Path | Params |
|---|---|---|
| 1 | `/active-ats-7d` | `limit=100, location_filter=Austin.*TX` |
| 2 | `/active-ats-7d` | `limit=100, job_country=US` (local filter applied after) |
| 3 | `/v1/jobs` | `limit=100, location=Austin,TX` |

### Active Jobs DB response fields mapped to ScraperSignal

| API Field | Signal Field | Notes |
|---|---|---|
| `id` or `job_id` | `external_path` | `activejobs:<id>` — SHA-256 fallback |
| `title` / `job_title` / `position` | `role_title` | Tried in order |
| `company_name` / `company` / `employer` / `organization` | `metadata.company` | Tried in order |
| `url` / `job_url` / `apply_url` / `link` | `source_url` | Tried in order |
| `locations_derived[0]` | `metadata.location` | Preferred — API-derived list |
| `location` / `job_location` / `city` | `metadata.location` | Fallback |
| `lats_derived` / `lngs_derived` | Austin filter | List of floats — all pairs checked against bbox |
| `latitude` / `lat` | Austin filter | Scalar fallback |
| `longitude` / `lng` / `lon` | Austin filter | Scalar fallback |
| `remote_derived` | `metadata.is_remote` | Boolean from API; falls back to `"remote" in location` |
| `category` / `industry` / `job_category` | `metadata.category` | |
| `job_type` / `employment_type` / `type` | `metadata.job_type` | |
| `date_posted` / `posted_at` / `published_at` / `created_at` | `observed_at` | Tried in order |
| `salary_min` / `min_salary` / `wage_min` | `wage_min` | |
| `salary_max` / `max_salary` / `wage_max` | `wage_max` | |
| `salary_period` / `wage_period` | `wage_period` | `"hourly"` if contains "hour", else `"yearly"` |
| `description` / `job_description` | `metadata.job_excerpt` | HTML stripped, 500 chars |

---

## Jobicy (`jobicy`)

**Endpoint:** `GET https://jobicy.com/api/v2/remote-jobs`
**Auth:** None (public)
**Budget:** ToS limit once per hour. Current config: interval 1h.
**Cache TTL:** Per run (hourly gate enforced by `_MIN_INTERVAL_MINUTES=60`)
**Collection strategy:** `count=100, geo=usa`. All results are remote — `is_remote=True` always. H3 cells are NULL for listings with no geocodable address. Rotates through `config/search_rotation.yaml` industry tags.

| API Field | Signal Field | Notes |
|---|---|---|
| `id` | `external_path` | `jobicy:<id>` |
| `jobTitle` | `role_title` | |
| `companyName` | `metadata.company` | |
| `url` | `source_url` | |
| `jobGeo` | `metadata.address` | Only used if it looks like a real address (not `"USA"`, `"Remote"`, etc.) |
| `jobIndustry` | `metadata.category` | May be list — joined as comma-separated string |
| `jobType` | `metadata.job_type` | May be list |
| `pubDate` | `observed_at` | |
| `annualSalaryMin` | `wage_min` | Yearly |
| `annualSalaryMax` | `wage_max` | Yearly |
| — | `metadata.is_remote` | Always `True` |

---

## JobSpy (`jobspy`)

**Source key:** `jobspy`
**Libraries:** `python-jobspy` — scrapes LinkedIn, Indeed, Glassdoor, ZipRecruiter
**Budget:** No API key; rate-limited by target sites. Current config: cron 4:00 AM daily.
**Strategy:** Austin TX location, searches for multiple industry/role terms across the 20 search rotation entries.

| ScraperSignal field | Source | Notes |
|---|---|---|
| `role_title` | `title` | |
| `metadata.company` | `company` | |
| `metadata.address` | `location` | City-level string or street address |
| `source_url` | `job_url` | |
| `wage_min/max/period` | `min_amount/max_amount/interval` | JobSpy normalizes salary internally |
| `metadata.is_remote` | `is_remote` | Boolean |
| `metadata.job_type` | `job_type` | |
| `metadata.source_platform` | `site` | `"linkedin"`, `"indeed"`, `"glassdoor"`, `"zip_recruiter"` |

---

## USAJobs (`usajobs`)

**Endpoint:** `GET https://data.usajobs.gov/api/search`
**Auth:** `Authorization-Key: $USAJOBS_API_KEY` + `User-Agent` (email)
**Budget:** Up to 1000 results/day. Current config: cron 6:00 AM daily.
**Strategy:** Austin TX location filter, all open federal postings.

| API Field | Signal Field | Notes |
|---|---|---|
| `MatchedObjectDescriptor.PositionTitle` | `role_title` | |
| `MatchedObjectDescriptor.OrganizationName` | `metadata.company` | Agency name |
| `MatchedObjectDescriptor.PositionLocationDisplay` | `metadata.location` | |
| `MatchedObjectDescriptor.PositionURI` | `source_url` | |
| `MatchedObjectDescriptor.PositionRemuneration[0].MinimumRange` | `wage_min` | |
| `MatchedObjectDescriptor.PositionRemuneration[0].MaximumRange` | `wage_max` | |
| `MatchedObjectDescriptor.PositionRemuneration[0].RateIntervalCode` | `wage_period` | `"PA"` → yearly, `"PH"` → hourly |
| `MatchedObjectDescriptor.PublicationStartDate` | `observed_at` | |

---

## City of Austin Workday (`austin_gov`)

**Source key:** `workday_gov`
**URL:** City of Austin Workday career portal
**Budget:** No API key; public scrape. Current config: cron 5:30 AM daily.
**Strategy:** All active municipal job postings.

| Field | Notes |
|---|---|
| `role_title` | Position title |
| `metadata.company` | Always `"City of Austin"` |
| `metadata.address` | Austin, TX (city-level) |
| `metadata.is_remote` | Generally False for municipal roles |

---

## Notes on data quality

**Address coverage by source:**

| Source | Street address rate | Typical fallback |
|---|---|---|
| TheirStack | ~30% (pyap/regex from description) | `long_location` city+zip |
| SerpAPI | ~20% (pyap/regex from description) | `location` city field |
| ActiveJobs | ~15% | `locations_derived[0]` city string |
| Jobicy | ~5% | `jobGeo` — usually `"USA"` (filtered out) |
| JobSpy | ~40% | City-level `location` field |
| USAJobs | ~60% | `PositionLocationDisplay` city string |

**External ID stability:**

All adapters use `source:native_id` as the primary dedup key (e.g. `theirstack:12345`). When the native ID is absent, a SHA-256 hash of `(url or company+title+location)` is used. This hash is stable across re-runs as long as the identifying fields don't change.

**NULL H3 cells:**

A posting with `h3_r7=NULL` and `h3_r8=NULL` means no geocodable address was found. This is expected for fully remote roles and city-only location strings that don't resolve to a point. The posting is still valid and searchable by employer match.
