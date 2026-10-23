"""Fast tests of the settings: no network."""
import pytest

import config

NAMES = ["LEDGERLINE_DSN", "LEDGERLINE_USER", "LEDGERLINE_PASSWORD",
         "CARRIER_HOST", "CARRIER_PORT", "CARRIER_USER", "CARRIER_PASSWORD",
         "STORE_URL"]


@pytest.fixture
def env(monkeypatch):
    for name in NAMES:
        monkeypatch.setenv(name, "1" if name == "CARRIER_PORT" else "x")
    return monkeypatch


def test_all_settings_present(env):
    assert config.ledgerline() == {"dsn": "x", "user": "x", "password": "x"}
    assert config.carrier()["port"] == 1
    assert config.store_url() == "x"


@pytest.mark.parametrize("name", NAMES)
def test_a_missing_setting_names_itself(env, name):
    env.delenv(name)
    with pytest.raises(RuntimeError, match=name):
        config.ledgerline()
        config.carrier()
        config.store_url()
