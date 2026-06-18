"""Issue #3 (security): fail-fast startup guard for insecure binds.

Exercises ``_assert_secure_bind`` / ``_resolve_bind_host`` from
``tradefarm.api.main`` directly (no socket is bound, no lifespan boots):

  (a) loopback host + empty secret      → OK.
  (b) 0.0.0.0 + empty secret            → RuntimeError.
  (c) 0.0.0.0 + secret set              → OK.

Plus coverage for the --host argv parsing and the loopback classifier.
"""

from __future__ import annotations

import pytest

from tradefarm.api.main import (
    _assert_secure_bind,
    _is_loopback_host,
    _resolve_bind_host,
)
from tradefarm.config import settings


def test_loopback_empty_secret_ok(monkeypatch):
    """(a) 127.0.0.1 + no secret is the local-dev default and must start."""
    monkeypatch.setattr(settings, "api_shared_secret", "")
    monkeypatch.setattr(settings, "api_bind_host", "127.0.0.1")
    assert _assert_secure_bind(argv=["uvicorn"]) == "127.0.0.1"


def test_non_loopback_empty_secret_raises(monkeypatch):
    """(b) 0.0.0.0 + empty secret exposes the mutating surface → refuse."""
    monkeypatch.setattr(settings, "api_shared_secret", "")
    monkeypatch.setattr(settings, "api_bind_host", "127.0.0.1")
    with pytest.raises(RuntimeError) as exc:
        _assert_secure_bind(argv=["uvicorn", "--host", "0.0.0.0"])
    assert "API_SHARED_SECRET" in str(exc.value)
    assert "0.0.0.0" in str(exc.value)


def test_non_loopback_with_secret_ok(monkeypatch):
    """(c) 0.0.0.0 + secret set is the broadcast-VM config → allowed."""
    monkeypatch.setattr(settings, "api_shared_secret", "swordfish")
    assert _assert_secure_bind(argv=["uvicorn", "--host", "0.0.0.0"]) == "0.0.0.0"


def test_lan_ip_empty_secret_raises(monkeypatch):
    """A concrete LAN IP is just as reachable as 0.0.0.0 → also guarded."""
    monkeypatch.setattr(settings, "api_shared_secret", "")
    with pytest.raises(RuntimeError):
        _assert_secure_bind(argv=["uvicorn", "--host", "192.168.1.50"])


def test_resolve_host_prefers_argv_flag(monkeypatch):
    """--host on the command line wins over the settings fallback."""
    monkeypatch.setattr(settings, "api_bind_host", "127.0.0.1")
    assert _resolve_bind_host(["uvicorn", "--host", "0.0.0.0"]) == "0.0.0.0"


def test_resolve_host_supports_equals_form(monkeypatch):
    """--host=VALUE is parsed the same as --host VALUE."""
    monkeypatch.setattr(settings, "api_bind_host", "127.0.0.1")
    assert _resolve_bind_host(["uvicorn", "--host=0.0.0.0"]) == "0.0.0.0"


def test_resolve_host_falls_back_to_setting(monkeypatch):
    """No --host flag → use settings.api_bind_host (env API_BIND_HOST)."""
    monkeypatch.setattr(settings, "api_bind_host", "0.0.0.0")
    assert _resolve_bind_host(["uvicorn", "--reload"]) == "0.0.0.0"


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1", "LOCALHOST", " ::1 "])
def test_loopback_hosts_classified_safe(host):
    assert _is_loopback_host(host) is True


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.10", "10.0.0.5", "example.com"])
def test_non_loopback_hosts_classified_unsafe(host):
    assert _is_loopback_host(host) is False
