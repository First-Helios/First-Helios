#!/bin/bash
# Orange Pi 5 Plus — First-Helios Setup Script
# Ubuntu Jammy (22.04), RK3588 ARM64
# Run this on the Orange Pi after cloning the repo.

set -e

echo "=== First-Helios: Orange Pi 5 Plus Setup ==="
echo "Target: Ubuntu Jammy / ARM64 (RK3588)"
echo ""

# ── 1. System packages ──────────────────────────────────────────────────────
echo "[1/6] Installing system dependencies..."
sudo apt-get update
sudo apt-get install -y \
    software-properties-common \
    build-essential \
    cmake \
    git \
    curl \
    libpq-dev \
    libicu-dev \
    libssl-dev \
    libffi-dev \
    libbz2-dev \
    libreadline-dev \
    libsqlite3-dev \
    libgeos-dev \
    zlib1g-dev \
    pkg-config \
    postgresql \
    postgresql-contrib

# ── 2. Python 3.12 (deadsnakes PPA — Jammy ships 3.10) ──────────────────────
echo "[2/6] Installing Python 3.12..."
sudo add-apt-repository -y ppa:deadsnakes/ppa
sudo apt-get update
sudo apt-get install -y python3.12 python3.12-venv python3.12-dev python3.12-distutils

# Verify
python3.12 --version

# ── 3. PostgreSQL — create DB and user ─────────────────────────────────────
echo "[3/6] Configuring PostgreSQL..."
sudo systemctl enable postgresql
sudo systemctl start postgresql

sudo -u postgres psql -c "CREATE USER helios WITH PASSWORD 'helios';" 2>/dev/null || echo "  (user already exists)"
sudo -u postgres psql -c "CREATE DATABASE helios OWNER helios;" 2>/dev/null || echo "  (database already exists)"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE helios TO helios;" 2>/dev/null || true

# ── 4. Python virtual environment ──────────────────────────────────────────
echo "[4/6] Creating Python virtual environment..."
cd "$(dirname "$0")/.."   # project root

python3.12 -m venv .venv
source .venv/bin/activate

pip install --upgrade pip wheel setuptools

# ── 5. Install Python packages ─────────────────────────────────────────────
echo "[5/6] Installing Python dependencies..."
echo "    NOTE: tls-client and playwright may fail on ARM64 — see notes below."

# Install everything except known ARM64 problem packages first
pip install -r requirements.txt \
    --extra-index-url https://pypi.org/simple/ \
    || true

# tls-client: ships x86-only prebuilt .so — try anyway, soft-fail
pip install tls-client 2>/dev/null || echo "  WARN: tls-client failed (expected on ARM64, check if it's actually used)"

# playwright: ARM64 browser binaries are limited
# Install the Python package but skip browser download unless needed
pip install playwright 2>/dev/null && \
    python -m playwright install chromium 2>/dev/null || \
    echo "  WARN: playwright browser install failed — only affects JS-rendering scrapers"

echo ""
echo "[5/6] Done. Checking for import errors on core modules..."
python -c "import flask, sqlalchemy, psycopg, pandas, numpy, shapely, h3" && \
    echo "  Core imports OK" || \
    echo "  WARN: some core imports failed — check above output"

# ── 6. .env file ───────────────────────────────────────────────────────────
echo "[6/6] Environment config..."
if [ ! -f .env ]; then
    cp .env.example .env 2>/dev/null || cat > .env <<'EOF'
DATABASE_URL=postgresql+psycopg://helios:helios@localhost:5432/helios
FLASK_ENV=development
FLASK_DEBUG=1
EOF
    echo "  Created .env — add your API keys."
else
    echo "  .env already exists — verify DATABASE_URL is set correctly."
fi

echo ""
echo "=== Setup complete ==="
echo ""
echo "Next steps:"
echo "  1. Restore database:  psql -U helios -d helios < helios_backup.sql"
echo "  2. Activate venv:     source .venv/bin/activate"
echo "  3. Start server:      python server.py"
echo ""
echo "Known ARM64 limitations:"
echo "  - tls-client: cloudscraper fallback will be used if tls-client is missing"
echo "  - playwright: only affects JS-heavy scrapers (Playwright-based collectors)"
echo "  - All other packages should work natively on ARM64"
