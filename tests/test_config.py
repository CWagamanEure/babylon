import pytest
from pydantic import ValidationError

from babylon.config import Network, Settings

ADDR = "0x" + "a" * 40
KEY = "0x" + "b" * 64


def _settings(**kw):
    # _env_file=None so the developer's real .env never bleeds into tests.
    return Settings(_env_file=None, **kw)


def test_defaults_are_testnet_data_only():
    s = _settings()
    assert s.network is Network.TESTNET
    assert not s.can_trade


def test_secret_key_is_not_in_repr_or_dump():
    s = _settings(account_address=ADDR, secret_key=KEY)
    assert KEY not in repr(s)
    assert KEY not in str(s.model_dump())
    assert s.secret_key.get_secret_value() == KEY  # still retrievable at the boundary


def test_bad_address_rejected():
    with pytest.raises(ValidationError):
        _settings(account_address="0x123")


def test_bad_secret_key_rejected():
    with pytest.raises(ValidationError):
        _settings(account_address=ADDR, secret_key="not-a-key")


def test_key_without_address_rejected():
    with pytest.raises(ValidationError):
        _settings(secret_key=KEY)


def test_can_trade_when_fully_configured():
    s = _settings(network="mainnet", account_address=ADDR, secret_key=KEY)
    assert s.can_trade and s.is_mainnet
