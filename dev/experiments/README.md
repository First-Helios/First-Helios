# Future Plans: Web Scraping

This directory contains scrapers that target **specific business websites** (Workday career portals, company career pages, etc.).

These are architecturally distinct from the main project's public API consumption because they require:

- **Anti-bot handling** — Cloudflare, CAPTCHAs, JS rendering
- **Session management** — cookies, authentication flows
- **Per-site maintenance** — each company's career portal has unique DOM structure
- **Dedicated infrastructure** — headless browsers, proxy rotation

## Files

| File | What It Scrapes | Original Location |
|---|---|---|
| `careers_api.py` | Starbucks Workday careers API (JSON endpoint) | `scrapers/careers_api.py` |
| `workday_scraper.py` | Starbucks Workday SPA via Playwright headless browser | `scrapers/playwright_fallback.py` (WorkdayScraper class) |

## When to Reactivate

These scrapers should be reactivated as a **separate project** when:
1. The public data pipeline (JobSpy, BLS, Overture, etc.) is fully operational
2. Dedicated infrastructure for headless browsing is available
3. There's a clear need for company-specific data that public APIs can't provide

## Dependencies

- `playwright` + Chromium (for WorkdayScraper)
- `requests` (for CareersAPIScraper)
- Project root on `sys.path` for `config.loader`, `scrapers.base`, `backend.database`
