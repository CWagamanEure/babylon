"""Central configuration, loaded from environment / `.env`.

All settings are prefixed with ``BABYLON_`` and validated at startup so the
system fails fast on misconfiguration rather than mid-trade.
"""

from __future__ import annotations

import re
from enum import StrEnum
from pathlib import Path

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_ADDR_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
_KEY_RE = re.compile(r"^0x[0-9a-fA-F]{64}$")


class Network(StrEnum):
    MAINNET = "mainnet"
    TESTNET = "testnet"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BABYLON_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    network: Network = Network.TESTNET
    account_address: str = ""
    # SecretStr so the key never leaks via repr, model_dump, or log formatting.
    secret_key: SecretStr = SecretStr("")
    data_dir: Path = Path("./data")
    log_level: str = "INFO"
    log_console: bool = True

    @field_validator("account_address")
    @classmethod
    def _check_address(cls, v: str) -> str:
        v = v.strip()
        if v and not _ADDR_RE.match(v):
            raise ValueError("account_address must be a 0x-prefixed 40-hex address")
        return v

    @field_validator("secret_key")
    @classmethod
    def _check_secret(cls, v: SecretStr) -> SecretStr:
        raw = v.get_secret_value().strip()
        if raw and not _KEY_RE.match(raw):
            raise ValueError("secret_key must be a 0x-prefixed 64-hex (32-byte) key")
        return SecretStr(raw)

    @model_validator(mode="after")
    def _check_trading_pair(self) -> Settings:
        # A signing key with no account address is a half-configured trading
        # setup — account queries would fail at runtime. Fail fast instead.
        if self.secret_key.get_secret_value() and not self.account_address:
            raise ValueError("secret_key is set but account_address is empty")
        return self

    @property
    def can_trade(self) -> bool:
        """True when a signing key is configured (vs data-only mode)."""
        return bool(self.secret_key.get_secret_value())

    @property
    def is_mainnet(self) -> bool:
        return self.network is Network.MAINNET


_settings: Settings | None = None


def get_settings() -> Settings:
    """Process-wide singleton so config is parsed once."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
