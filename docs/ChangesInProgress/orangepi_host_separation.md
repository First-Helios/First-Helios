# OrangePi Host Configuration Separation

**Date:** 2026-04-05
**Status:** Deployed and Verified on OrangePi
**Repo:** First-Helios_Orangepi_Host

---

## Overview

OrangePi host infrastructure has been extracted into its own repository (`First-Helios_Orangepi_Host/`) to operate independently from the backend application code. This repo owns provisioning, service orchestration, reverse proxy, and auto-update — nothing application-specific.

## What Migrated

| Source (First-Helios) | Destination (Orangepi_Host) | Changes |
|---|---|---|
| `dev/opi5_setup.sh` | `scripts/provision.sh` | Adapted for 3-repo architecture; clones backend + frontend; installs systemd + nginx |
| `dev/update.sh` | `scripts/update.sh` | Now pulls 3 repos independently; only restarts changed services; host repo pulled first for config updates |
| `dev/sync_from_opi.sh` | `scripts/sync_from_opi.sh` | Moved as-is (dev convenience tool) |
| `docs/orangepi/README.md` | `docs/operations.md` | Expanded into full operations reference with multi-service architecture |
| (not in any repo) | `systemd/*.service`, `systemd/*.timer` | **NEW** — unit files previously only existed on OPi filesystem, now version-controlled |
| (not in any repo) | `nginx/helios.conf` | **NEW** — nginx config previously only existed on OPi filesystem, now version-controlled |
| — | `scripts/install-services.sh` | **NEW** — push updated configs to running OPi without full re-provision |

## What Did NOT Migrate (Stays in First-Helios)

- `server.py` — Flask API application
- `collector_main.py` — APScheduler standalone process
- `core/scheduler.py` — scheduler job definitions
- `config/scheduler.yaml` — job schedules and configuration
- `config/event_sources.yaml` — event source catalog
- All collectors, backend modules, database models
- `requirements.txt` — Python application dependencies
- `.env` / `.env.example` — application secrets and config

## New Systemd Services

| Unit File | Purpose |
|-----------|---------|
| `helios.service` | Gunicorn API (9 workers, 2 threads, :8765) |
| `helios-frontend.service` | Python static server (:3000) — **NEW** for separated frontend |
| `helios-update.service` | Oneshot: multi-repo git pull |
| `helios-update.timer` | Fires update every 5 minutes |
| `cpugov.service` | CPU governor → performance |

Note: `helios-collector.service` is intentionally NOT in this repo. The collector is an application concern managed by the backend repo.

## nginx Architecture Change

Previously nginx proxied port 80 directly to Gunicorn (:8765) which served both API and static files. Now:

```
nginx (:80)
  ├── /        → helios-frontend (:3000)  — static HTML/JS/CSS
  └── /api/    → helios (:8765)           — Flask API only
```

This means the frontend no longer relies on Flask's `send_from_directory`. The browser loads from the frontend service, and API calls route through nginx to the backend.

## Auto-Update Changes

The update script now manages 3 repos in priority order:

1. **Host repo first** — if systemd/nginx configs changed, `daemon-reload` and nginx reload happen before any app restarts
2. **Backend repo** — `pip install` if requirements changed, then `systemctl restart helios`
3. **Frontend repo** — `systemctl restart helios-frontend` (static files, fast restart)

Each repo is checked independently. Only services whose code actually changed are restarted. Silent exit when all repos are current (no log spam).

## Deploy Key Configuration

GitHub requires unique deploy keys per repo. Three separate ed25519 keys were generated on the OPi, with SSH host aliases routing each repo to its key:

| SSH Alias | Key File | GitHub Repo |
|-----------|----------|-------------|
| `github-backend` | `~/.ssh/github_deploy` | First-Helios |
| `github-frontend` | `~/.ssh/github_deploy_frontend` | First-Helios_Frontend |
| `github-host` | `~/.ssh/github_deploy_host` | First-Helios_Orangepi_Host |

Git remotes use the alias hostnames (e.g. `git@github-backend:4Fortune8/First-Helios.git`).

## OPi Deployment (2026-04-05) — Completed

- [x] Cloned Host and Frontend repos on OrangePi
- [x] Generated per-repo deploy keys with SSH host aliases
- [x] Added deploy keys to all 3 GitHub repos
- [x] Installed systemd units and nginx config
- [x] Added sudoers NOPASSWD for update script service commands (`/etc/sudoers.d/helios-update`)
- [x] Force-pulled backend to current main
- [x] Verified all services running: helios, helios-frontend, helios-update.timer, nginx
- [x] Verified frontend serves via nginx :80 (HTML + JS + CSS assets)
- [x] Verified API routes via nginx /api/ (ref/summary, mobility/occupations, jobs/categories)
- [x] Verified auto-update cycle completes successfully (status=0/SUCCESS)

## Remaining Work

### Frontend meta tag
- [ ] Set frontend `<meta name="api-base">` to `""` (empty — nginx handles routing, same origin)

### Backend Cleanup
- [ ] Optionally remove `dev/opi5_setup.sh`, `dev/update.sh`, `dev/sync_from_opi.sh` from backend repo
- [ ] Optionally remove `docs/orangepi/` from backend repo
- [ ] Update RUNBOOK.md to reference host repo for infrastructure operations
- [ ] Optionally remove `static_folder="frontend"` from server.py (no longer needed with nginx routing)

### Backend Cleanup
- [ ] Optionally remove `dev/opi5_setup.sh`, `dev/update.sh`, `dev/sync_from_opi.sh` from backend repo
- [ ] Optionally remove `docs/orangepi/` from backend repo
- [ ] Update RUNBOOK.md to reference host repo for infrastructure operations
- [ ] Optionally remove `static_folder="frontend"` from server.py (no longer needed with nginx routing)

### Collector Service
- [ ] Decide whether `helios-collector.service` unit file should also move to host repo
- [ ] Currently left in backend scope since it's tightly coupled to collector_main.py

---

*This document tracks the OrangePi host separation work. Update as phases complete.*
