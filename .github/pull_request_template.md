## Summary

What does this PR do, and why?

## Related

Closes #
ADR/RFC (if applicable):

## Changes

-

## Verification

- [ ] `make ci` passes locally (lint, typecheck, test, lockfile check)
- [ ] Database code, models or migrations changed: `HELIOS_STRICT_DB_TESTS=1 DATABASE_URL=... make ci`
  and `DATABASE_URL=... uv run alembic check` pass against a disposable PostgreSQL `*_test`
  database, never application data (CI runs both)
- [ ] New/changed behavior has test coverage
- [ ] Migrations reviewed by hand, not just accepted from autogenerate (if applicable)

## Notes for reviewer

Anything non-obvious, deliberately deferred, or worth a second look.
