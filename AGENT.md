# AGENT.md — First-Helios Development & Deployment Workflow

This file is the **canonical workflow contract** for any agent (human or AI)
making changes to the First-Helios ecosystem. It captures the loop that keeps
local development, GitHub, and the Orange Pi production host in sync, with
explicit verification gates. If you are about to deploy, test, or backfill
anything, read this first.

---

## The Three Repos

| Repo | Location | Role |
|---|---|---|
| First-Helios | `/home/fortune/CodeProjects/First-Helios` (origin: `git@github.com:4Fortune8/First-Helios.git`) | Flask API, collectors, scheduler, DB schema |
| SpiritPool | `/home/fortune/CodeProjects/SpiritPool` (origin: `https://github.com/4Fortune8/ChainStaffingTracker`) | Browser extension; installs locally, never runs on the Pi |
| Spiritpool_User | `/home/fortune/CodeProjects/Spiritpool_User` (origin: `https://github.com/4Fortune8/Spiritpool_User.git`) | **Local-only** test harness — isolated Firefox profile + Selenium runner |

Production host: `orangepi@192.168.1.191` (Ubuntu Jammy, ARM64). Deployment is
git-pull-based via the `helios-update.timer` systemd unit (polls every 5 min).

---

## The Canonical Loop

Every substantive change follows these gates, in order. Never skip a gate just
because "it's a small change" — the gates exist because skipping them is how
prod stalemates happen.

### Gate 1 — Develop in the current workspace (local)

- Work only inside the repo the change belongs to. Never edit a sibling repo
  as a shortcut; commits there still need to be committed and pushed.
- For Python code, always activate the project venv before running anything:
  `source .venv/bin/activate`.
- For extension work, never run the extension from `/tmp` or an ad-hoc copy.
  Use the tracked source tree and the launcher under `Spiritpool_User/`.

### Gate 2 — Successfully develop AND test locally

- New or changed code must be runnable locally before it is pushed. That
  usually means: `pytest -x` for Python, `npm test` or `web-ext lint` for JS.
- Security-critical paths (anything that accepts HTML, signatures, tokens, or
  raw URLs from clients) need a passing test in `tests/HeliosDeployment/`
  before they leave the workstation.
- "Successfully" means exit code 0 and expected output inspected. A test
  that imports but doesn't assert the thing you changed is not a test.

### Gate 3 — Push to GitHub

- Commit with a message that names the subsystem and the observable effect.
  Example: `spiritpool-dev-capture: add HMAC verifier + kill switch`.
- Push to `origin/main`. Feature branches are fine for work that isn't ready,
  but production will never pull them.

### Gate 4 — Pull to Orange Pi

- The `helios-update.timer` systemd unit runs `dev/update.sh` every 5 minutes.
  That script fetches, pulls, reinstalls dependencies, and restarts services
  **only if the commit hash actually changed**.
- To deploy immediately:
  ```bash
  ssh orangepi@192.168.1.191 "cd ~/First-Helios && git pull && \
      sudo systemctl restart helios helios-collector"
  ```
- **Always verify the commit hash on the Pi matches the hash you pushed.**
  A "git pull" that claims "Already up to date" while the Pi is on an older
  commit usually means the timer ran mid-push.

### Gate 5 — SSH all needed commands

When the Pi needs configuration that isn't checked into git (env vars, one-off
migrations, systemd drop-ins, dev-key issuance), do it **via SSH from the
workstation, documented in RUNBOOK.md or the feature's session note**.

Useful one-liners:
```bash
# Confirm commit + service status
ssh orangepi@192.168.1.191 "cd ~/First-Helios && git log -1 --oneline && \
    systemctl is-active helios helios-collector"

# View recent server logs
ssh orangepi@192.168.1.191 "journalctl -u helios -n 100 --no-pager"

# Restart after env-var / config change
ssh orangepi@192.168.1.191 "sudo systemctl restart helios helios-collector"
```

### Gate 6 — Validate working status

Every deployment ends with an **API or file-system check from the
workstation**, not just from the Pi itself. "Works on the Pi" and "works for
a remote caller" are different guarantees.

```bash
# Example: confirm the route is live
curl -sS -o /dev/null -w "%{http_code}\n" \
    http://192.168.1.191/api/ref/summary?region=austin_tx
```

