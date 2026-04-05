# Geocoding Agent Guide — First Helios Location Pipeline

Every data adapter that produces a physical location (jobs, events, venues, employers) must yield a geocodable address.
This guide documents the complete geocoding pipeline, how to extract
location data from API responses, and the priority rules every adapter
must follow when constructing the `"address"` metadata key.

---

## 1. End-to-End Pipeline

```
Adapter  →  ScraperSignal.metadata["address"]
         →  listings/ingest.py  _geocode_if_needed()
         →  scrapers/geocoding.py  geocode()
         →  (lat, lng)
         →  h3.latlng_to_cell(lat, lng, 7)  →  h3_r7
         →  h3.latlng_to_cell(lat, lng, 8)  →  h3_r8
         →  stored in job_postings (lat, lng, h3_r7, h3_r8)
```

### What triggers geocoding

`listings/ingest.py::_geocode_if_needed(posting_lat, posting_lng, raw_address)`:

```python
# 1. Pre-supplied coordinates — cheapest, always prefer
if lat is not None and lng is not None:
    return lat, lng, "provided"

# 2. No address at all — silently skipped, no H3
if not address:
    return None, None, None

# 3. Geocode the address string
glat, glng = geocode(address)
```

`raw_address` is read from signal metadata exactly once:

```python
if "address" in meta:
    raw_address = meta["address"]   # explicit None = no address (respected)
else:
    raw_address = meta.get("location_text") or meta.get("location")
```

**Critical:** Always include `"address"` as an explicit key in signal metadata.
If set to `None`, the ingest layer stops there and will NOT fall through to
`meta["location"]`. Use `None` only when you are certain no address exists.
If the best you have is a city string, pass that — do NOT pass `None`.

---

## 2. geocode() Resolution Order

`scrapers/geocoding.py::geocode(address)`:

| Priority | Trigger | Example |
|----------|---------|---------|
| 1 | Facility/landmark index (`data/reference/facility_index.json`) | "Domain Northside" |
| 2 | City-only override dict (address has no digits) | "Austin, TX" → (30.2672, -97.7431) |
| 3 | Nominatim full address | "123 Main St, Austin, TX 78701" |
| 4 | Nominatim simplified (suite/ZIP stripped) | "123 Main St, Austin, TX" |
| 5 | `(None, None)` | address could not be resolved |

### City-only overrides (no Nominatim call, always succeed)

```python
_OVERRIDES = {
    "Austin, TX":        (30.2672, -97.7431),
    "Round Rock, TX":    (30.5083, -97.6789),
    "Cedar Park, TX":    (30.5052, -97.8203),
    "Pflugerville, TX":  (30.4394, -97.6200),
    "Georgetown, TX":    (30.6333, -97.6781),
    "San Marcos, TX":    (29.8833, -97.9414),
    "Kyle, TX":          (29.9889, -97.8772),
    "Buda, TX":          (30.0852, -97.8392),
    "Lakeway, TX":       (30.3639, -97.9795),
    "Leander, TX":       (30.5788, -97.8531),
    "Del Valle, TX":     (30.1869, -97.6083),
}
```

A city-only address like `"Austin, TX"` **will produce valid H3 cells**
(city-center coordinates). This is the correct fallback for jobs that have
a city but no street address.

---

## 3. Address Priority Rules for Every Adapter

Apply these in order and stop at the first match:

```
1. lat + lng fields  →  pass directly as metadata["lat"] + metadata["lng"]
                         (bypasses geocoding entirely, most accurate)

2. Full street address  →  "123 Congress Ave, Austin, TX 78701"
                            from: address field, location_detail, description regex

3. Street + city  →  "123 Congress Ave, Austin, TX"
                      acceptable, Nominatim resolves well

4. City + state  →  "Austin, TX" / "Round Rock, TX"
                     covered by _OVERRIDES, always succeeds, gives city-center H3

5. City + state (constructed)  →  f"{city}, {state_abbrev}"
                                   when API provides city and state separately

6. City-only (with state inferred)  →  append ", TX" if Austin-area API
                                        e.g., company.city = "Austin" → "Austin, TX"

NEVER pass:  "USA" / "United States" / "Remote" / "Worldwide" / ""
             These are in _GEO_NOISE and will not geocode.
             Pass None instead of a noise string.
```

---

## 4. How to Inspect a New API Response

When integrating a new job API, run this pattern to discover what location
fields are available before writing the adapter:

