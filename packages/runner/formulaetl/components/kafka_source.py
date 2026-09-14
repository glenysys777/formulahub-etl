"""Kafka Source — consume topic messages; demo mode reads a fixture (no broker)."""

from __future__ import annotations

import csv
import io
import json
import os
from pathlib import Path
from typing import Any

from formulaetl.sdk.base import BaseComponent
from formulaetl.sdk.context import ComponentResult, Metrics, RunContext, timed
from formulaetl.sdk.registry import register


def _parse_message(raw: str | bytes, fmt: str) -> dict[str, Any] | None:
    if isinstance(raw, (bytes, bytearray)):
        text = raw.decode("utf-8", errors="replace").strip()
    else:
        text = str(raw).strip()
    if not text:
        return None
    fmt = (fmt or "json").lower()
    if fmt == "csv":
        reader = csv.DictReader(io.StringIO(text))
        rows = list(reader)
        return rows[0] if rows else {"_raw": text}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {"_raw": text}
    if isinstance(data, dict):
        return data
    return {"value": data}


def _load_fixture_rows(path: Path, fmt: str, limit: int) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    rows: list[dict[str, Any]] = []
    suffix = path.suffix.lower()
    stripped = text.strip()

    if suffix == ".jsonl" or (
        suffix != ".json" and "\n" in stripped and stripped.lstrip().startswith("{")
    ):
        for ln in text.splitlines():
            if not ln.strip():
                continue
            row = _parse_message(ln, "json")
            if row:
                rows.append(row)
    elif suffix == ".json" or stripped.startswith("[") or stripped.startswith("{"):
        data = json.loads(stripped)
        if isinstance(data, list):
            for item in data:
                rows.append(item if isinstance(item, dict) else {"value": item})
        elif isinstance(data, dict):
            for key in ("records", "data", "items", "messages"):
                val = data.get(key)
                if isinstance(val, list):
                    for item in val:
                        rows.append(item if isinstance(item, dict) else {"value": item})
                    break
            else:
                # Multi-line JSON objects disguised as .json
                lines = [ln for ln in text.splitlines() if ln.strip()]
                if len(lines) > 1:
                    rows = []
                    for ln in lines:
                        row = _parse_message(ln, "json")
                        if row:
                            rows.append(row)
                else:
                    rows.append(data)
    else:
        for ln in text.splitlines():
            if not ln.strip():
                continue
            row = _parse_message(ln, fmt)
            if row:
                rows.append(row)

    if limit > 0:
        rows = rows[:limit]
    return rows


