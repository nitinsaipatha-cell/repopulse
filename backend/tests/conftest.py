"""Prevent tests from opening real network connections."""
import socket
import sys

import pytest

# On Windows, asyncio builds its internal socket pair through a loopback connection.
ALLOWED = {"127.0.0.1", "::1"} if sys.platform == "win32" else set()
real_connect = socket.socket.connect
real_connect_ex = socket.socket.connect_ex


@pytest.fixture(autouse=True)
def block_real_network(monkeypatch):
    attempts = []

    def guard(real):
        def connect(self, address, *args, **kwargs):
            if isinstance(address, tuple) and address[0] in ALLOWED:
                return real(self, address, *args, **kwargs)
            attempts.append(True)
            raise OSError("Real network access is prohibited in tests")
        return connect

    monkeypatch.setattr(socket.socket, "connect", guard(real_connect))
    monkeypatch.setattr(socket.socket, "connect_ex", guard(real_connect_ex))
    yield
    if attempts:
        pytest.fail("A test attempted real network access")
