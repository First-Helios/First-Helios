COMPOSE := docker compose -f infra/docker-compose.yml

.PHONY: install lint typecheck test ci clean build dev dev-down dev-logs migrate

install:
	uv sync
	uv run pre-commit install --install-hooks --hook-type pre-commit --hook-type commit-msg

lint:
	uv run pre-commit run --all-files

typecheck:
	uv run mypy .

test:
	uv run pytest --cov=. --cov-report=term-missing

# Run everything CI runs, in order
ci: lint typecheck test
	uv lock --check

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
