#!/usr/bin/env bash
# Build FormulaHub-ETL-Mac.zip for founder / design-partner handoff.
#
# Top-level after unzip:
#   FormulaHub Studio.app     ← double-click (primary)
#   START-NATIVE.command      ← Terminal fallback
#   README_MAC.md             ← short: unzip → double-click app
#   FormulaHub-ETL/           ← repo sources (Docker / make install)
#
# On macOS, if deps are ready, also embeds electron-builder FormulaHub Studio.app
# (unsigned). Linux agents still emit a clickable .app launcher + icon.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT_DIR="${ROOT}/data/out/mac-pack"
STAGE="${OUT_DIR}/FormulaHub-ETL-Mac"
REPO_STAGE="${STAGE}/FormulaHub-ETL"
ZIP_PATH="${OUT_DIR}/FormulaHub-ETL-Mac.zip"
APP_NAME="FormulaHub Studio.app"
ICON_SRC="${ROOT}/apps/desktop/build/icon.png"

rm -rf "${STAGE}"
mkdir -p "${REPO_STAGE}"

copy_tree() {
  local src="$1"
  local dest="$2"
  mkdir -p "$(dirname "${dest}")"
  if [[ -d "${src}" ]]; then
    mkdir -p "${dest}"
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
    copy_tree "${ROOT}/${item}" "${REPO_STAGE}/${item}"
  fi
done

mkdir -p "${REPO_STAGE}/data/s3/demo" "${REPO_STAGE}/data/out" "${REPO_STAGE}/data/archive"
if [[ -f "${ROOT}/data/s3/demo/.gitkeep" ]]; then
  cp "${ROOT}/data/s3/demo/.gitkeep" "${REPO_STAGE}/data/s3/demo/" 2>/dev/null || true
fi

# ---------------------------------------------------------------------------
# FormulaHub Studio.app — clickable icon (no Terminal window required)
# ---------------------------------------------------------------------------
APP_DIR="${STAGE}/${APP_NAME}"
MACOS_DIR="${APP_DIR}/Contents/MacOS"
RES_DIR="${APP_DIR}/Contents/Resources"
mkdir -p "${MACOS_DIR}" "${RES_DIR}"

if [[ -f "${ICON_SRC}" ]]; then
  cp "${ICON_SRC}" "${RES_DIR}/icon.png"
fi
ICNS_SRC="${ROOT}/apps/desktop/build/icon.icns"
if [[ -f "${ICNS_SRC}" ]]; then
  cp "${ICNS_SRC}" "${RES_DIR}/AppIcon.icns"
elif [[ -f "${ICON_SRC}" ]]; then
  # Fallback: Finder prefers .icns; PNG kept as secondary resource
  cp "${ICON_SRC}" "${RES_DIR}/AppIcon.png"
fi

cat > "${APP_DIR}/Contents/Info.plist" << 'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleDevelopmentRegion</key>
  <string>en</string>
  <key>CFBundleDisplayName</key>
  <string>FormulaHub Studio</string>
  <key>CFBundleExecutable</key>
  <string>FormulaHub Studio</string>
  <key>CFBundleIconFile</key>
  <string>AppIcon</string>
  <key>CFBundleIdentifier</key>
  <string>io.formulahub.etl.studio.launcher</string>
  <key>CFBundleInfoDictionaryVersion</key>
  <string>6.0</string>
  <key>CFBundleName</key>
  <string>FormulaHub Studio</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>0.1.0</string>
  <key>CFBundleVersion</key>
  <string>0.1.0</string>
  <key>LSMinimumSystemVersion</key>
  <string>12.0</string>
  <key>NSHighResolutionCapable</key>
  <true/>
  <key>NSPrincipalClass</key>
  <string>NSApplication</string>
</dict>
</plist>
PLIST

# Executable launcher — stays alive while Electron/API children run; no Terminal.
cat > "${MACOS_DIR}/FormulaHub Studio" << 'LAUNCH'
#!/bin/bash
set -euo pipefail

# Resolve pack root: .../FormulaHub-ETL-Mac/FormulaHub Studio.app/Contents/MacOS → pack
HERE="$(cd "$(dirname "$0")" && pwd)"
APP_CONTENTS="$(cd "${HERE}/.." && pwd)"
APP_BUNDLE="$(cd "${APP_CONTENTS}/.." && pwd)"
PACK_ROOT="$(cd "${APP_BUNDLE}/.." && pwd)"
REPO="${PACK_ROOT}/FormulaHub-ETL"
LOG_DIR="${PACK_ROOT}/.studio-logs"
mkdir -p "${LOG_DIR}"
LOG="${LOG_DIR}/studio.log"

notify() {
  local msg="$1"
  if command -v osascript >/dev/null 2>&1; then
    osascript -e "display notification \"${msg}\" with title \"FormulaHub Studio\"" 2>/dev/null || true
  fi
}

alert() {
  local msg="$1"
  if command -v osascript >/dev/null 2>&1; then
    osascript -e "display alert \"FormulaHub Studio\" message \"${msg}\"" 2>/dev/null || true
  else
    echo "${msg}" >&2
  fi
}

if [[ ! -d "${REPO}" ]]; then
  alert "FormulaHub-ETL folder missing next to this app. Re-unzip the Mac pack."
  exit 1
fi

export FORMULAETL_WORK_DIR="${FORMULAETL_WORK_DIR:-${REPO}}"
export FORMULAETL_DEMO="${FORMULAETL_DEMO:-1}"
export FORMULAETL_EMBEDDED_WORKER="${FORMULAETL_EMBEDDED_WORKER:-1}"
cd "${REPO}"

# Prefer a real Electron .app produced by npm run dist:mac (embedded beside launcher).
EMBEDDED_ELECTRON=""
for cand in \
  "${PACK_ROOT}/ElectronStudio/FormulaHub Studio.app" \
  "${REPO}/apps/desktop/release/mac/FormulaHub Studio.app" \
  "${REPO}/apps/desktop/release/mac-arm64/FormulaHub Studio.app" \
  "${REPO}/apps/desktop/release/mac-x64/FormulaHub Studio.app"
do
  if [[ -d "${cand}" ]]; then
    EMBEDDED_ELECTRON="${cand}"
    break
  fi
done

if [[ -n "${EMBEDDED_ELECTRON}" ]]; then
  notify "Opening FormulaHub Studio…"
  open "${EMBEDDED_ELECTRON}"
  exit 0
fi

ELECTRON_BIN="${REPO}/apps/desktop/node_modules/.bin/electron"
WEB_DIST="${REPO}/apps/web/dist/index.html"

need_setup=0
command -v python3 >/dev/null 2>&1 || need_setup=1
command -v node >/dev/null 2>&1 || need_setup=1
[[ -x "${ELECTRON_BIN}" || -f "${ELECTRON_BIN}" ]] || need_setup=1
[[ -f "${WEB_DIST}" ]] || need_setup=1

if [[ "${need_setup}" -eq 1 ]]; then
  alert "First-time setup needed (once).

1. Open Terminal
2. cd \"${REPO}\"
3. make install && make seed && make build
4. Double-click FormulaHub Studio.app again

Fallback: double-click START-NATIVE.command"
  exit 1
fi

notify "Starting FormulaHub Studio…"
{
  echo "==== $(date -u +%Y-%m-%dT%H:%M:%SZ) launch ===="
  echo "work_dir=${FORMULAETL_WORK_DIR}"
  cd "${REPO}/apps/desktop"
  # Electron owns API lifecycle; keep this launcher process until Electron exits
  # so macOS does not treat the app as instantly quitting.
  exec ./node_modules/.bin/electron . >>"${LOG}" 2>&1
} >>"${LOG}" 2>&1
LAUNCH
chmod +x "${MACOS_DIR}/FormulaHub Studio"

# PkgInfo helps Finder treat it as an application
echo -n 'APPL????' > "${APP_DIR}/Contents/PkgInfo"

# ---------------------------------------------------------------------------
# START-NATIVE.command — Terminal fallback (ports can drop if Terminal closes)
# ---------------------------------------------------------------------------
cat > "${STAGE}/START-NATIVE.command" << 'CMD'
#!/bin/bash
# Fallback launcher — keeps a Terminal window open.
# Prefer FormulaHub Studio.app (survives better; no Terminal required).
set -euo pipefail
cd "$(dirname "$0")/FormulaHub-ETL"
export FORMULAETL_WORK_DIR="${FORMULAETL_WORK_DIR:-$(pwd)}"
export FORMULAETL_DEMO="${FORMULAETL_DEMO:-1}"
export FORMULAETL_EMBEDDED_WORKER="${FORMULAETL_EMBEDDED_WORKER:-1}"

echo "FormulaHub ETL — native fallback (Terminal)"
echo "Prefer: double-click FormulaHub Studio.app instead."
echo ""

if [[ ! -d apps/web/dist ]]; then
  echo "Building Studio UI…"
  make build
fi

# Start API in background (survives slightly better than foreground-only)
if ! curl -sf "http://127.0.0.1:18765/health" >/dev/null 2>&1; then
  echo "Starting API on :18765…"
  nohup python3 -m uvicorn formulaetl_api.main:app \
    --host 127.0.0.1 --port 18765 \
    --app-dir packages/api \
    >"${TMPDIR:-/tmp}/formulahub-api.log" 2>&1 &
  echo $! >"${TMPDIR:-/tmp}/formulahub-api.pid"
  for i in $(seq 1 40); do
    curl -sf "http://127.0.0.1:18765/health" >/dev/null 2>&1 && break
    sleep 0.5
  done
fi

if [[ -x apps/desktop/node_modules/.bin/electron ]]; then
  echo "Opening Electron Studio window…"
  cd apps/desktop && ./node_modules/.bin/electron .
else
  echo "Electron not installed — opening browser. Run: make install && make desktop"
  if [[ -d apps/web/dist ]]; then
    (cd apps/web && npx --yes serve -l 18766 dist >/dev/null 2>&1 &) || true
  fi
  open "http://127.0.0.1:18766" 2>/dev/null || true
  echo "API log: ${TMPDIR:-/tmp}/formulahub-api.log"
  echo "Press Ctrl+C to leave this Terminal (API may keep running via nohup)."
  wait
fi
CMD
chmod +x "${STAGE}/START-NATIVE.command"

# ---------------------------------------------------------------------------
# Short README — lead with .app
# ---------------------------------------------------------------------------
cat > "${STAGE}/README_MAC.md" << 'EOF'
# FormulaHub ETL — Mac pack

## Unzip → double-click

1. Unzip `FormulaHub-ETL-Mac.zip`
2. Double-click **FormulaHub Studio.app**
3. Studio opens in a **desktop window** (API starts behind the scenes)

No Terminal window required. **Open in Browser** is optional (Studio menu).

### First launch

If the app asks for setup (once):

```bash
cd FormulaHub-ETL
make install && make seed && make build
```

Then double-click **FormulaHub Studio.app** again.

Gatekeeper (unsigned): Right-click the app → **Open**.

### Optional: full Electron .app on this Mac

```bash
cd FormulaHub-ETL
make install && make seed && make build
cd apps/desktop && npm install && npm run dist:mac
open release/mac*/FormulaHub\ Studio.app
```

### Fallback

`START-NATIVE.command` — opens Terminal; use only if the `.app` cannot run.
Closing Terminal can drop ports; prefer the `.app`.

### Docker (browser)

```bash
cd FormulaHub-ETL
docker compose up --build
# Studio http://127.0.0.1:18766
```

Local `work_dir` is primary. No cloud auth in this pack.
EOF

# Keep START_HERE_MAC.md as alias name founders may expect
cp "${STAGE}/README_MAC.md" "${STAGE}/START_HERE_MAC.md"

# ---------------------------------------------------------------------------
# On macOS: try to embed a real electron-builder .app when build is possible
# ---------------------------------------------------------------------------
embed_electron_app() {
  local built=""
  for cand in \
    "${ROOT}/apps/desktop/release/mac/FormulaHub Studio.app" \
    "${ROOT}/apps/desktop/release/mac-arm64/FormulaHub Studio.app" \
    "${ROOT}/apps/desktop/release/mac-x64/FormulaHub Studio.app"
  do
    if [[ -d "${cand}" ]]; then
      built="${cand}"
      break
    fi
  done

  if [[ -z "${built}" && "$(uname -s)" == "Darwin" && "${MAC_PACK_BUILD_ELECTRON:-0}" == "1" ]]; then
    echo "MAC_PACK_BUILD_ELECTRON=1 — building Electron .app on this Mac…"
    if [[ ! -d "${ROOT}/apps/web/dist" ]]; then
      (cd "${ROOT}/apps/web" && npm ci && npm run build)
    fi
    (cd "${ROOT}/apps/desktop" && npm ci && npm run dist:mac) || true
    for cand in \
      "${ROOT}/apps/desktop/release/mac/FormulaHub Studio.app" \
      "${ROOT}/apps/desktop/release/mac-arm64/FormulaHub Studio.app" \
      "${ROOT}/apps/desktop/release/mac-x64/FormulaHub Studio.app"
    do
      if [[ -d "${cand}" ]]; then
        built="${cand}"
        break
      fi
    done
  fi

  if [[ -n "${built}" ]]; then
    echo "Embedding Electron app from ${built}"
    mkdir -p "${STAGE}/ElectronStudio"
    rm -rf "${STAGE}/ElectronStudio/FormulaHub Studio.app"
    cp -R "${built}" "${STAGE}/ElectronStudio/FormulaHub Studio.app"
  fi
}

embed_electron_app

# Strip accidental heavy dirs
find "${STAGE}" -type d -name node_modules -prune -exec rm -rf {} + 2>/dev/null || true
find "${STAGE}" -type d -name .git -prune -exec rm -rf {} + 2>/dev/null || true
find "${STAGE}" -path '*/apps/desktop/release' -prune -exec rm -rf {} + 2>/dev/null || true

rm -f "${ZIP_PATH}" "${OUT_DIR}/FormulaHub-ETL-Mac.tar.gz"
(
  cd "${OUT_DIR}"
  if command -v zip >/dev/null 2>&1; then
    zip -r -q "FormulaHub-ETL-Mac.zip" "FormulaHub-ETL-Mac"
  else
    tar -czf "FormulaHub-ETL-Mac.tar.gz" "FormulaHub-ETL-Mac"
    echo "zip not found — wrote FormulaHub-ETL-Mac.tar.gz instead" >&2
  fi
)

echo "Wrote ${ZIP_PATH}"
echo "Contents (top level):"
ls -la "${STAGE}" | sed -n '1,20p'
ls -lh "${OUT_DIR}/FormulaHub-ETL-Mac.zip" 2>/dev/null || ls -lh "${OUT_DIR}/FormulaHub-ETL-Mac.tar.gz"
