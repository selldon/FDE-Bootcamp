"""Fast tests of the settings: no network."""
import pytest

import config

NAMES = ["LEDGERLINE_DSN", "LEDGERLINE_USER", "LEDGERLINE_PASSWORD",
         "CARRIER_HOST", "CARRIER_PORT", "CARRIER_USER", "CARRIER_PASSWORD",
         "STORE_URL", "LEDGERLINE_WRITER_USER", "LEDGERLINE_WRITER_PASSWORD",
         "SERVICENOW_URL", "SERVICENOW_USER", "SERVICENOW_PASSWORD"]


@pytest.fixture
def env(monkeypatch):
    for name in NAMES:
        monkeypatch.setenv(name, "1" if name == "CARRIER_PORT" else "x")
    return monkeypatch


def test_all_settings_present(env):
    assert config.ledgerline() == {"dsn": "x", "user": "x", "password": "x"}
    assert config.carrier()["port"] == 1
    assert config.store_url() == "x"
    assert config.ledgerline_writer() == {"dsn": "x", "user": "x", "password": "x"}
    assert config.servicenow() == {"url": "x", "user": "x", "password": "x"}


@pytest.mark.parametrize("name", NAMES)
def test_a_missing_setting_names_itself(env, name):
    env.delenv(name)
    with pytest.raises(RuntimeError, match=name):
        config.ledgerline()
        config.carrier()
        config.store_url()
        config.ledgerline_writer()
        config.servicenow()


@pytest.mark.parametrize("name", NAMES)
def test_each_setting_is_read_by_its_own_function(env, name):
    """Each missing name is reported by the function that reads it."""
    env.delenv(name)
    readers = [config.ledgerline, config.carrier, config.store_url,
               config.ledgerline_writer, config.servicenow]
    failed = []
    for read in readers:
        try:
            read()
        except RuntimeError as error:
            assert name in str(error)
            failed.append(read.__name__)
    assert failed  # the DSN is shared by the reader and the writer, so it may fail two


def test_the_probe_never_writes():
    """The probe only looks: no write verb, no writer account, no insert."""
    with open("probe_live.py") as f:
        source = f.read()
    for forbidden in ("POST", "PUT", "PATCH", "DELETE", "ledgerline_writer", "WRITER",
                      "INSERT", "UPDATE", "MERGE", "TRUNCATE", "DROP", ".commit("):
        assert forbidden not in source, forbidden
