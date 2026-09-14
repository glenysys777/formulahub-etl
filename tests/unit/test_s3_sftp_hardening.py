"""Phase C — S3 pagination helper + SFTP policy unit coverage (demo + mocked live)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from formulaetl.components.sftp_source import SFTPSource, _host_key_policy
from formulaetl.components.source_s3 import S3Source, iter_s3_keys
from formulaetl.sdk.context import RunContext
from formulaetl.sdk.io_util import boto3_client_kwargs, retry_call


def _ctx(work: Path, demo: bool = True) -> RunContext:
    return RunContext(
        run_id="io-test",
        pipeline_id="io-test",
        demo_mode=demo,
        work_dir=work,
        data_dir=work / "data",
        log=lambda m: None,
    )


def test_iter_s3_keys_paginates():
    client = MagicMock()
    client.list_objects_v2.side_effect = [
        {
            "IsTruncated": True,
            "NextContinuationToken": "t1",
            "Contents": [{"Key": "a/1", "Size": 1}, {"Key": "a/2", "Size": 2}],
        },
        {
            "IsTruncated": False,
            "Contents": [{"Key": "a/3", "Size": 3}],
        },
    ]
    keys = list(iter_s3_keys(client, bucket="b", prefix="a/", page_size=2))
    assert [k["key"] for k in keys] == ["a/1", "a/2", "a/3"]
    assert client.list_objects_v2.call_count == 2
    assert client.list_objects_v2.call_args_list[1].kwargs["ContinuationToken"] == "t1"


def test_iter_s3_keys_respects_max_keys():
    client = MagicMock()
    client.list_objects_v2.return_value = {
        "IsTruncated": True,
        "NextContinuationToken": "x",
        "Contents": [{"Key": f"k{i}", "Size": i} for i in range(5)],
    }
    keys = list(iter_s3_keys(client, bucket="b", prefix="", max_keys=3))
    assert len(keys) == 3


def test_s3_demo_list_prefix(work_dir: Path):
    c = S3Source({"bucket": "demo", "prefix": "demo/", "list_only": True})
    result = c.run(_ctx(work_dir))
    assert result.side_effects["list_only"] is True
    assert result.metrics.rows_out >= 1
    assert all("_s3_key" in r for r in result.rows)


def test_s3_demo_download_unchanged(work_dir: Path):
    c = S3Source({"bucket": "demo", "key": "demo/orders_encrypted.csv.pgp"})
    result = c.run(_ctx(work_dir))
    assert result.artifact is not None
    assert "bytes" not in result.artifacts


def test_boto3_client_kwargs_has_retries():
    kw = boto3_client_kwargs(region="us-west-2", max_attempts=7)
    assert kw["region_name"] == "us-west-2"
    assert kw["config"].retries["max_attempts"] == 7


def test_retry_call_succeeds_after_failures():
    state = {"n": 0}

    def flaky():
        state["n"] += 1
        if state["n"] < 3:
            raise TimeoutError("boom")
        return "ok"

    assert retry_call(flaky, attempts=5, base_delay=0.01, label="flaky") == "ok"
    assert state["n"] == 3


def test_sftp_host_key_default_is_reject():
    import paramiko

    client = MagicMock()
    _host_key_policy(paramiko, "reject", None)(client)
    client.set_missing_host_key_policy.assert_called()
    policy = client.set_missing_host_key_policy.call_args[0][0]
    assert isinstance(policy, paramiko.RejectPolicy)


def test_sftp_live_requires_auth(work_dir: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FORMULAETL_DEMO", "0")
    c = SFTPSource(
        {
            "host": "sftp.example.invalid",
            "remote_path": "/x.csv",
            "local_staging_path": "data/out/sftp_staging/x.csv",
            "username": "u",
        }
    )
    with pytest.raises(ValueError, match="password and/or key_path"):
        c.run(_ctx(work_dir, demo=False))


def test_sftp_live_streams_via_get(work_dir: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FORMULAETL_DEMO", "0")
    dest = work_dir / "data/out/sftp_staging/live.csv"
    dest.parent.mkdir(parents=True, exist_ok=True)

    mock_sftp = MagicMock()

    def fake_get(remote, local):
        Path(local).write_text("a,b\n1,2\n", encoding="utf-8")

    mock_sftp.get.side_effect = fake_get
    mock_sftp.get_channel.return_value = MagicMock()

    mock_client = MagicMock()
    mock_client.open_sftp.return_value = mock_sftp
    mock_client.get_transport.return_value = MagicMock()

    with patch("paramiko.SSHClient", return_value=mock_client):
        c = SFTPSource(
            {
                "host": "sftp.example.invalid",
                "port": 22,
                "username": "u",
                "password": "p",
                "remote_path": "/remote.csv",
                "local_staging_path": str(dest),
                "host_key_policy": "auto_add",
                "max_retries": 1,
            }
        )
        result = c.run(_ctx(work_dir, demo=False))

    assert result.side_effects["mode"] == "sftp"
    assert dest.exists()
    mock_sftp.get.assert_called_once()
    mock_client.connect.assert_called_once()
    assert mock_client.connect.call_args.kwargs.get("look_for_keys") is False
