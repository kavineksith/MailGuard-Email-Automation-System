import os

import pytest

from core.config import ConfigManager, SMTPConfig
from core.exceptions import (
    ConfigDecryptionError,
    ConfigNotFoundError,
    ConfigValidationError,
    MissingPassphraseError,
)


VALID_DATA = {
    "smtp_server": "smtp.example.com",
    "smtp_port": 587,
    "smtp_username": "user",
    "smtp_password": "secret",
    "default_sender": "noreply@example.com",
}


def test_smtp_config_from_dict_success():
    cfg = SMTPConfig.from_dict(VALID_DATA)
    assert cfg.smtp_server == "smtp.example.com"
    assert cfg.smtp_port == 587


def test_smtp_config_missing_key_raises():
    bad = dict(VALID_DATA)
    del bad["smtp_password"]
    with pytest.raises(ConfigValidationError):
        SMTPConfig.from_dict(bad)


def test_smtp_config_invalid_port_raises():
    bad = dict(VALID_DATA, smtp_port=70000)
    with pytest.raises(ConfigValidationError):
        SMTPConfig.from_dict(bad)


def test_smtp_config_repr_redacts_password():
    cfg = SMTPConfig.from_dict(VALID_DATA)
    assert "secret" not in repr(cfg)
    assert "redacted" in repr(cfg)


@pytest.mark.asyncio
async def test_save_and_load_round_trip(tmp_path):
    config_path = tmp_path / "config.json.enc"
    salt_path = tmp_path / "config.salt"
    manager = ConfigManager(str(config_path), str(salt_path))

    await manager.save(VALID_DATA)
    assert config_path.exists()
    assert salt_path.exists()

    fresh_manager = ConfigManager(str(config_path), str(salt_path))
    loaded = await fresh_manager.load()
    assert loaded.smtp_server == VALID_DATA["smtp_server"]
    assert loaded.smtp_username == VALID_DATA["smtp_username"]


@pytest.mark.asyncio
async def test_load_missing_file_raises(tmp_path):
    manager = ConfigManager(str(tmp_path / "nope.enc"), str(tmp_path / "salt"))
    with pytest.raises(ConfigNotFoundError):
        await manager.load()


@pytest.mark.asyncio
async def test_wrong_passphrase_raises_decryption_error(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json.enc"
    salt_path = tmp_path / "config.salt"
    manager = ConfigManager(str(config_path), str(salt_path))
    await manager.save(VALID_DATA)

    monkeypatch.setenv("MAILGUARD_PASSPHRASE", "wrong-passphrase")
    other_manager = ConfigManager(str(config_path), str(salt_path))
    with pytest.raises(ConfigDecryptionError):
        await other_manager.load()


@pytest.mark.asyncio
async def test_missing_passphrase_raises(tmp_path, monkeypatch):
    monkeypatch.delenv("MAILGUARD_PASSPHRASE", raising=False)
    manager = ConfigManager(str(tmp_path / "c.enc"), str(tmp_path / "s"))
    with pytest.raises(MissingPassphraseError):
        await manager.save(VALID_DATA)


@pytest.mark.asyncio
async def test_backup_created_on_overwrite(tmp_path):
    config_path = tmp_path / "config.json.enc"
    salt_path = tmp_path / "config.salt"
    manager = ConfigManager(str(config_path), str(salt_path))
    await manager.save(VALID_DATA)
    await manager.save(dict(VALID_DATA, smtp_port=2525))

    backups = list(tmp_path.glob("config.json.enc.bak_*"))
    assert len(backups) == 1
