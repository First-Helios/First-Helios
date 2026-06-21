.PHONY: install lint typecheck test ci clean

install:
	uv sync
	uv run pre-commit install --install-hooks --hook-type pre-commit --hook-type commit-msg

lint:
	uv run pre-commit run --all-files

typecheck:
	uv run mypy .

test:
	uv run pytest --cov=packages --cov=apps --cov-report=term-missing

# Run everything CI runs, in order
ci: lint typecheck test
	uv lock --check

clean:
	rm -rf .venv .ruff_cache .mypy_cache .pytest_cache htmlcov
