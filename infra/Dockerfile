# syntax=docker/dockerfile:1
#
# Single image, multiple entrypoints: the API runs the default CMD, future
# scraper workers (Phase 4+) override it. Build context is the repo root:
#   docker build -f infra/Dockerfile -t helios-api .

FROM python:3.12-slim-bookworm AS builder

# Pinned to match the uv version used locally and in CI.
COPY --from=ghcr.io/astral-sh/uv:0.12.0 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependencies first, as their own cached layer: this only re-runs when
# uv.lock or pyproject.toml change, not on every source edit.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-dev

COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev


FROM python:3.12-slim-bookworm AS runtime

# Run as a non-root user. psycopg[binary] bundles libpq, so no apt packages
# are needed at runtime.
RUN groupadd --system helios \
    && useradd --system --gid helios --create-home helios

WORKDIR /app
COPY --from=builder --chown=helios:helios /app /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER helios
EXPOSE 8000

# Migrations are deliberately NOT run here. Running `alembic upgrade head` on
# container start races when more than one replica boots at once; it's a
# separate one-shot step (see the `migrate` service in docker-compose.yml).
CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
