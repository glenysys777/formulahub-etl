.PHONY: install seed test test-fast bench bench-pytest bench-10m demo demo-api demo-excel demo-sftp demo-db demo-core-path demo-python-row demo-kafka demo-s3-databricks demo-databricks-sql demo-customer001 customer001-wedge customer001-wedge-pg customer001-fail-injects api worker web build docker-up docker-down lint desktop desktop-install desktop-lint dist-mac mac-pack

ROOT := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
export FORMULAETL_DEMO ?= 1
export FORMULAETL_WORK_DIR ?= $(ROOT)

install:
	python3 -m pip install -e packages/runner -e packages/api
	python3 -m pip install pytest pytest-asyncio httpx openpyxl pandas 'paramiko>=3.0' 'psycopg[binary]>=3.1' 'cryptography>=42.0'
	cd apps/web && npm install
	cd apps/desktop && npm install

seed:
	python3 scripts/seed_demo.py

test: seed
	python3 -m pytest tests -v --tb=short -m "not live and not bench"

test-fast: seed
	python3 -m pytest tests -q --tb=short -m "not live and not bench and not slow"

# LOCAL/DEMO wedge scale benches (10K/100K/1M). Never LIVE_CLOUD.
# Optional 10M: BENCH_INCLUDE_10M=1 make bench-10m
bench: seed
	RUN_BENCH=1 FORMULAETL_DEMO=1 FORMULAETL_WORK_DIR=$(ROOT) \
		python3 scripts/local_wedge_bench.py --require-run-bench \
		--scales 10000,100000,1000000 \
		--source s3 --dest snowflake \
		--out data/out/bench/local_wedge_results.json

bench-pytest: seed
	RUN_BENCH=1 FORMULAETL_DEMO=1 FORMULAETL_WORK_DIR=$(ROOT) \
		python3 -m pytest tests/bench -v --tb=short -m bench -s

bench-10m: seed
	RUN_BENCH=1 BENCH_INCLUDE_10M=1 FORMULAETL_DEMO=1 FORMULAETL_WORK_DIR=$(ROOT) \
		python3 scripts/local_wedge_bench.py --require-run-bench \
		--scales 10000000 --timebox-s 3600 \
		--source s3 --dest snowflake \
		--out data/out/bench/local_wedge_10m.json

demo: seed
	FORMULAETL_DEMO=1 FORMULAETL_WORK_DIR=$(ROOT) \
		python3 -m formulaetl.cli run demos/s3-pgp-snowflake/pipeline.json

demo-api: seed
	FORMULAETL_DEMO=1 FORMULAETL_WORK_DIR=$(ROOT) \
		python3 -m formulaetl.cli run demos/api-map-transform/pipeline.json


demo-excel: seed
	FORMULAETL_DEMO=1 FORMULAETL_WORK_DIR=$(ROOT) \
		python3 -m formulaetl.cli run demos/excel-to-file/pipeline.json

demo-sftp: seed
	FORMULAETL_DEMO=1 FORMULAETL_WORK_DIR=$(ROOT) \
		python3 -m formulaetl.cli run demos/sftp-excel-to-file/pipeline.json

demo-db: seed
	FORMULAETL_DEMO=1 FORMULAETL_WORK_DIR=$(ROOT) \
		python3 -m formulaetl.cli run demos/db-to-file/pipeline.json

demo-core-path: seed
	FORMULAETL_DEMO=1 FORMULAETL_WORK_DIR=$(ROOT) \
		python3 -m formulaetl.cli run demos/core-path/pipeline.json

demo-python-row: seed
	FORMULAETL_DEMO=1 FORMULAETL_WORK_DIR=$(ROOT) \
		python3 -m formulaetl.cli run demos/python-row-flex/pipeline.json

demo-kafka: seed
	FORMULAETL_DEMO=1 FORMULAETL_WORK_DIR=$(ROOT) \
		python3 -m formulaetl.cli run demos/api-kafka-databricks/pipeline.json

demo-s3-databricks: seed
	FORMULAETL_DEMO=1 FORMULAETL_WORK_DIR=$(ROOT) \
		python3 -m formulaetl.cli run demos/s3-databricks/pipeline.json

demo-databricks-sql: seed
	FORMULAETL_DEMO=1 FORMULAETL_WORK_DIR=$(ROOT) \
		python3 -m formulaetl.cli run demos/api-databricks-sql/pipeline.json

demo-lookup-join: seed
	FORMULAETL_DEMO=1 FORMULAETL_WORK_DIR=$(ROOT) \
		python3 -m formulaetl.cli run demos/lookup-join-mapper/pipeline.json

# Customer001 LOCAL wedge (filesystem; DEMO postgres mirror). Never LIVE_EXTERNAL.
demo-customer001: seed
	FORMULAETL_DEMO=1 FORMULAETL_WORK_DIR=$(ROOT) \
		python3 scripts/customer001_local_wedge.py --mode demo

customer001-wedge: demo-customer001

# Real local Postgres (Mac/CI service). Requires LOCAL_POSTGRES_DSN + FORMULAETL_DEMO=0.
customer001-wedge-pg: seed
	FORMULAETL_DEMO=0 FORMULAETL_WORK_DIR=$(ROOT) \
		python3 scripts/customer001_local_wedge.py --mode postgres

customer001-fail-injects: seed
	bash scripts/customer001_fail_injections/run_all.sh

api: seed
	FORMULAETL_DEMO=1 FORMULAETL_WORK_DIR=$(ROOT) \
		python3 -m uvicorn formulaetl_api.main:app --host 0.0.0.0 --port 18765 --app-dir packages/api

# Standalone worker (optional). Default ``make api`` embeds a worker thread.
# Use this when FORMULAETL_EMBEDDED_WORKER=0 so the API only enqueues.
worker: seed
	FORMULAETL_DEMO=1 FORMULAETL_WORK_DIR=$(ROOT) FORMULAETL_EMBEDDED_WORKER=0 \
		PYTHONPATH=$(ROOT)/packages/api:$(ROOT)/packages/runner \
		python3 -m formulaetl_api.worker

web:
	cd apps/web && npm run dev -- --host 0.0.0.0 --port 18766

build:
	cd apps/web && npm run build

# Desktop Studio shell (Electron). Starts local API if needed, opens Studio WebView.
# Mac .app / .dmg: on macOS run `cd apps/desktop && npm run dist:mac` — see docs/studio/DESKTOP_SHELL.md
desktop-install:
	cd apps/desktop && npm install

desktop-lint:
	cd apps/desktop && npm run build:check

desktop: build
	cd apps/desktop && npm install && npm start

# Mac .app + .dmg (must run on macOS). Use: make dist-mac   or   make dist:mac
dist-mac: build
	cd apps/desktop && npm install && npm run dist:mac

dist\:mac: dist-mac

docker-up: seed
	docker compose up --build

docker-down:
	docker compose down

# Zip FormulaHub-ETL-Mac: FormulaHub Studio.app + README + START-NATIVE.command fallback.
# Optional on macOS: MAC_PACK_BUILD_ELECTRON=1 make mac-pack  (embeds electron-builder .app)
mac-pack:
	bash scripts/mac_pack.sh

lint:
	python3 -m compileall packages/runner packages/api scripts
