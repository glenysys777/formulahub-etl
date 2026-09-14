"""Phase B: DatasetHandle / ArtifactHandle / adapter / planner."""

from __future__ import annotations

from pathlib import Path

from formulaetl.engine.planner import decide_feed, plan_pipeline
from formulaetl.engine.runner import PipelineRunner
from formulaetl.models.pipeline import PipelineDefinition
from formulaetl.sdk.adapter import (
    apply_upstream_to_component,
    dataset_to_rows,
    rows_to_dataset,
    run_batched,
    run_legacy,
)
from formulaetl.sdk.base import BaseComponent
from formulaetl.sdk.capabilities import (
    ARTIFACT_SOURCE,
    BLOCKING_ROWS,
    LEGACY,
    ROWWISE,
    TABULAR_FROM_FILE,
)
from formulaetl.sdk.context import ComponentResult, Metrics, RunContext
from formulaetl.sdk.data import ArtifactHandle, DatasetHandle, RowBatch
from formulaetl.sdk.registry import list_components


def _ctx(work: Path, batch_size: int = 2) -> RunContext:
    return RunContext(
        run_id="test",
        pipeline_id="test",
        demo_mode=True,
        work_dir=work,
        data_dir=work / "data",
        log=lambda m: None,
        batch_size=batch_size,
    )


def test_row_batch_iter_and_len():
    batch = RowBatch(rows=[{"a": 1}, {"a": 2}], batch_index=0, eof=False)
    assert len(batch) == 2
    assert [r["a"] for r in batch] == [1, 2]


def test_dataset_handle_chunks_and_materialize_adapter():
    rows = [{"n": i} for i in range(5)]
    ds = DatasetHandle.from_rows(rows, batch_size=2)
    batches = list(ds.iter_batches())
    assert [len(b) for b in batches] == [2, 2, 1]
    assert batches[-1].eof is True
    assert dataset_to_rows(ds) == rows
    roundtrip = rows_to_dataset(rows, batch_size=3)
    assert [len(b) for b in roundtrip.iter_batches()] == [3, 2]


def test_dataset_handle_from_csv_path(tmp_path: Path):
    csv_path = tmp_path / "tiny.csv"
    csv_path.write_text("id,name\n1,a\n2,b\n3,c\n", encoding="utf-8")
    ds = DatasetHandle.from_csv_path(csv_path, batch_size=2)
    batches = list(ds.iter_batches())
    assert len(batches) == 2
    assert batches[0].rows[0]["name"] == "a"
    assert batches[-1].eof is True
    assert ds.materialize() == [
        {"id": "1", "name": "a"},
        {"id": "2", "name": "b"},
        {"id": "3", "name": "c"},
    ]


def test_artifact_handle_from_path(tmp_path: Path):
    p = tmp_path / "blob.csv"
    p.write_bytes(b"hello,world\n")
    handle = ArtifactHandle.from_path(p, temp=False)
    assert handle.size == 12
    assert handle.content_type == "text/csv"
    assert handle.checksum
    assert handle.temp is False
    assert handle.read_bytes() == b"hello,world\n"
    d = handle.to_dict()
    restored = ArtifactHandle.from_dict(d)
    assert restored is not None
    assert restored.checksum == handle.checksum


def test_legacy_component_run_via_adapter(tmp_path: Path):
    class PlusOne(BaseComponent):
        component_type = "plus_one_test"
        capabilities = ROWWISE

        def run(self, ctx, rows=None):
            rows = rows or []
            return ComponentResult(
                rows=[{"n": int(r["n"]) + 1} for r in rows],
                metrics=Metrics(rows_in=len(rows), rows_out=len(rows)),
            )

    ctx = _ctx(tmp_path, batch_size=2)
    ds = DatasetHandle.from_rows([{"n": 1}, {"n": 2}, {"n": 3}], batch_size=2)
    batched = run_batched(PlusOne({}), ctx, ds, batch_size=2)
    assert [r["n"] for r in batched.rows] == [2, 3, 4]
    assert batched.metrics.extras["feed"] == "batches"
    assert batched.metrics.extras["batches"] == 2  # 2+1 rows → 2 batches

    materialized = run_legacy(PlusOne({}), ctx, rows_to_dataset([{"n": 10}]))
    assert materialized.rows == [{"n": 11}]


def test_apply_upstream_skips_bytes_when_path_exists(tmp_path: Path):
    blob = tmp_path / "obj.bin"
    blob.write_bytes(b"not-copied")
    handle = ArtifactHandle.from_path(blob, temp=False)

    class Dummy(BaseComponent):
        component_type = "dummy_test"

        def run(self, ctx, rows=None):
            return ComponentResult()

    component = Dummy({"delimiter": ","})
    ctx = _ctx(tmp_path)
    apply_upstream_to_component(
        component,
        ctx,
        artifacts={"path": str(blob), "bytes": b"secret-bytes", "content": "nope"},
        handle=handle,
        next_caps=TABULAR_FROM_FILE,
    )
    assert component.config["path"] == str(blob)
    assert "bytes" not in component.config
    assert "content" not in component.config
    assert "upstream_bytes" not in ctx.variables


def test_planner_uses_capabilities_for_feed_mode():
    feed, reason = decide_feed(ROWWISE, inbound=1, outbound=1, upstream_kind="rows")
    assert feed == "batches"
    feed, reason = decide_feed(BLOCKING_ROWS, inbound=1, outbound=1, upstream_kind="rows")
    assert feed == "materialized_rows"
    feed, reason = decide_feed(ROWWISE, inbound=1, outbound=2, upstream_kind="rows")
    assert feed == "materialized_rows"
    assert "fan-out" in reason
    feed, _ = decide_feed(ARTIFACT_SOURCE, inbound=0, outbound=1, upstream_kind=None)
    assert feed == "none"
    feed, _ = decide_feed(TABULAR_FROM_FILE, inbound=1, outbound=1, upstream_kind="artifact")
    assert feed == "artifact"
    feed, _ = decide_feed(LEGACY, inbound=1, outbound=1, upstream_kind="rows")
    assert feed == "materialized_rows"


