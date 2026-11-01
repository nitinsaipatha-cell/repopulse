"""Prevent tests from opening real network connections."""
import socket

import pytest


@pytest.fixture(autouse=True)
def block_real_network(monkeypatch):
    attempts = []

    def blocked(*args, **kwargs):
        attempts.append(True)
        raise OSError("Real network access is prohibited in tests")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    yield
    if attempts:
        pytest.fail("A test attempted real network access")
