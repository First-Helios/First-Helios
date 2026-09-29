# syntax=docker/dockerfile:1
#
# Two targets. The default (last) stage `runtime` is the API image; discovery
# CLIs that need no extras can run in it too. `worker` adds the `menu` extra
# (the page classifier runtime, ADR-0013) for the discovery and menu-pipeline
# CLIs. Build context is the repo root:
#   docker build -f infra/Dockerfile -t helios-api .
#   docker build -f infra/Dockerfile --target worker -t helios-worker .

# Pinned by digest for reproducible builds; tag kept in the comment (R90).
FROM python:3.12-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e AS builder

# Keep in step with setup-uv's `version:` in .github/workflows/ci.yml.
COPY --from=ghcr.io/astral-sh/uv:0.12.0@sha256:606e70c71c852d03f611b1e56a195d08648507018a7057fab82c4974c4eae105 /uv /usr/local/bin/uv

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


# The worker's environment: the same sync plus the `menu` extra.
FROM builder AS builder-menu
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra menu


FROM python:3.12-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e AS base

# Run as a non-root user. psycopg[binary] bundles libpq, and onnxruntime's
# wheel bundles its own libraries, so no apt packages are needed at runtime.
RUN groupadd --system --gid 999 helios \
    && useradd --system --uid 999 --gid 999 --create-home helios

WORKDIR /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1


# Model files are never baked in: they live in var/models/ (a volume) and are
# checked against config/models.yaml before use (ADR-0013 §3).
FROM base AS worker
COPY --from=builder-menu --chown=helios:helios /app /app
USER helios
CMD ["python", "-m", "apps.menu_pipeline.models", "verify"]


FROM base AS runtime
COPY --from=builder --chown=helios:helios /app /app

USER helios
EXPOSE 8000

# Migrations are deliberately NOT run here. Running `alembic upgrade head` on
# container start races when more than one replica boots at once; it's a
# separate one-shot step (see the `migrate` service in docker-compose.yml).
CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