def test_plan_flagship_like_graph():
    pipeline = PipelineDefinition.model_validate(
        {
            "id": "plan-test",
            "name": "plan-test",
            "nodes": [
                {"id": "s3", "type": "s3_source", "config": {"bucket": "demo", "key": "k"}},
                {
                    "id": "pgp",
                    "type": "pgp_decrypt",
                    "config": {"private_key_path": "fixtures/keys/demo_private.asc"},
                },
                {"id": "parse", "type": "csv_parser", "config": {"delimiter": ","}},
                {
                    "id": "validate",
                    "type": "schema_validate",
                    "config": {"columns": {"order_id": "int"}},
                },
                {
                    "id": "transform",
                    "type": "transform",
                    "config": {"add_constants": {"x": 1}},
                },
                {
                    "id": "dest",
                    "type": "local_file_destination",
                    "config": {"path": "out.csv"},
                },
                {
                    "id": "rejects",
                    "type": "local_file_destination",
                    "config": {"path": "rej.csv"},
                },
                {
                    "id": "sort",
                    "type": "sort",
                    "config": {"keys": ["order_id:asc"]},
                },
            ],
            "edges": [
                {"id": "e1", "source": "s3", "target": "pgp"},
                {"id": "e2", "source": "pgp", "target": "parse"},
                {"id": "e3", "source": "parse", "target": "validate"},
                {"id": "e4", "source": "validate", "target": "transform", "sourceHandle": "out"},
                {"id": "e5", "source": "transform", "target": "dest"},
                {"id": "e6", "source": "validate", "target": "rejects", "sourceHandle": "rejects"},
                {"id": "e7", "source": "parse", "target": "sort"},
            ],
        }
    )
    plan = plan_pipeline(pipeline, batch_size=8)
    assert plan.nodes["s3"].feed == "none"
    assert plan.nodes["pgp"].feed == "artifact"
    assert plan.nodes["parse"].feed == "artifact"
    assert plan.nodes["validate"].feed == "materialized_rows"  # fan-out
    assert plan.nodes["transform"].feed == "batches"
    assert plan.nodes["dest"].feed == "materialized_rows"
    assert plan.nodes["sort"].feed == "materialized_rows"
    assert plan.nodes["sort"].capabilities.blocking is True


def test_python_row_batch_mode_is_blocking():
    from formulaetl.components.python_row import PythonRow

    row = PythonRow({"mode": "row", "code": "row['x']=1"})
    batch = PythonRow({"mode": "batch", "code": "rows = rows"})
    assert row.get_capabilities().supports_batch is True
    assert batch.get_capabilities().requires_materialization is True
    assert batch.get_capabilities().blocking is True


def test_list_components_exposes_live_capabilities():
    by = {c["type"]: c for c in list_components()}
    assert "capabilities" in by["filter"]
    caps = by["filter"]["capabilities"]
    assert caps["supports_batch"] is True
    assert caps["requires_materialization"] is False
    assert by["sort"]["capabilities"]["blocking"] is True
    assert by["s3_source"]["capabilities"]["io_kind"] == "artifact"


def test_runner_feeds_filter_in_bounded_batches(work_dir: Path):
    """Linear csv → filter → dest: planner must batch the row-wise filter."""
    pipeline = PipelineDefinition.model_validate(
        {
            "id": "batch-demo",
            "name": "batch-demo",
            "nodes": [
                {
                    "id": "src",
                    "type": "local_file_source",
                    "config": {
                        "path": "fixtures/sample/orders_17cols.csv",
                        "format": "csv",
                    },
                },
                {
                    "id": "flt",
                    "type": "filter",
                    "config": {"expression": "order_id != ''"},
                },
                {
                    "id": "out",
                    "type": "local_file_destination",
                    "config": {"path": "data/out/batched.csv", "format": "csv"},
                },
            ],
            "edges": [
                {"id": "e1", "source": "src", "target": "flt"},
                {"id": "e2", "source": "flt", "target": "out"},
            ],
        }
    )
    runner = PipelineRunner(work_dir=work_dir, demo_mode=True, batch_size=3)
    result = runner.run(pipeline)
    assert result.status == "success", result.error
    assert result.plan["nodes"]["flt"]["feed"] == "batches"
    assert result.plan["nodes"]["out"]["feed"] == "materialized_rows"
    assert result.node_metrics["flt"]["feed"] == "batches"
    assert result.node_metrics["flt"]["batches"] >= 2
    assert result.node_metrics["flt"]["rows_out"] == 13
    written = work_dir / "data/out/batched.csv"
    assert written.exists()
    assert written.read_text(encoding="utf-8").count("\n") == 14  # header + 13


def test_csv_parser_streams_from_artifact_path(work_dir: Path):
    from formulaetl.components.csv_parser import CSVParser

    src = work_dir / "fixtures/sample/orders_17cols.csv"
    ctx = _ctx(work_dir, batch_size=4)
    ctx.variables["upstream_path"] = str(src)
    result = CSVParser({"delimiter": ","}).run(ctx)
    assert result.metrics.rows_out == 13
    assert result.dataset is not None
    assert "Customer 1" in result.rows[0]["customer_name"]
