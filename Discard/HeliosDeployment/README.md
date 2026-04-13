# Helios Deployment Documentation

> **Purpose:** Make working with and understanding First Helios possible — for the developer, for future agents, and for anyone inheriting this codebase.
>
> **Scope:** The complete backend platform. Frontend and host infrastructure live in separate repos.

---

## Document Map

| # | Document | What It Covers |
|---|----------|---------------|
| 1 | [Platform Overview](01_PLATFORM_OVERVIEW.md) | What First Helios is, the three-repo architecture, data domains, the mission |
| 2 | [Data Architecture](02_DATA_ARCHITECTURE.md) | 6-layer DB design, 48 tables, write paths, metadata system, data contracts |
| 3 | [SpiritPool Intake Pipeline](03_SPIRITPOOL_INTAKE_PIPELINE.md) | FH-0/FH-1 contributor pipeline: tables, endpoints, processing flow, burn mechanism |
| 4 | [Privacy & Governance](04_PRIVACY_AND_GOVERNANCE.md) | IP suppression, field stripping, PII quarantine, 18 non-negotiable rules |
| 5 | [Deployment Progress](05_DEPLOYMENT_PROGRESS.md) | What's built, what's next, tier checklists, success criteria |
| 6 | [Infrastructure & Operations](06_INFRASTRUCTURE.md) | OrangePi host, systemd services, scheduler, rate management, auto-deploy |

---

## How to Use This Documentation

**New to the project?** Start with [Platform Overview](01_PLATFORM_OVERVIEW.md). It explains all the pieces and how they connect.

**Working on SpiritPool integration?** Read [SpiritPool Intake Pipeline](03_SPIRITPOOL_INTAKE_PIPELINE.md) and [Privacy & Governance](04_PRIVACY_AND_GOVERNANCE.md) together.

**Adding a data source?** Start with [Data Architecture](02_DATA_ARCHITECTURE.md) for the layer model and write paths, then check the [PLAYBOOK](../../PLAYBOOK.md) for step-by-step instructions.

**Checking what's been done?** [Deployment Progress](05_DEPLOYMENT_PROGRESS.md) has tier-by-tier checklists.

**Debugging production?** [Infrastructure & Operations](06_INFRASTRUCTURE.md) covers services, logs, and troubleshooting.

---

## Related Documentation (Elsewhere in This Repo)

| Document | Location | Purpose |
|----------|----------|---------|
| RUNBOOK | [RUNBOOK.md](../../RUNBOOK.md) | Operations reference — services, commands, troubleshooting |
| PLAYBOOK | [PLAYBOOK.md](../../PLAYBOOK.md) | Developer guide — write paths, adding collectors, testing |
| Data Dictionary | [docs/data/dictionary/](../data/dictionary/) | Column-level schema reference for all tables |
| Data Streams | [docs/architecture/DATA_STREAMS.md](../architecture/DATA_STREAMS.md) | Every data source, collection method, and downstream consumer |
| Data Contracts | [docs/contracts/](../contracts/) | SLA and schema guarantees for dashboard-facing tables |
| Integration Roadmap | [docs/INTEGRATION_ROADMAP.md](../INTEGRATION_ROADMAP.md) | Task sequencing by context-window complexity |
| Handoff Docs | [agentMailbox/](../../agentMailbox/) | FH-0, FH-1, FH-2 spec documents + SpiritPool privacy contract |

---

## Cross-Repo Architecture

First Helios is split across three repositories:

| Repo | Scope | Link |
|------|-------|------|
| **First-Helios** (this repo) | Backend API, data pipeline, scoring, scheduler | `github.com/4Fortune8/First-Helios` |
| **First-Helios_Frontend** | Dashboard UI (HTML/CSS/JS) | `github.com/4Fortune8/First-Helios_Frontend` |
| **First-Helios_Orangepi_Host** | Host infrastructure (systemd, nginx, deploy scripts) | `github.com/4Fortune8/First-Helios_Orangepi_Host` |

The SpiritPool browser extension lives in a fourth repo (`ChainStaffingTracker/spiritpool/`) and communicates with this backend via `POST /api/contribute`.
