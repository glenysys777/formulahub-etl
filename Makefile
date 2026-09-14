.PHONY: install seed test demo demo-api demo-excel demo-sftp demo-db demo-core-path demo-python-row demo-kafka demo-s3-databricks api web build docker-up docker-down lint

ROOT := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
export FORMULAETL_DEMO ?= 1
export FORMULAETL_WORK_DIR ?= $(ROOT)

install:
	python3 -m pip install -e packages/runner -e packages/api
	python3 -m pip install pytest pytest-asyncio httpx openpyxl pandas 'paramiko>=3.0' 'psycopg[binary]>=3.1'
	cd apps/web && npm install

seed:
	python3 scripts/seed_demo.py

test: seed
	python3 -m pytest tests -v --tb=short

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