```python
# Step 1 — Fetch a sample page and print all location-related keys
import json, requests, os
resp = requests.get(ENDPOINT, headers=headers, params=params, timeout=30)
jobs = resp.json()  # adjust for actual response structure
job = jobs[0]

# Print keys that look like location data
for k, v in job.items():
    if any(x in k.lower() for x in ['loc', 'city', 'state', 'country',
                                      'address', 'region', 'geo', 'lat', 'lng',
                                      'coord', 'zip', 'postal']):
        print(f"{k}: {v!r}")

# Step 2 — Check nested objects (company_object, location_info, etc.)
for k, v in job.items():
    if isinstance(v, dict):
        print(f"--- {k} ---")
        for nk, nv in v.items():
            print(f"  {nk}: {nv!r}")
```

Look for these common field patterns across job APIs:

| API Type | Typical Fields | Notes |
|----------|---------------|-------|
| LinkedIn-style | `location`, `city`, `state` | `location` often "City, ST" |
| ATS/enterprise | `jobLocation`, `addressLocality`, `addressRegion` | Schema.org format |
| Job board | `job_location`, `workplace_city`, `workplace_state` | Varies widely |
| Indeed/Google | `location`, `detected_extensions.address` | Structured |
| Company-centric | `company_object.city`, `company_object.state` | Employer HQ |
| GeoJSON | `geometry.coordinates` → `[lng, lat]` | Note: lng first! |

---

## 5. Adapter address_method Values

Set `metadata["address_method"]` to document how the address was obtained.
This is stored in `job_postings.address_method` for audit and improvement.

| Value | Meaning |
|-------|---------|
| `"provided_coords"` | API returned lat/lng directly |
| `"street"` | Full street address from structured field |
| `"pyap"` | Street address extracted from text by pyap library |
| `"regex"` | Street address extracted from text by `_STREET_RE` |
| `"city_state"` | Constructed from separate city + state fields |
| `"job_location"` | `job_location` field used as-is (city-level) |
| `"location_field"` | `location` or similar field used as-is |
| `"fallback_city"` | City name appended with ", TX" — last resort |
| `None` | No address found |

---

## 6. Common API-Specific Patterns

### APIs that return lat/lng directly
Pass them through `metadata["lat"]` and `metadata["lng"]`. The ingest
layer will use them as `geocode_source="provided"` and skip Nominatim:

```python
signal = ScraperSignal(
    ...
    metadata={
        "address":  None,           # required key — explicit None OK when lat/lng provided
        "lat":      job["latitude"],
        "lng":      job["longitude"],
        ...
    }
)
```

### APIs with city + state as separate fields

```python
city  = (job.get("city") or company.get("city") or "").strip()
state = (job.get("state") or company.get("state") or "").strip()

if city and state:
    address = f"{city}, {state}"
    method  = "city_state"
elif city and city.lower() in AUSTIN_AREA_CITIES:
    address = f"{city}, TX"         # infer TX for known Austin-area cities
    method  = "fallback_city"
else:
    address = None
    method  = None
```

`AUSTIN_AREA_CITIES` (lowercase) to recognise when state is implicit:
```python
AUSTIN_AREA_CITIES = {
    "austin", "round rock", "cedar park", "pflugerville", "georgetown",
    "kyle", "buda", "lakeway", "leander", "del valle", "san marcos",
    "manor", "hutto", "taylor", "bastrop", "lockhart", "dripping springs",
}
```

### APIs with a combined location string

`"Austin, TX"` / `"Austin, TX, United States"` / `"Austin, Texas"`:

```python
_LOCATION_NORMALISE = {
    "united states": "US",
    "texas": "TX",
}

def normalise_location(loc: str) -> str:
    """'Austin, Texas, United States' → 'Austin, TX'"""
    for long, short in _LOCATION_NORMALISE.items():
        loc = re.sub(long, short, loc, flags=re.IGNORECASE)
    # strip trailing country if city+state already present
    loc = re.sub(r",\s*US$", "", loc).strip()
    return loc
```

### APIs that embed location in description text

Use the shared `_find_address()` pattern (pyap → regex) with length gates.
After extracting, always validate the result is not a false positive:

```python
_ADDR_MIN_LEN = 15   # shorter = likely just "123" or "Main St"
_ADDR_MAX_LEN = 120  # longer  = captured a paragraph

def _find_address(text: str) -> tuple[str, str] | None:
    """Try pyap first, fall back to _STREET_RE. Returns (address, method) or None."""
    try:
        import pyap
        found = pyap.parse(text, country='US')
        if found:
            candidate = str(found[0]).strip()
            if _ADDR_MIN_LEN <= len(candidate) <= _ADDR_MAX_LEN:
                return candidate, "pyap"
    except Exception:
        pass

    m = _STREET_RE.search(text)
    if m:
        candidate = m.group(0).strip()
        if _ADDR_MIN_LEN <= len(candidate) <= _ADDR_MAX_LEN:
            return candidate, "regex"

    return None
```

