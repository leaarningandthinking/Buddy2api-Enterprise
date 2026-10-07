import asyncio

import pytest

import credential_crypto
import database as db
import auth_manager


@pytest.fixture()
def isolated_db(tmp_path, monkeypatch):
    path = tmp_path / "gateway.db"
    monkeypatch.setattr(db, "DB_PATH", path)
    monkeypatch.setenv("CB_GATEWAY_MASTER_KEY", "pytest-master-key")
    credential_crypto.reset_cache()
    db.init_db()
    yield path
    credential_crypto.reset_cache()


def test_default_registry_enables_wave1_channels(monkeypatch):
    import providers

    monkeypatch.delenv("CB_GATEWAY_PROVIDERS", raising=False)
    assert providers.enabled_provider_ids() == ["workbuddy", "qclaw", "qwenwork", "traework"]
    monkeypatch.setenv("CB_GATEWAY_PROVIDERS", "workbuddy")
    assert providers.enabled_provider_ids() == ["workbuddy"]
    assert providers.get_provider("qclaw") is None


def test_accounts_and_keys_have_channel_columns(isolated_db):
    account_id = db.add_account({"name": "wb", "uid": "u1", "access_token": "a"})
    account = db.get_account(account_id)
    assert account["provider"] == "workbuddy"
    key_id = db.add_api_key("sk-cb-test-channel", "k")
    keys = db.list_api_keys()
    row = next(item for item in keys if item["id"] == key_id)
    assert row["default_channel"] == "workbuddy"


def test_second_import_same_uid_updates_token(isolated_db):
    first = db.add_account(
        {"name": "wb", "uid": "same", "provider": "workbuddy", "access_token": "old", "weight": 3}
    )
    db.update_account(first, {"access_token": "new", "uid": "same"})
    rows = db.list_accounts(provider="workbuddy")
    assert len(rows) == 1
    assert rows[0]["access_token"] == "new"
    assert rows[0]["weight"] == 3


def test_workbuddy_pick_ignores_other_provider_expired(isolated_db, monkeypatch):
    wb = db.add_account(
        {
            "name": "wb",
            "uid": "wb-1",
            "provider": "workbuddy",
            "status": "active",
            "access_token": "ok",
            "expires_at": 9_999_999_999_999,
        }
    )
    db.add_account(
        {
            "name": "qw",
            "uid": "qw-1",
            "provider": "qwenwork",
            "status": "expired",
            "access_token": "qw-token",
            "refresh_token": "qw-refresh",
        }
    )
    refreshed = []

    async def fake_refresh(account):
        refreshed.append(account.get("provider"))
        return True

    monkeypatch.setattr(auth_manager, "refresh_token", fake_refresh)
    picked = auth_manager.pick_account(provider="workbuddy")
    assert picked["id"] == wb
    asyncio.run(auth_manager.pick_account_with_fallback(provider="workbuddy"))
    assert "qwenwork" not in refreshed
