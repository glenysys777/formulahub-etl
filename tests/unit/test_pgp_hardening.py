"""Phase C — PGP large-file path, wrong key / corrupt, secret redaction."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from formulaetl.components.pgp_decrypt import PGPDecrypt
from formulaetl.components.pgp_encrypt import PGPEncrypt
from formulaetl.sdk.context import RunContext
from formulaetl.sdk.io_util import redact_secrets


def _ctx(work: Path) -> RunContext:
    return RunContext(
        run_id="pgp-test",
        pipeline_id="pgp-test",
        demo_mode=True,
        work_dir=work,
        data_dir=work / "data",
        log=lambda m: None,
    )


def test_pgp_roundtrip_via_path(work_dir: Path):
    plain = work_dir / "data" / "plain.csv"
    plain.parent.mkdir(parents=True, exist_ok=True)
    plain.write_text("id,name\n1,alpha\n", encoding="utf-8")
    enc = PGPEncrypt(
        {
            "public_key_path": "fixtures/keys/demo_public.asc",
            "input_path": str(plain),
            "armor": True,
        }
    ).run(_ctx(work_dir))
    assert enc.artifact is not None
    assert Path(enc.artifact.path).exists()
    assert enc.artifact.temp is True

    dec = PGPDecrypt(
        {
            "private_key_path": "fixtures/keys/demo_private.asc",
            "input_path": enc.artifact.path,
        }
    ).run(_ctx(work_dir))
    assert "alpha" in (dec.artifacts.get("content") or Path(dec.artifact.path).read_text())


def test_pgp_private_key_ref_env(work_dir: Path, monkeypatch: pytest.MonkeyPatch):
    key = str((work_dir / "fixtures/keys/demo_private.asc").resolve())
    monkeypatch.setenv("FORMULAETL_PGP_PRIVATE_KEY", key)
    enc_bytes = (work_dir / "data/s3/demo/orders_encrypted.csv.pgp").read_bytes()
    result = PGPDecrypt(
        {
            "private_key_ref": "FORMULAETL_PGP_PRIVATE_KEY",
            "bytes": enc_bytes,
        }
    ).run(_ctx(work_dir))
    assert result.metrics.rows_out == 1
    assert "order_id" in result.artifacts["content"]


def test_pgp_wrong_key_clear_error(work_dir: Path, tmp_path: Path):
    """Encrypt to demo public key, try decrypt with a different freshly generated key."""
    import pgpy
    from pgpy.constants import (
        CompressionAlgorithm,
        HashAlgorithm,
        KeyFlags,
        PubKeyAlgorithm,
        SymmetricKeyAlgorithm,
    )

    plain = tmp_path / "msg.txt"
    plain.write_text("secret-payload", encoding="utf-8")
    enc = PGPEncrypt(
        {
            "public_key_path": "fixtures/keys/demo_public.asc",
            "input_path": str(plain),
            "armor": True,
        }
    ).run(_ctx(work_dir))

    # Generate an unrelated key pair
    other = pgpy.PGPKey.new(PubKeyAlgorithm.RSAEncryptOrSign, 2048)
    uid = pgpy.PGPUID.new("Other", email="other@example.com")
    other.add_uid(
        uid,
        usage={KeyFlags.Sign, KeyFlags.EncryptCommunications, KeyFlags.EncryptStorage},
        hashes=[HashAlgorithm.SHA256],
        ciphers=[SymmetricKeyAlgorithm.AES256],
        compression=[CompressionAlgorithm.ZLIB],
    )
    other_priv = tmp_path / "other_private.asc"
    other_priv.write_text(str(other), encoding="utf-8")

    with pytest.raises(ValueError, match="decryption failed|wrong key"):
        PGPDecrypt(
            {
                "private_key_path": str(other_priv),
                "input_path": enc.artifact.path,
            }
        ).run(_ctx(work_dir))


def test_pgp_corrupt_input(work_dir: Path):
    bad = work_dir / "data" / "corrupt.pgp"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_bytes(b"this is not pgp ciphertext at all")
    with pytest.raises(ValueError, match="corrupt|non-PGP"):
        PGPDecrypt(
            {
                "private_key_path": "fixtures/keys/demo_private.asc",
                "input_path": str(bad),
            }
        ).run(_ctx(work_dir))


def test_pgp_no_passphrase_in_logs(work_dir: Path):
    logs: list[str] = []
    ctx = _ctx(work_dir)
    ctx.log = logs.append
    enc_path = work_dir / "data/s3/demo/orders_encrypted.csv.pgp"
    PGPDecrypt(
        {
            "private_key_path": "fixtures/keys/demo_private.asc",
            "passphrase": "super-secret-passphrase-xyz",
            "input_path": str(enc_path),
        }
    ).run(ctx)
    joined = "\n".join(logs)
    assert "super-secret-passphrase-xyz" not in joined


def test_redact_secrets_helper():
    assert "***" in redact_secrets("password=hunter2 failed")
    assert "passphrase=***" in redact_secrets("passphrase=abc123 ok")


def test_pgp_large_file_stays_path_only(work_dir: Path):
    """>64KiB plaintext → artifacts omit content/bytes; path handle only."""
    big = work_dir / "data" / "big.csv"
    big.parent.mkdir(parents=True, exist_ok=True)
    # ~80 KiB
    body = "id,value\n" + "".join(f"{i},{'x' * 60}\n" for i in range(1200))
    assert len(body.encode()) > 64 * 1024
    big.write_text(body, encoding="utf-8")
    enc = PGPEncrypt(
        {
            "public_key_path": "fixtures/keys/demo_public.asc",
            "input_path": str(big),
            "armor": True,
        }
    ).run(_ctx(work_dir))
    assert "bytes" not in enc.artifacts
    assert Path(enc.artifacts["path"]).exists()

    dec = PGPDecrypt(
        {
            "private_key_path": "fixtures/keys/demo_private.asc",
            "input_path": enc.artifacts["path"],
        }
    ).run(_ctx(work_dir))
    # Decrypted size exceeds preview → no content in artifacts
    assert "content" not in dec.artifacts
    assert Path(dec.artifacts["path"]).read_text(encoding="utf-8").startswith("id,value")