**Warning:** `_STREET_RE` produces false positives in salary text and bullet
lists. Always have a city/state fallback when description-extraction fails.

---

## 7. Required Signal Metadata Keys

Every job adapter's `ScraperSignal.metadata` dict MUST include:

```python
metadata = {
    # Required for geocoding (always present, even if None)
    "address":          str | None,   # best available location string
    "address_method":   str | None,   # how address was obtained (see section 5)

    # Required for ingest
    "company":          str,          # raw employer name
    "employer":         str,          # same as company
    "external_path":    str,          # stable unique ID for this source

    # Optional but valuable
    "lat":              float | None, # if API provides coordinates
    "lng":              float | None,
    "location":         str | None,   # human-readable location label (shown in UI)
    "is_remote":        bool | None,
    "job_url":          str | None,
    "date_posted":      str | None,   # ISO 8601
    "job_excerpt":      str | None,   # short description (≤500 chars)
    "category":         str | None,   # industry / job category
}
```

---

## 8. Verification Checklist

After writing a new adapter, run these checks before enabling ingest:

```bash
# 1. Dry-run — confirm signals are produced
python scrapers/my_adapter.py --no-ingest

# 2. Inspect address coverage in sample output
python3 -c "
import sys; sys.path.insert(0, '.')
from scrapers.my_adapter import MyAdapter
a = MyAdapter()
signals = a.scrape('austin_tx')
for s in signals[:5]:
    addr   = s.metadata.get('address')
    method = s.metadata.get('address_method')
    lat    = s.metadata.get('lat')
    print(f'{s.role_title[:35]:<35} | {str(addr)[:35]:<35} | {method} | lat={lat}')
"

# 3. After ingest, check geocoding hit rate
python3 -c "
import sys; sys.path.insert(0, '.')
from dotenv import load_dotenv; load_dotenv('.env')
from backend.database import get_session, init_db
from sqlalchemy import text
engine = init_db(); session = get_session(engine)
r = session.execute(text('''
    SELECT
        COUNT(*)                                           total,
        SUM(CASE WHEN h3_r7 IS NOT NULL THEN 1 ELSE 0 END)  has_h3,
        SUM(CASE WHEN raw_address IS NOT NULL THEN 1 ELSE 0 END) has_addr,
        SUM(CASE WHEN lat IS NOT NULL THEN 1 ELSE 0 END)    has_latlong
    FROM job_postings WHERE source = \'my_source\'
'''))
row = r.fetchone()
print(f'total={row[0]}  h3={row[1]}  addr={row[2]}  latlong={row[3]}')
session.close()
"
```

Target: **≥ 50 % of non-remote jobs** should have `h3_r7` populated.
Remote-only sources (Jobicy) will have 0 — that is expected.

---

## 9. Known Issues and Workarounds

### TheirStack — `company_object` has city but no state
TheirStack's `company_object` returns `city` but `state` is always `None`.
Use `AUSTIN_AREA_CITIES` to infer ", TX" for known cities:

```python
city = (company_obj.get("city") or "").strip()
if city.lower() in AUSTIN_AREA_CITIES:
    address, method = f"{city}, TX", "fallback_city"
elif city:
    address, method = f"{city}, US", "fallback_city"   # non-Austin, still geocodable
else:
    address, method = None, None
```

### SerpAPI Google Jobs — `location` field is city-level
SerpAPI's `location` key contains "Austin, TX" — a valid geocodable string.
It is stored under `"location"` in metadata, not `"address"`.
Fix: use `location` as the `"address"` value when no street is found:

```python
metadata = {
    "address":        extracted_addr or raw_location or None,
    "address_method": extracted_method or ("location_field" if raw_location else None),
    "location":       raw_location,   # human-readable label preserved separately
    ...
}
```

### Jobicy — remote jobs, address not meaningful
All Jobicy listings are `is_remote=True`. The `_GEO_NOISE` filter correctly
blocks "USA" / "Worldwide" geocoding. H3 cells will be NULL — this is correct
behaviour. The job finder shows remote listings in the sidebar (no hex).

### Nominatim rate limit
Nominatim enforces 1 request/second. For batches of 100+ jobs with street
addresses, expect ~2 minutes of geocoding at ingest time. City-only strings
hit `_OVERRIDES` and cost 0 Nominatim calls — so pushing as many addresses
to city-level as possible keeps ingest fast.