If the feature touches the DB, also verify with a read query:

```bash
ssh orangepi@192.168.1.191 'PGPASSWORD=helios psql -U helios -h localhost \
    -d helios -c "SELECT COUNT(*) FROM job_postings WHERE source LIKE '\''spiritpool_%'\'';"'
```

### Gate 7 — Pull current DB / data from Orange Pi to local workstation

After a deploy that changes what the Pi collects, pull the fresh data back
so local analysis/exploration reflects production state.

```bash
# Schema + data dump (full)
ssh orangepi@192.168.1.191 "PGPASSWORD=helios pg_dump -U helios -h localhost \
    -d helios" | PGPASSWORD=helios psql -U helios -h localhost -d helios

# Or incremental: pull artifact directories (e.g., Spirit Pool dev captures)
rsync -avz orangepi@192.168.1.191:~/First-Helios/data/cache/spiritpool_dev/page_captures/ \
    /home/fortune/CodeProjects/First-Helios/data/cache/spiritpool_dev/page_captures/
```

The pull step may need updates as the data surface grows — document new
directories here when you add them.

---

## Spirit Pool Dev-Capture Loop (`/api/spiritpool/dev/*`)

This is the current highest-leverage example of the full loop:

1. **Local develop** in `SpiritPool/spiritpool/` and `First-Helios/postings/spiritpool_dev_capture.py`.
2. **Test locally** with `tests/HeliosDeployment/test_spiritpool_dev_capture.py` (20 cases: kill switch, HMAC, replay, tamper, SSRF, overwrite).
3. **Push** both repos to GitHub.
4. **Pull** on Orange Pi (`helios-update.timer` handles First-Helios; SpiritPool is local-only, no Pi pull).
5. **SSH config** — enable the feature on the Pi by setting the env var in a systemd drop-in:
   ```bash
   ssh orangepi@192.168.1.191 "sudo install -d /etc/systemd/system/helios.service.d && \
       sudo tee /etc/systemd/system/helios.service.d/dev-capture.conf > /dev/null" <<'EOF'
   [Service]
   Environment=SPIRITPOOL_DEV_SIGNING_KEY=1
   EOF
   ssh orangepi@192.168.1.191 "sudo systemctl daemon-reload && sudo systemctl restart helios"
   ```
   Then issue a device key **on the Pi** (key file must live on the host that verifies signatures):
   ```bash
   ssh orangepi@192.168.1.191 "cd ~/First-Helios && source .venv/bin/activate && \
       SPIRITPOOL_DEV_SIGNING_KEY=1 python scripts/issue_spiritpool_dev_key.py \
       --note 'fortune local-firefox'"
   ```
6. **Validate** with a signed curl smoke from the workstation (does not require the browser extension).
7. **User-side local test** — drive the real extension from `Spiritpool_User/` via Selenium + Firefox. Always local; never on the Pi.
8. **Pull captures back** with `rsync` (see Gate 7).

---

## When Things Go Wrong

| Symptom | Likely cause | First check |
|---|---|---|
| `curl /api/...` returns 404 but local passes | Pi not on the same commit | `ssh ... git log -1` |
| Route returns 500 with "no such table" | Migration not run on Pi | `ssh ... alembic current` |
| Dev-capture returns 404 in prod | Env var not set | `ssh ... systemctl show helios -p Environment` |
| Extension POSTs succeed but file missing | Signature rejected; look for 401 reason | Pi `journalctl -u helios \| grep SPDevCapture` |
| "Already up to date" but Pi behind | update timer raced mid-push | `ssh ... && git pull` manually |

---

## Non-Negotiables

- **Never** commit `.env`, `data/cache/spiritpool_dev/keys.json`, or any dev
  secret. The `.gitignore` already excludes these — don't add `-f`.
- **Never** enable `SPIRITPOOL_DEV_SIGNING_KEY` in a public-internet environment
  without first reviewing the threat model in `postings/spiritpool_dev_capture.py`.
- **Never** run the Spiritpool_User launcher on the Pi. The test harness is
  local by definition; running it remotely defeats the point of a real
  user-browser session.
- **Never** skip Gate 6. A push that lands on the Pi but doesn't respond to a
  workstation curl is not deployed.

---

*This file supersedes any conflicting workflow advice in older docs. If you
find a conflict, update this file first, then reconcile the older doc.*
