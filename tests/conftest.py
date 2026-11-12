import pytest

from dofuspetmerch import items, net
from dofuspetmerch.sheets import client


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    """Every test gets its own data folder, no network and no leftover offline back-off."""
    monkeypatch.setenv("DOFUSPETMERCH_HOME", str(tmp_path))
    attempts = []

    def no_network(req, timeout):
        attempts.append(req.full_url)
        raise OSError("network access in tests")

    monkeypatch.setattr(net, "open_url", no_network)
    items.backoff.reset()
    client.backoff.reset()
    yield tmp_path
    # Checked here because the callers swallow network errors by design.
    assert not attempts, f"unexpected network access: {attempts}"
