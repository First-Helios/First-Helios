# S6 Pi rebuild execution record

**Rebuild complete. Pi URL-resolution gate closed: precision review found supported errors and unresolved cases.**

The owner explicitly instructed the agent to perform the rebuild after #42
merged. Execution began 2026-09-28 and used merged commit
`3faae15e1cd452bcc00abfcd53b951ba3f46ae89`; PR and merged-main CI passed.
No runtime code or deployment configuration was changed during this operation.

## Deployment and recovery

- Host: `orangepi5plus` (`orangepi@192.168.1.219`, ARM64).
- Active source snapshot: `/home/orangepi/First-Helios`; `DEPLOYED_COMMIT`
  records the deployed SHA. This directory is not a Git checkout.
- The exact commit was transferred with `git archive`; archive SHA-256:
  `e1517ddcb4d2cde45e9cec953ac81836fe751fd6bb0f2906cf9ebe48cec8d833`.
- Backup directory: `/home/orangepi/helios-backups/s6-20260928-3faae15`.
  `pre-s6.dump` is a custom-format PostgreSQL dump; `pg_restore --list`
  successfully read its 520-line catalog. Dump SHA-256:
  `09a7eaa474eb96194964a915ae2c7818b51046ac0738d974c81148ebb1a1500f`.
  A full restore rehearsal was not performed.
- `checkout/` preserves the previous source snapshot and environment file.
  The existing `var/` cache directory was moved into the new deployment.
- The old `infra` Compose stack was stopped. Its `infra_postgres_data`
  volume is retained offline. No volume was deleted. The new `helios` stack
  uses a fresh `helios_postgres_data` volume.
- The stopped `helios-resolve` container has restart policy `no`.
  No active discovery/URL-resolution scheduler was found.
- PostgreSQL and the API are healthy. The migration container exited 0 at
  `c91a6f02de73`. `alembic check` reported no new operations;
  `/healthz` and `/readyz` returned `{"status":"ok"}`.
  `/v1/venues?limit=1` returned a valid paginated response.
- API remains bound to the configured loopback address, `127.0.0.1:8000`.

Do not attach the old volume to the new image or run the two database stacks
on the same port. Recovery materials preserve the old deployment; they do not
make legacy Bronze data compatible with the S6 migration.

## Discovery and provenance acceptance

Re-ingested the same release used by the previous Phase 4 audit:
`s3://overturemaps-us-west-2/release/2026-08-19.0/theme=places/type=place/*.parquet`,
using the default full Travis/Williamson bbox and category policy. The ordinary
CLI completed with exit 0; no coordinate gap-filling was needed.

```text
fetched=10014 minted=9996 deduped=18 reused=0 ambiguous=0
needs_review=0 geocoded=0 skipped=0
```

| Check | Result |
|---|---:|
| Current venues | 9,996 |
| Source Records / Versions | 10,014 / 10,014 |
| Successful Captures | 10,014 |
| Versions with Capture, Endpoint, and Evidence | 10,014 each |
| Opt-in Identity match endpoints | 0 |
| Published website coverage | 8,217 / 10,014 (82.1%) |

The shared acquisition endpoint is the canonical S3 release prefix, without
the filename glob. It is not used as an Identity match key. Counts and the
provenance check are saved in `discovery.log` and `provenance-check.txt` in the
backup directory.

## Fresh precision audit

The audit CLI completed with exit 0 against the new export and deterministic
100-row sample (rebuilt Subject IDs), with a fresh Nominatim cache:

| Automated check | Result |
|---|---:|
| Duplicate candidates across the full corpus | 43 |
| Candidate fraction, counting every pair as a duplicate | 0.430% |
| Missing/out-of-bbox coordinate flags | 0 |
| Sample geocodes corroborated within 150 m | 55 / 100 |
| Nominatim match farther than 150 m | 17 / 100 |
| Address unresolved by Nominatim | 28 / 100 |

These are detector results, not confirmed precision labels. In particular,
the 45 geocode flags do not establish either a passing rate or a 45% error
rate. Unresolved addresses may be geocoder recall failures; distant matches
require checking both points. With a strict `< 1%` criterion on a 100-row
sample, one confirmed wrong geocode would be 1%, which does not pass.

Artifacts are in `var/audits/s6-20260928/` in both the Pi deployment and the
local workspace: `venues.json`, raw `worksheet.json`, and the fresh `geocode/`
cache. The local packet additionally includes `sample.json`, `review.md`
(with map links), `review.json`, `audit.log`, `provenance-check.txt`, and
`SHA256SUMS`. Copies of the sample/review/checksum files are also in the Pi
backup directory.

The raw CLI worksheet pre-populates labels with detector suggestions. The
original **`review.json` clears those labels and records `review_status:
"pending"`**, so they cannot be mistaken for completed review. It remains
unchanged for reproducibility. The [subsequent precision review](2026-09-28-precision-review.md)
assesses all 88 entries in a separate worksheet: 23 supported duplicate pairs,
4 distinct, 16 unresolved; 20 corroborated geocodes, 3 supported wrong,
22 unresolved. Owner confirmation remains pending. Three confirmed wrong
geocodes would yield at least 3% in the 100-row sample and fail the gate.
No labels were carried over from the previous audit. URL resolution remains stopped.

S6b is not Pi-gating. Phase 5 remains closed until S13 and its lifecycle
acceptance tests pass.
