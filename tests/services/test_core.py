from __future__ import annotations

from pathlib import Path

import pytest

from hopshift.services.audit import AuditLog
from hopshift.services.db import Database
from hopshift.services.platform import Platform
from hopshift.services.secrets import SecretBox, SecretsUnavailable, mask_values, redact_mapping
from hopshift.services.settings import SettingsError, SettingsStore


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "platform.sqlite")
    database.migrate()
    return database


def test_secret_box_roundtrip_and_rotation(monkeypatch: pytest.MonkeyPatch) -> None:
    old_key, new_key = SecretBox.generate_key(), SecretBox.generate_key()
    monkeypatch.setenv("HOPSHIFT_SECRET_KEY", old_key)
    box = SecretBox.from_env()
    token = box.encrypt_json({"secret_access_key": "abc"})

    monkeypatch.setenv("HOPSHIFT_SECRET_KEY", f"{new_key},{old_key}")
    rotated_box = SecretBox.from_env()
    assert rotated_box.decrypt_json(token) == {"secret_access_key": "abc"}
    rotated = rotated_box.rotate(token)
    assert SecretBox([new_key]).decrypt_json(rotated) == {"secret_access_key": "abc"}
    with pytest.raises(SecretsUnavailable):
        SecretBox([old_key]).decrypt_json(rotated)


def test_secret_box_unavailable_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HOPSHIFT_SECRET_KEY", raising=False)
    box = SecretBox.from_env()
    assert not box.available
    with pytest.raises(SecretsUnavailable, match="HOPSHIFT_SECRET_KEY"):
        box.encrypt_json({"x": 1})


def test_masking_and_redaction() -> None:
    assert mask_values("key=abcd1234 other", ["abcd1234"]) == "key=*** other"
    assert redact_mapping({"client_secret": "s3cret", "region": "eu-west-1", "nested": {"password": "p"}}) == {
        "client_secret": "***", "region": "eu-west-1", "nested": {"password": "***"},
    }


def test_audit_chain_detects_tampering(db: Database) -> None:
    log = AuditLog(db)
    log.record("run.created", actor="alice", actor_kind="user", target_type="run", target_id="r1")
    log.record("run.approved", actor="alice", actor_kind="user", target_type="run", target_id="r1", details={"pause_point": "review_cim"})
    entries, total = log.list()
    assert total == 2 and entries[0].action == "run.approved" and entries[1].prev_hash == "0" * 64
    assert log.verify().ok

    with db.connect() as conn:
        conn.execute("UPDATE audit_log SET actor = 'mallory' WHERE id = 1")
    verification = log.verify()
    assert not verification.ok and verification.broken_at == 1


def test_audit_prune_reanchors_chain(db: Database) -> None:
    log = AuditLog(db)
    first = log.record("a")
    log.record("b")
    removed = log.prune_before("9999-01-01T00:00:00")  # removes both, then records the prune itself
    assert removed == 2
    assert log.verify().ok
    entries, total = log.list()
    assert total == 1 and entries[0].action == "audit.pruned" and entries[0].id > first.id


def test_settings_overlay_validation_and_apply(db: Database) -> None:
    store = SettingsStore(db)
    base = {"generation": {"mode": "deterministic"}, "security": {"auth": {"session_hours": 12}}}
    store.update({"generation.mode": "hybrid", "security.auth.session_hours": "24"}, actor="admin")
    effective = store.apply(base)
    assert effective["generation"]["mode"] == "hybrid" and effective["security"]["auth"]["session_hours"] == 24
    assert base["generation"]["mode"] == "deterministic"  # base untouched

    with pytest.raises(SettingsError):
        store.update({"generation.mode": "magic"}, actor="admin")
    with pytest.raises(SettingsError):
        store.update({"llm.api_key": "nope"}, actor="admin")
    with pytest.raises(SettingsError):
        store.update({"security.auth.session_hours": 10_000}, actor="admin")

    store.update({"generation.mode": None}, actor="admin")
    assert "generation.mode" not in store.overrides()


def test_platform_from_config_wires_services(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOPSHIFT_SECRET_KEY", SecretBox.generate_key())
    platform = Platform.from_config({"runtime": {"platform_db": str(tmp_path / "p.sqlite")}})
    assert platform.secrets.available
    assert "audit_log" in platform.db.table_names() and "settings" in platform.db.table_names()
    platform.audit.record("platform.started")
    assert platform.audit.verify().ok
    assert platform.auth_mode in {"required", "disabled"}


def test_secret_box_rejects_an_invalid_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOPSHIFT_SECRET_KEY", "not-a-fernet-key")
    with pytest.raises(SecretsUnavailable, match="valid Fernet key"):
        SecretBox.from_env()
