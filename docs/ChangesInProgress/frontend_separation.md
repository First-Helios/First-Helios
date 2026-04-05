# Frontend/Backend Service Separation

**Date:** 2026-04-04
**Status:** Phase 1 Complete — Local Testing Ready
**Branch:** DataVisTestFilter

---

## Overview

The First Helios frontend has been extracted into its own repository (`First-Helios_Frontend/`) to operate as an independent service, decoupled from the backend API server.

## Completed Milestones

### M1: Frontend File Migration
- Copied `frontend/` contents (index.html, js/, css/) to `First-Helios_Frontend/`
- Files: index.html, js/app.js, js/h3map.js, js/jobfinder.js, js/eventfinder.js, js/pathfinder.js, css/style.css

### M2: API Connection Decoupling
- Created `js/config.js` — centralized API base URL resolution
- Updated all 5 JS modules to use `window.HELIOS_API_BASE` instead of same-origin relative URLs
- Configuration priority: `window.HELIOS_CONFIG.apiBase` > `<meta name="api-base">` > default `http://localhost:8765`
- **Files modified:** app.js, pathfinder.js, h3map.js, jobfinder.js, eventfinder.js

### M3: Independent Static Server
- Created `serve.py` — lightweight Python HTTP server (port 3000)
- No additional dependencies required (uses stdlib `http.server`)
- Configurable via `--port` and `--bind` flags

### M4: API Contract Documentation
- Created `docs/API_CONTRACT.md` in frontend repo
- Inventoried all 13 API endpoints the frontend depends on
- Documented request parameters and response conventions
- Noted CORS requirements for cross-origin operation

### M5: Local Verification
- Backend on `:8765` + Frontend on `:3000` — both operational
- CORS already enabled on backend (`CORS(app)` in server.py)
- All static assets serve correctly from independent server

## Data Connection Inventory

| Module | Endpoints Used | Connection Pattern |
|--------|---------------|-------------------|
| app.js | /api/ref/summary, /api/targeting, /api/map-employers, /api/jobs/categories | `API_BASE + '/api/...'` via fetch() |
| h3map.js | /api/h3-map | `HELIOS_API_BASE + '/api/...'` via fetch() |
| jobfinder.js | /api/jobs/h3-map, /api/jobs/listings | `HELIOS_API_BASE + '/api/...'` via fetch() |
| eventfinder.js | /api/events/h3-map, /api/events/listings | `HELIOS_API_BASE + '/api/...'` via fetch() |
| pathfinder.js | /api/mobility/occupations, /api/mobility/paths, /api/mobility/employers | `API_BASE + '/api/...'` via fetch() |

## Remaining Work (Phase 2)

### OrangePi Deployment Migration
- [ ] Create systemd unit files for both services (backend API + frontend static)
- [ ] Configure auto-pull / self-updating mechanism for frontend repo
- [ ] Set `<meta name="api-base">` to OrangePi backend IP/hostname
- [ ] Restrict CORS on backend to frontend origin only (currently allows all)

### Backend Cleanup
- [ ] Optionally remove `static_folder="frontend"` and static file serving routes from server.py
- [ ] Or keep as fallback for single-machine deployments

### Monitoring
- [ ] Health check endpoint on backend (`/api/health`) for frontend to poll
- [ ] Frontend connection status indicator (detect backend unreachable)

---

*This document tracks the frontend separation work. Update as phases complete.*
