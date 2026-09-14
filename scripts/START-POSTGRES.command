#!/bin/bash
# START-POSTGRES.command — FormulaHub-ETL Mac LOCAL Postgres helper
#
# Founder pack: place/double-click as FormulaHub-ETL-Mac/START-POSTGRES.command
# Repo:          bash scripts/START-POSTGRES.command
#
# Classification: LOCAL only (Homebrew Postgres). Never LIVE_EXTERNAL.
set -euo pipefail

export LC_ALL="${LC_ALL:-en_US.UTF-8}"
export LANG="${LANG:-en_US.UTF-8}"

# When double-clicked from the Mac pack, repo lives under FormulaHub-ETL/
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [[ -d "${SCRIPT_DIR}/FormulaHub-ETL" ]]; then
  ROOT="${SCRIPT_DIR}/FormulaHub-ETL"
elif [[ -d "${SCRIPT_DIR}/../fixtures/sql" ]]; then
  ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
elif [[ -d "${SCRIPT_DIR}/fixtures/sql" ]]; then
  ROOT="${SCRIPT_DIR}"
else
  ROOT="${SCRIPT_DIR}"
fi
cd "${ROOT}"

echo "FormulaHub LOCAL Postgres"
echo "  LC_ALL=${LC_ALL}"
echo "  repo=${ROOT}"
echo ""

if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew not found. Install from https://brew.sh then re-run." >&2
  exit 1
fi

if ! brew list postgresql@16 >/dev/null 2>&1; then
  echo "Installing postgresql@16…"
  brew install postgresql@16
fi

# Ensure brew postgres binaries are on PATH for this shell
export PATH="$(brew --prefix postgresql@16)/bin:${PATH}"

echo "Starting postgresql@16 (LC_ALL=${LC_ALL})…"
brew services start postgresql@16 || true

# Wait for readiness
for i in $(seq 1 40); do
  if pg_isready -h localhost -p 5432 >/dev/null 2>&1 || pg_isready >/dev/null 2>&1; then
    break
  fi
  sleep 0.5
done

if ! pg_isready -h localhost -p 5432 >/dev/null 2>&1 && ! pg_isready >/dev/null 2>&1; then
  echo "Postgres did not become ready. If postmaster failed on locale, ensure:" >&2
  echo "  export LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8" >&2
  echo "then: brew services restart postgresql@16" >&2
  exit 1
fi

# Create DB (trust / local socket — no password)
if command -v createdb >/dev/null 2>&1; then
  createdb formulahub_wedge 2>/dev/null || true
fi
# Fallback via psql if createdb missing/permission quirks
psql -h localhost -d postgres -v ON_ERROR_STOP=0 -c "CREATE DATABASE formulahub_wedge;" 2>/dev/null || true

SQL_FILE="${ROOT}/fixtures/sql/formulahub_wedge.sql"
if [[ -f "${SQL_FILE}" ]]; then
  echo "Applying ${SQL_FILE}…"
  psql -h localhost -d formulahub_wedge -v ON_ERROR_STOP=1 -f "${SQL_FILE}"
else
  echo "DDL missing at ${SQL_FILE} — creating customers_wedge inline…"
  psql -h localhost -d formulahub_wedge -v ON_ERROR_STOP=1 <<'SQL'
CREATE TABLE IF NOT EXISTS customers_wedge (
    customer_id text NOT NULL,
    email text,
    signup_date text,
    loaded_at text,
    PRIMARY KEY (customer_id)
);
SQL
fi

echo ""
echo "Ready — LOCAL Postgres (not LIVE_EXTERNAL)"
echo "  database: formulahub_wedge"
echo "  table:    customers_wedge (customer_id, email, signup_date, loaded_at)"
echo ""
echo "Run LOCAL_PROVEN wedge:"
echo "  export FORMULAETL_DEMO=0"
echo "  export LOCAL_POSTGRES_DSN=\"host=localhost port=5432 dbname=formulahub_wedge\""
echo "  export LOCAL_POSTGRES_TABLE=customers_wedge"
echo "  python3 scripts/customer001_local_wedge.py --mode postgres"
echo ""