@register
class KafkaSource(BaseComponent):
    component_type = "kafka_source"
    display_name = "Kafka Source"
    category = "source"
    config_schema = {
        "type": "object",
        "required": ["brokers", "topic"],
        "properties": {
            "brokers": {
                "type": "string",
                "description": "Comma-separated broker list, e.g. localhost:9092",
            },
            "topic": {"type": "string"},
            "group_id": {"type": "string", "default": "formulaetl"},
            "auto_offset_reset": {
                "type": "string",
                "enum": ["earliest", "latest"],
                "default": "earliest",
            },
            "max_messages": {"type": "number", "default": 100},
            "timeout_sec": {"type": "number", "default": 10},
            "security": {
                "type": "string",
                "enum": ["plain", "ssl", "sasl_plain"],
                "default": "plain",
                "description": "Demo-friendly security mode label (plain = no auth)",
            },
            "format": {"type": "string", "enum": ["json", "csv"], "default": "json"},
            "demo": {"type": "boolean", "default": False},
            "fixture_path": {
                "type": "string",
                "description": "Optional fixture override for demo mode",
            },
        },
    }
    parameters = [
        {
            "key": "brokers",
            "label": "Brokers",
            "type": "string",
            "required": True,
            "help": "Comma-separated brokers (use demo for fixture mode)",
            "placeholder": "localhost:9092",
        },
        {
            "key": "topic",
            "label": "Topic",
            "type": "string",
            "required": True,
            "help": "Kafka topic name",
            "placeholder": "orders",
        },
        {
            "key": "group_id",
            "label": "Group ID",
            "type": "string",
            "required": False,
            "default": "formulaetl",
            "help": "Consumer group id",
        },
        {
            "key": "auto_offset_reset",
            "label": "Offset reset",
            "type": "select",
            "required": False,
            "default": "earliest",
            "options": ["earliest", "latest"],
            "help": "Where to start when no committed offset",
        },
        {
            "key": "max_messages",
            "label": "Max messages",
            "type": "number",
            "required": False,
            "default": 100,
            "help": "Stop after this many messages (batch pull)",
        },
        {
            "key": "timeout_sec",
            "label": "Timeout (sec)",
            "type": "number",
            "required": False,
            "default": 10,
            "help": "Poll timeout seconds",
        },
        {
            "key": "security",
            "label": "Security",
            "type": "select",
            "required": False,
            "default": "plain",
            "options": ["plain", "ssl", "sasl_plain"],
            "help": "plain = demo / no auth (MVP)",
        },
        {
            "key": "format",
            "label": "Message format",
            "type": "select",
            "required": False,
            "default": "json",
            "options": ["json", "csv"],
            "help": "Parse message value as JSON or CSV row",
        },
        {
            "key": "demo",
            "label": "Demo fixture",
            "type": "boolean",
            "required": False,
            "default": False,
            "help": "Force fixture read instead of live Kafka",
        },
    ]

    def _use_demo(self, ctx: RunContext) -> bool:
        if self.config.get("demo") is True:
            return True
        brokers = str(self.config.get("brokers") or "").strip().lower()
        if brokers in ("demo", "localhost:demo", "fixture"):
            return True
        if ctx.demo_mode or os.environ.get("FORMULAETL_DEMO") == "1":
            return True
        return False

    def _fixture_path(self, ctx: RunContext) -> Path:
        custom = self.config.get("fixture_path")
        if custom:
            return ctx.resolve(str(custom))
        candidates = [
            ctx.resolve("fixtures/sample/kafka_orders.jsonl"),
            Path(__file__).resolve().parents[4] / "fixtures" / "sample" / "kafka_orders.jsonl",
            ctx.resolve("fixtures/sample/kafka_orders.json"),
        ]
        for path in candidates:
            if path.exists():
                return path
        raise FileNotFoundError(
            "KafkaSource (demo): fixtures/sample/kafka_orders.jsonl not found under work_dir"
        )

    def _consume_live(self, ctx: RunContext) -> list[dict[str, Any]]:
        brokers = str(self.config.get("brokers") or "")
        topic = str(self.config["topic"])
        group_id = str(self.config.get("group_id") or "formulaetl")
        auto_offset = str(self.config.get("auto_offset_reset") or "earliest")
        max_messages = int(self.config.get("max_messages") or 100)
        timeout_sec = float(self.config.get("timeout_sec") or 10)
        fmt = str(self.config.get("format") or "json")
        security = str(self.config.get("security") or "plain").lower()

        # Prefer confluent-kafka, fall back to kafka-python
        consumer = None
        backend = None
        try:
            from confluent_kafka import Consumer  # type: ignore

            conf: dict[str, Any] = {
                "bootstrap.servers": brokers,
                "group.id": group_id,
                "auto.offset.reset": auto_offset,
                "enable.auto.commit": True,
            }
            if security == "ssl":
                conf["security.protocol"] = "ssl"
            elif security == "sasl_plain":
                conf["security.protocol"] = "sasl_plaintext"
            consumer = Consumer(conf)
            consumer.subscribe([topic])
            backend = "confluent-kafka"
        except ImportError:
            try:
                from kafka import KafkaConsumer  # type: ignore

                kwargs: dict[str, Any] = {
                    "bootstrap_servers": [b.strip() for b in brokers.split(",") if b.strip()],
                    "group_id": group_id,
                    "auto_offset_reset": auto_offset,
                    "consumer_timeout_ms": int(timeout_sec * 1000),
                    "enable_auto_commit": True,
                    "value_deserializer": lambda v: v,
                }
                if security == "ssl":
                    kwargs["security_protocol"] = "SSL"
                elif security == "sasl_plain":
                    kwargs["security_protocol"] = "SASL_PLAINTEXT"
                consumer = KafkaConsumer(topic, **kwargs)
                backend = "kafka-python"
            except ImportError as exc:
                raise ImportError(
                    "Live Kafka requires an optional client. Install one of:\n"
                    "  pip install formulaetl[kafka]   # kafka-python\n"
                    "  # or: pip install confluent-kafka\n"
                    "Or set brokers=demo / FORMULAETL_DEMO=1 to use the fixture."
                ) from exc

        rows: list[dict[str, Any]] = []
        try:
            if backend == "confluent-kafka":
                deadline = timeout_sec
                import time

                t0 = time.perf_counter()
                while len(rows) < max_messages and (time.perf_counter() - t0) < deadline:
                    msg = consumer.poll(1.0)
                    if msg is None:
                        continue
                    if msg.error():
                        continue
                    row = _parse_message(msg.value(), fmt)
                    if row:
                        rows.append(row)
                consumer.close()
            else:
                for msg in consumer:
                    row = _parse_message(msg.value, fmt)
                    if row:
                        rows.append(row)
                    if len(rows) >= max_messages:
                        break
                consumer.close()
        finally:
            try:
                consumer.close()
            except Exception:
                pass

        ctx.emit(f"KafkaSource [{backend}]: topic={topic} → {len(rows)} messages")
        return rows

    def run(self, ctx: RunContext, rows: list[dict[str, Any]] | None = None) -> ComponentResult:
        metrics = Metrics()
        with timed(metrics):
            brokers = self.config.get("brokers")
            topic = self.config["topic"]
            fmt = str(self.config.get("format") or "json")
            max_messages = int(self.config.get("max_messages") or 100)

            if self._use_demo(ctx):
                path = self._fixture_path(ctx)
                out_rows = _load_fixture_rows(path, fmt, max_messages)
                ctx.emit(
                    f"KafkaSource [demo]: topic={topic} brokers={brokers} "
                    f"← {path.name} ({len(out_rows)} messages)"
                )
                mode = "demo"
            else:
                out_rows = self._consume_live(ctx)
                mode = "kafka"

            metrics.rows_in = 0
            metrics.rows_out = len(out_rows)

        return ComponentResult(
            rows=out_rows,
            metrics=metrics,
            side_effects={
                "mode": mode,
                "brokers": brokers,
                "topic": topic,
                "group_id": self.config.get("group_id") or "formulaetl",
            },
            artifacts={"message_count": len(out_rows)},
        )
