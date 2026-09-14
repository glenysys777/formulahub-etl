#!/usr/bin/env bash
# Customer001 LOCAL wedge — failure injection helpers (manual / CI opt-in).
# Classification: LOCAL_ONLY failure drills. Never LIVE_EXTERNAL.
#
# Usage (from repo root):
#   bash scripts/customer001_fail_injections/run_all.sh
#   bash scripts/customer001_fail_injections/01_bad_pgp.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export FORMULAETL_WORK_DIR="${FORMULAETL_WORK_DIR:-$ROOT}"
export FORMULAETL_DEMO="${FORMULAETL_DEMO:-1}"

PASS=0
FAIL=0
SKIP=0

expect_fail() {
  local name="$1"
  shift
  echo "=== FAIL inject: $name ==="
  if "$@" >/tmp/c001_fail_${name}.out 2>/tmp/c001_fail_${name}.err; then
    echo "UNEXPECTED SUCCESS for $name (expected failure)"
    FAIL=$((FAIL + 1))
  else
    echo "OK expected failure: $name (exit=$?)"
    PASS=$((PASS + 1))
  fi
}

# --- 01 bad PGP ---
bad_pgp() {
  python3 scripts/seed_demo.py >/dev/null
  python3 scripts/customer001_local_wedge.py --prepare >/dev/null
  mkdir -p data/drop/customer001
  printf 'not-a-pgp-payload' > data/drop/customer001/orders.csv.pgp
  FORMULAETL_DEMO=1 python3 -m formulaetl.cli run demos/customer001-local-wedge/pipeline.json
}

# --- 02 missing file ---
missing_file() {
  python3 scripts/seed_demo.py >/dev/null
  rm -f data/drop/customer001/orders.csv.pgp
  FORMULAETL_DEMO=1 python3 -m formulaetl.cli run demos/customer001-local-wedge/pipeline.json
}

# --- 03 malformed CSV (decrypts but CSV is garbage) ---
malformed_csv() {
  python3 scripts/seed_demo.py >/dev/null
  python3 <<'PY'
from pathlib import Path
import pgpy
from pgpy.constants import CompressionAlgorithm
root = Path('.')
pub = (root / 'fixtures/keys/demo_public.asc').read_text()
key, _ = pgpy.PGPKey.from_blob(pub)
msg = pgpy.PGPMessage.new(b'not,csv\nthis is|||broken\n', file=True)
try:
    cipher = key.encrypt(msg, compression=CompressionAlgorithm.Uncompressed)
except TypeError:
    cipher = key.encrypt(msg)
drop = root / 'data/drop/customer001/orders.csv.pgp'
drop.parent.mkdir(parents=True, exist_ok=True)
drop.write_bytes(str(cipher).encode())
print('wrote malformed encrypted drop')
PY
  # --no-prepare so harness does not overwrite the bad drop with the good fixture
  FORMULAETL_DEMO=1 python3 scripts/customer001_local_wedge.py --mode demo --no-prepare
}

# --- 04 schema drift (extra required column) ---
schema_drift() {
  python3 scripts/seed_demo.py >/dev/null
  python3 scripts/customer001_local_wedge.py --prepare >/dev/null
  python3 <<'PY'
import json
from pathlib import Path
src = Path('demos/customer001-local-wedge/pipeline.json')
pipe = json.loads(src.read_text())
for n in pipe['nodes']:
    if n['id'] == 'validate':
        n['config']['columns']['must_exist_col'] = 'string'
        n['config']['required_columns'].append('must_exist_col')
out = Path('data/out/customer001/pipeline_schema_drift.json')
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(pipe, indent=2))
print(out)
PY
  FORMULAETL_DEMO=1 python3 -m formulaetl.cli run data/out/customer001/pipeline_schema_drift.json
  # All rows rejected → load 0 → we still may get success status; verify rejects exist
  test -s data/rejects/customer001/orders_rejects.csv
}

# --- 05 destination down (bad postgres host, DEMO=0) ---
destination_down() {
  python3 scripts/seed_demo.py >/dev/null
  python3 scripts/customer001_local_wedge.py --prepare >/dev/null
  python3 <<'PY'
import json, os
from pathlib import Path
from formulaetl.engine.runner import PipelineRunner
from formulaetl.models.pipeline import PipelineDefinition

os.environ["FORMULAETL_DEMO"] = "0"
pipe = json.loads(Path("demos/customer001-local-wedge/pipeline.json").read_text())
for n in pipe["nodes"]:
    if n["id"] == "dest":
        n["config"] = {
            "host": "127.0.0.1",
            "port": 1,
            "database": "nope",
            "user": "nope",
            "password": "nope",
            "table": "customer001_orders",
            "if_exists": "replace",
        }
pipeline = PipelineDefinition.model_validate(pipe)
result = PipelineRunner(work_dir=Path("."), demo_mode=False).run(pipeline)
print(result.status, result.error)
raise SystemExit(0 if result.status == "success" else 1)
PY
}

# --- 06 retry (run twice; second replace should succeed) ---
retry_ok() {
  python3 scripts/seed_demo.py >/dev/null
  python3 scripts/customer001_local_wedge.py --prepare >/dev/null
  FORMULAETL_DEMO=1 python3 scripts/customer001_local_wedge.py --mode demo
  python3 scripts/customer001_local_wedge.py --prepare >/dev/null
  FORMULAETL_DEMO=1 python3 scripts/customer001_local_wedge.py --mode demo
}

case "${1:-all}" in
  01|bad_pgp) expect_fail bad_pgp bad_pgp ;;
  02|missing_file) expect_fail missing_file missing_file ;;
  03|malformed_csv) expect_fail malformed_csv malformed_csv ;;
  04|schema_drift)
    echo "=== schema_drift (expects rejects file) ==="
    if schema_drift; then PASS=$((PASS+1)); echo OK schema_drift; else FAIL=$((FAIL+1)); fi
    ;;
  05|destination_down) expect_fail destination_down destination_down ;;
  06|retry) retry_ok; PASS=$((PASS+1)); echo OK retry ;;
  all)
    expect_fail bad_pgp bad_pgp
    expect_fail missing_file missing_file
    expect_fail malformed_csv malformed_csv
    echo "=== schema_drift ==="
    if schema_drift; then PASS=$((PASS+1)); else FAIL=$((FAIL+1)); fi
    expect_fail destination_down destination_down
    retry_ok; PASS=$((PASS+1)); echo OK retry
    ;;
  *)
    echo "Unknown inject: $1" >&2
    exit 2
    ;;
esac

echo "FAIL_INJECT summary pass=$PASS fail=$FAIL skip=$SKIP"
test "$FAIL" -eq 0
