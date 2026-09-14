.PHONY: install seed test test-fast bench bench-pytest bench-10m demo demo-api demo-excel demo-sftp demo-db demo-core-path demo-python-row demo-kafka demo-s3-databricks api worker web build docker-up docker-down lint

ROOT := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
export FORMULAETL_DEMO ?= 1
export FORMULAETL_WORK_DIR ?= $(ROOT)

install:
	python3 -m pip install -e packages/runner -e packages/api
	python3 -m pip install pytest pytest-asyncio httpx openpyxl pandas 'paramiko>=3.0' 'psycopg[binary]>=3.1' 'cryptography>=42.0'
	cd apps/web && npm install

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

demo-lookup-join: seed
	FORMULAETL_DEMO=1 FORMULAETL_WORK_DIR=$(ROOT) \
		python3 -m formulaetl.cli run demos/lookup-join-mapper/pipeline.json

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

docker-up: seed
	docker compose up --build

docker-down:
	docker compose down

lint:
	python3 -m compileall packages/runner packages/api scripts
