COMPOSE := docker compose -f infra/docker-compose.yml

.PHONY: install lint typecheck test lockcheck ci clean build dev dev-down dev-logs migrate

install:
	uv sync
	uv run pre-commit install --install-hooks --hook-type pre-commit --hook-type commit-msg

lint:
	uv run pre-commit run --all-files

typecheck:
	uv run mypy .

test:
	uv run pytest --cov=. --cov-report=term-missing

# Lockfile first: the `uv run` steps below silently re-lock a stale lockfile,
# so checking afterwards could never fail.
lockcheck:
	uv lock --check

# Local subset of CI (CI also builds/smoke-tests Docker, runs DB tests in strict
# mode with a coverage floor, and runs `alembic check`). For database
# acceptance see the disposable-DB command in CONTRIBUTING.md.
ci: lockcheck lint typecheck test

# --- Docker ---------------------------------------------------------------

# Build the app image on its own (CI does the same thing).
build:
	docker build -f infra/Dockerfile -t helios-api:local .

# Bring up the full stack: postgres -> migrate (one-shot) -> api.
# API lands on http://127.0.0.1:8000
dev:
	$(COMPOSE) up -d --build

dev-down:
	$(COMPOSE) down

dev-logs:
	$(COMPOSE) logs -f

# Apply migrations against the running stack. Deliberately a separate step
# rather than something the api container does on boot.
migrate:
	$(COMPOSE) run --rm migrate

clean:
	rm -rf .venv .ruff_cache .mypy_cache .pytest_cache htmlcov
