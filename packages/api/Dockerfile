FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY packages/runner /tmp/runner
COPY packages/api /tmp/api
RUN pip install --no-cache-dir /tmp/runner /tmp/api uvicorn

COPY scripts /app/scripts
COPY demos /app/demos
COPY fixtures /app/fixtures
COPY data /app/data

ENV FORMULAETL_DEMO=1
ENV FORMULAETL_WORK_DIR=/app
ENV PYTHONPATH=/app

RUN python scripts/seed_demo.py

EXPOSE 18765
CMD ["python", "-m", "uvicorn", "formulaetl_api.main:app", "--host", "0.0.0.0", "--port", "18765"]
