#!/usr/bin/env bash
# Build FormulaHub-ETL-Mac.zip — Docker-first pack for Mac founders / design partners.
# Does NOT produce a signed .app (see apps/desktop + docs/studio/DESKTOP_SHELL.md).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT_DIR="${ROOT}/data/out/mac-pack"
STAGE="${OUT_DIR}/FormulaHub-ETL-Mac"
ZIP_PATH="${OUT_DIR}/FormulaHub-ETL-Mac.zip"

rm -rf "${STAGE}"
mkdir -p "${STAGE}"

# Core runtime / ops files (no bulky node_modules, .git, or runtime data dumps)
copy_tree() {
  local src="$1"
  local dest="$2"
  mkdir -p "$(dirname "${dest}")"
  if [[ -d "${src}" ]]; then
    mkdir -p "${dest}"
    # Prefer rsync when available for excludes
    if command -v rsync >/dev/null 2>&1; then
      rsync -a \
        --exclude 'node_modules' \
        --exclude '.git' \
        --exclude 'dist' \
        --exclude 'release' \
        --exclude '__pycache__' \
        --exclude '*.pyc' \
        --exclude '.pytest_cache' \
        --exclude '*.egg-info' \
        --exclude 'data/out' \
        --exclude 'data/*.db' \
        --exclude 'data/*.db-*' \
        "${src}/" "${dest}/"
    else
      cp -R "${src}" "$(dirname "${dest}")/"
    fi
  else
    cp "${src}" "${dest}"
  fi
}

for item in \
  README.md LICENSE Makefile docker-compose.yml requirements.txt pytest.ini \
  packages apps demos fixtures scripts docs .github
do
  if [[ -e "${ROOT}/${item}" ]]; then
    copy_tree "${ROOT}/${item}" "${STAGE}/${item}"
  fi
done

# Ensure data skeleton exists without dumping local DBs
mkdir -p "${STAGE}/data/s3/demo" "${STAGE}/data/out" "${STAGE}/data/archive"
# Prefer seeded fixtures note over copying large generated artifacts
if [[ -f "${ROOT}/data/s3/demo/.gitkeep" ]]; then
  cp "${ROOT}/data/s3/demo/.gitkeep" "${STAGE}/data/s3/demo/" 2>/dev/null || true
fi

cat > "${STAGE}/START_HERE_MAC.md" << 'EOF'
# FormulaHub ETL — Mac pack

Two ways to run Studio on your Mac.

## A) Desktop app (recommended feel)

Requires Node + Python (see repo README).

```bash
cd FormulaHub-ETL-Mac   # after unzip
make install && make seed && make build
make desktop            # opens native Studio window
```

Build a double-clickable **FormulaHub Studio.app** (unsigned):

```bash
cd apps/desktop && npm install && npm run dist:mac
open release/mac*/FormulaHub\ Studio.app
```

Full steps: `docs/studio/DESKTOP_SHELL.md` and `apps/desktop/README.md`.

## B) Docker (browser fallback)

```bash
cd FormulaHub-ETL-Mac
docker compose up --build
# Studio UI  http://127.0.0.1:18766
# API        http://127.0.0.1:18765
```

Status bar shows `workspace on this machine · {work_dir}` when the API is healthy.

## Notes

- Local `work_dir` is primary. Cloud auth is **not** in this pack.
- Linux CI does **not** produce signed Mac `.dmg` files — build `.app` on macOS.
EOF

# Strip accidental heavy dirs if cp -R path was used without rsync
find "${STAGE}" -type d -name node_modules -prune -exec rm -rf {} + 2>/dev/null || true
find "${STAGE}" -type d -name .git -prune -exec rm -rf {} + 2>/dev/null || true
find "${STAGE}" -path '*/apps/desktop/release' -prune -exec rm -rf {} + 2>/dev/null || true

rm -f "${ZIP_PATH}"
(
  cd "${OUT_DIR}"
  # Prefer zip; fall back to tar.gz named the same base
  if command -v zip >/dev/null 2>&1; then
    zip -r -q "FormulaHub-ETL-Mac.zip" "FormulaHub-ETL-Mac"
  else
    tar -czf "FormulaHub-ETL-Mac.tar.gz" "FormulaHub-ETL-Mac"
    echo "zip not found — wrote FormulaHub-ETL-Mac.tar.gz instead" >&2
    ZIP_PATH="${OUT_DIR}/FormulaHub-ETL-Mac.tar.gz"
  fi
)

echo "Wrote ${ZIP_PATH:-$OUT_DIR/FormulaHub-ETL-Mac.zip}"
ls -lh "${OUT_DIR}/FormulaHub-ETL-Mac.zip" 2>/dev/null || ls -lh "${OUT_DIR}/FormulaHub-ETL-Mac.tar.gz"
