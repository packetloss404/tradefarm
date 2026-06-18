"""Issue #4 (security): CORS allow-list must be default-safe.

Exercises ``build_cors_origin_regex`` from ``tradefarm.api.main`` directly
(no app boot, no socket): the regex it produces is what CORSMiddleware uses
as ``allow_origin_regex``, so matching the compiled pattern against candidate
Origin headers is exactly the runtime allow/deny decision.

  (a) default settings              → loopback + Tauri allowed, LAN rejected.
  (b) cors_allow_lan=True           → RFC-1918 LAN origins allowed.
  (c) cors_allow_origins CSV        → explicit exact origins merged in.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from tradefarm.api.main import build_cors_origin_regex


@dataclass
class _FakeCors:
    """Minimal stand-in for Settings, only the CORS knobs the builder reads."""

    cors_allow_lan: bool = False
    cors_allow_origins: str = ""


def _matches(cfg: _FakeCors, origin: str) -> bool:
    return re.match(build_cors_origin_regex(cfg), origin) is not None


def test_default_allows_loopback_and_tauri():
    """(a) The default allow-list covers the local dev + Tauri flows."""
    cfg = _FakeCors()
    assert _matches(cfg, "http://localhost:5179")
    assert _matches(cfg, "http://localhost:5180")
    assert _matches(cfg, "http://127.0.0.1:5179")
    assert _matches(cfg, "https://localhost:5179")
    assert _matches(cfg, "http://tauri.localhost")
    assert _matches(cfg, "https://tauri.localhost")
    assert _matches(cfg, "tauri://localhost")


def test_default_rejects_lan_origins():
    """(a) RFC-1918 LAN hosts are NOT permitted on the default bind."""
    cfg = _FakeCors()
    assert not _matches(cfg, "http://10.0.0.5:8000")
    assert not _matches(cfg, "http://192.168.1.20:5179")
    assert not _matches(cfg, "http://172.16.5.9:8000")
    # And an arbitrary external origin is rejected too.
    assert not _matches(cfg, "https://evil.example.com")


def test_allow_lan_opt_in_permits_lan_origins():
    """(b) cors_allow_lan=True re-adds the RFC-1918 ranges."""
    cfg = _FakeCors(cors_allow_lan=True)
    assert _matches(cfg, "http://10.0.0.5:8000")
    assert _matches(cfg, "http://192.168.1.20:5179")
    assert _matches(cfg, "http://172.31.255.255:8000")
    # Loopback + Tauri still work with LAN enabled.
    assert _matches(cfg, "http://localhost:5179")
    assert _matches(cfg, "tauri://localhost")
    # Public origin still rejected even with LAN on.
    assert not _matches(cfg, "https://evil.example.com")


def test_explicit_origins_csv_merged():
    """(c) cors_allow_origins adds exact origins; LAN stays off."""
    cfg = _FakeCors(cors_allow_origins="https://dash.example.com, https://ops.example.net")
    assert _matches(cfg, "https://dash.example.com")
    assert _matches(cfg, "https://ops.example.net")
    # Not a substring/prefix match — the regex is anchored + escaped.
    assert not _matches(cfg, "https://dash.example.com.evil.com")
    assert not _matches(cfg, "http://10.0.0.5:8000")
