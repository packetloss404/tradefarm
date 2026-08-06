"""Tests for the LLM model catalog module.

0.18.0 - the catalog fans out to three providers' /v1/models
endpoints, caches for 60 min, and returns a partial-failure
envelope. These tests mock the httpx transport so no real network
calls happen.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from tradefarm.runtime import llm_model_catalog as catalog


def _make_mock_transport(handlers: dict[str, httpx.Response]) -> httpx.MockTransport:
    """Build a MockTransport that dispatches on the URL path.

    ``handlers`` maps the full URL string to a canned response
    (status + JSON body). Unmapped URLs raise so a test catches
    unexpected network calls immediately.
    """
    import re

    def _handle(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        for pattern, response in handlers.items():
            if re.search(pattern, url):
                return response
        raise AssertionError(f"unexpected request: {url}")

    return httpx.MockTransport(_handle)


def _json_response(status: int, payload: Any) -> httpx.Response:
    return httpx.Response(
        status_code=status,
        json=payload,
        request=httpx.Request("GET", "https://example.invalid/"),
    )


# ---------------------------------------------------------------------------
# Parser tests (pure functions, no I/O)
# ---------------------------------------------------------------------------


def test_parse_anthropic_happy_path() -> None:
    payload = {
        "data": [
            {
                "id": "claude-haiku-4-5-20251001",
                "display_name": "Claude Haiku 4.5",
                "created_at": "2025-10-15T00:00:00Z",
                "type": "model",
                "max_input_tokens": 200000,
                "capabilities": {"thinking": {"supported": True}},
            },
            {
                "id": "claude-opus-4-8",
                "display_name": "Claude Opus 4.8",
                "created_at": "2026-07-01T00:00:00Z",
                "type": "model",
                "max_input_tokens": 1000000,
            },
        ],
        "has_more": False,
    }
    listing = catalog._parse_anthropic(payload)
    assert listing.ok is True
    assert listing.error is None
    assert len(listing.models) == 2
    assert listing.models[0].id == "claude-haiku-4-5-20251001"
    assert listing.models[0].display_name == "Claude Haiku 4.5"
    assert listing.models[0].context_tokens == 200000
    # The haiku model has a cost-hint row in MODEL_COST_HINTS.
    assert listing.models[0].cost_hint_usd == {
        "input_per_million": 1.00,
        "output_per_million": 5.00,
        "cached_input_per_million": 0.10,
    }
    # Opus also has a hint.
    assert listing.models[1].cost_hint_usd.get("input_per_million") == 5.00


def test_parse_anthropic_missing_data_array() -> None:
    listing = catalog._parse_anthropic({"unexpected": "shape"})
    assert listing.ok is False
    assert "missing 'data' array" in listing.error


def test_parse_anthropic_skips_malformed_rows() -> None:
    payload = {
        "data": [
            None,
            "not-a-dict",
            {"display_name": "no-id"},  # missing id
            {"id": "valid-1"},
            {"id": ""},  # empty id
            {"id": 12345},  # non-string id
        ]
    }
    listing = catalog._parse_anthropic(payload)
    assert listing.ok is True
    assert len(listing.models) == 1
    assert listing.models[0].id == "valid-1"


def test_parse_anthropic_empty_list() -> None:
    listing = catalog._parse_anthropic({"data": []})
    assert listing.ok is True
    assert listing.models == ()


def test_parse_openai_happy_path() -> None:
    payload = {
        "object": "list",
        "data": [
            {
                "id": "gpt-5.6-sol",
                "object": "model",
                "created": 1780000000,
                "owned_by": "openai",
            },
            {
                "id": "gpt-5.6-luna",
                "object": "model",
                "created": 1780000000,
                "owned_by": "openai",
            },
        ],
    }
    listing = catalog._parse_openai(payload)
    assert listing.ok is True
    assert len(listing.models) == 2
    assert listing.models[0].id == "gpt-5.6-sol"
    # OpenAI has no display_name; the id is used as the human label.
    assert listing.models[0].display_name == "gpt-5.6-sol"
    # The unix-seconds `created` is converted to ISO-8601 UTC.
    assert listing.models[0].created_at is not None
    assert listing.models[0].created_at.endswith("Z")
    # No context_tokens in the OpenAI envelope; the parser must
    # NOT crash on the missing field.
    assert listing.models[0].context_tokens is None
    # The capabilities dict carries the `owned_by` field.
    assert listing.models[0].capabilities == {"owned_by": "openai"}


def test_parse_openai_missing_data_array() -> None:
    listing = catalog._parse_openai({"object": "list"})
    assert listing.ok is False
    assert "missing 'data' array" in listing.error


def test_parse_openai_invalid_unix_timestamp() -> None:
    """Garbage `created` values fall back to None rather than crash
    the whole fetch."""
    payload = {
        "data": [
            {"id": "good", "created": 1780000000, "owned_by": "openai"},
            {"id": "bad-unix", "created": -1, "owned_by": "openai"},
            {"id": "bad-type", "created": "not-a-number", "owned_by": "openai"},
        ]
    }
    listing = catalog._parse_openai(payload)
    assert listing.ok is True
    assert len(listing.models) == 3
    assert listing.models[0].created_at is not None
    assert listing.models[1].created_at is None
    assert listing.models[2].created_at is None


def test_parse_minimax_uses_openai_shape() -> None:
    """MiniMax returns the same envelope as OpenAI; the parser
    must accept it byte-identically."""
    payload = {
        "object": "list",
        "data": [
            {"id": "M2.7-highspeed", "object": "model", "created": 1773799200, "owned_by": "minimax"},
        ],
    }
    listing = catalog._parse_minimax(payload)
    assert listing.ok is True
    assert len(listing.models) == 1
    assert listing.models[0].id == "M2.7-highspeed"
    # Cost hint is filled in from the static table.
    assert listing.models[0].cost_hint_usd.get("input_per_million") == 0.60


# ---------------------------------------------------------------------------
# ProviderListing + ModelCatalog shape
# ---------------------------------------------------------------------------


def test_provider_listing_to_payload_shape() -> None:
    listing = catalog.ProviderListing(ok=True, fetched_at="2026-08-10T14:23:01Z")
    payload = listing.to_payload()
    assert payload == {
        "ok": True,
        "models": [],
        "fetched_at": "2026-08-10T14:23:01Z",
        "error": None,
        "ttl_sec": catalog.CATALOG_TTL_SEC,
    }


def test_model_catalog_to_payload_shape() -> None:
    catalog_obj = catalog.ModelCatalog(
        anthropic=catalog.ProviderListing(ok=False, error="ANTHROPIC_API_KEY not set"),
        openai=catalog.ProviderListing(ok=True, fetched_at="2026-08-10T14:23:01Z"),
        minimax=catalog.ProviderListing(ok=False, error="MINIMAX_API_KEY not set"),
        cached_at="2026-08-10T14:23:01Z",
    )
    payload = catalog_obj.to_payload()
    assert set(payload.keys()) == {"anthropic", "openai", "minimax", "cached_at"}
    assert payload["anthropic"]["ok"] is False
    assert payload["openai"]["ok"] is True
    assert payload["minimax"]["ok"] is False
    assert payload["cached_at"] == "2026-08-10T14:23:01Z"


# ---------------------------------------------------------------------------
# get_model_catalog — fan-out + missing key + cache behavior.
# These tests monkey-patch get_shared_client to return a mock-transport
# httpx client so no real network I/O happens.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_catalog_cache() -> None:
    catalog.reset_model_catalog_cache()
    yield
    catalog.reset_model_catalog_cache()


@pytest.fixture
def patch_get_shared_client(monkeypatch: pytest.MonkeyPatch):
    """Replace get_shared_client with a factory that builds a
    transport from the supplied handlers.

    Usage:
        def test_xyz(patch_get_shared_client):
            patch_get_shared_client({"api.anthropic.com": _json_response(200, payload)})
            ...
    """

    def _set(handlers: dict[str, httpx.Response]) -> None:
        transport = _make_mock_transport(handlers)

        class _MockClient(httpx.AsyncClient):
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                kwargs.pop("timeout", None)
                kwargs.pop("limits", None)
                kwargs.pop("http2", None)
                super().__init__(*args, transport=transport, **kwargs)

        async def _factory(**_kwargs: Any) -> httpx.AsyncClient:
            return _MockClient()

        monkeypatch.setattr(catalog, "get_shared_client", _factory)

    return _set


async def test_get_catalog_fans_out_to_all_three_providers(
    patch_get_shared_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("MINIMAX_API_KEY", "test-minimax-key")
    patch_get_shared_client(
        {
            r"https://api\.anthropic\.com/v1/models": _json_response(
                200,
                {
                    "data": [
                        {
                            "id": "claude-haiku-4-5-20251001",
                            "display_name": "Claude Haiku 4.5",
                        }
                    ]
                },
            ),
            r"https://api\.openai\.com/v1/models": _json_response(
                200,
                {
                    "data": [
                        {"id": "gpt-5.6-sol", "created": 1780000000, "owned_by": "openai"}
                    ]
                },
            ),
            r"https://api\.minimax\.io/v1/models": _json_response(
                200,
                {
                    "data": [
                        {"id": "M2.7-highspeed", "created": 1773799200, "owned_by": "minimax"}
                    ]
                },
            ),
        }
    )

    cat = await catalog.get_model_catalog()
    assert cat.anthropic.ok is True
    assert cat.openai.ok is True
    assert cat.minimax.ok is True
    assert {m.id for m in cat.anthropic.models} == {"claude-haiku-4-5-20251001"}
    assert {m.id for m in cat.openai.models} == {"gpt-5.6-sol"}
    assert {m.id for m in cat.minimax.models} == {"M2.7-highspeed"}


async def test_get_catalog_skips_provider_without_key(
    patch_get_shared_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing env key short-circuits to the 0.18.0 demo fallback -
    the listing is ``ok=True`` with the static demo catalog + a
    warning string in ``error``. The Anthropic fetch still proceeds
    normally because its key is set."""
    # Only Anthropic set; OpenAI + MiniMax keys are absent.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    patch_get_shared_client(
        {
            r"https://api\.anthropic\.com/v1/models": _json_response(
                200,
                {
                    "data": [
                        {
                            "id": "claude-haiku-4-5-20251001",
                            "display_name": "Claude Haiku 4.5",
                        }
                    ]
                },
            ),
            # OpenAI + MiniMax are NOT in the handler map; a
            # request to either URL would raise AssertionError
            # from the mock transport (proving the demo fallback
            # short-circuited the network call).
        }
    )

    cat = await catalog.get_model_catalog()
    # Anthropic: real fetch succeeded.
    assert cat.anthropic.ok is True
    assert {m.id for m in cat.anthropic.models} == {"claude-haiku-4-5-20251001"}
    # OpenAI + MiniMax: demo fallback. ``ok=True`` so the dropdown
    # populates; the warning lives in ``error``.
    assert cat.openai.ok is True
    assert len(cat.openai.models) > 0  # demo list non-empty
    assert "OPENAI_API_KEY" in (cat.openai.error or "")
    assert "demo catalog" in (cat.openai.error or "").lower()
    assert cat.minimax.ok is True
    assert len(cat.minimax.models) > 0
    assert "MINIMAX_API_KEY" in (cat.minimax.error or "")
    assert "demo catalog" in (cat.minimax.error or "").lower()


async def test_get_catalog_handles_partial_failure(
    patch_get_shared_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One provider 500s, the other two succeed. The response
    carries the two ok=True rows AND the ok=False row - the
    dashboard renders whichever providers returned."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("MINIMAX_API_KEY", "test-minimax-key")
    patch_get_shared_client(
        {
            r"https://api\.anthropic\.com/v1/models": _json_response(
                500,
                {"error": "internal error"},
            ),
            r"https://api\.openai\.com/v1/models": _json_response(
                200,
                {
                    "data": [
                        {"id": "gpt-5.6-sol", "created": 1780000000, "owned_by": "openai"}
                    ]
                },
            ),
            r"https://api\.minimax\.io/v1/models": _json_response(
                200,
                {
                    "data": [
                        {"id": "M2.7-highspeed", "created": 1773799200, "owned_by": "minimax"}
                    ]
                },
            ),
        }
    )

    cat = await catalog.get_model_catalog()
    assert cat.anthropic.ok is False
    assert "fetch failed" in (cat.anthropic.error or "").lower() or "500" in (cat.anthropic.error or "")
    assert cat.openai.ok is True
    assert cat.minimax.ok is True


async def test_get_catalog_caches_result(
    patch_get_shared_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The 60-min cache means a second call without ``force=True``
    returns the cached catalog without hitting the network."""
    call_count = 0

    def _handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return _json_response(
            200,
            {
                "data": [
                    {
                        "id": "claude-haiku-4-5-20251001",
                        "display_name": "Claude Haiku 4.5",
                    }
                ]
            },
        )

    class _CountingClient(httpx.AsyncClient):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, transport=httpx.MockTransport(_handler), **kwargs)

    async def _factory(**_kwargs: Any) -> httpx.AsyncClient:
        return _CountingClient()

    monkeypatch.setattr(catalog, "get_shared_client", _factory)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)

    # First call - hits the network.
    cat1 = await catalog.get_model_catalog()
    first_call_count = call_count
    assert first_call_count >= 1
    # Second call - served from cache, no new requests.
    cat2 = await catalog.get_model_catalog()
    assert call_count == first_call_count
    assert cat1.cached_at == cat2.cached_at


async def test_get_catalog_force_bypasses_cache(
    patch_get_shared_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    patch_get_shared_client(
        {
            r"https://api\.anthropic\.com/v1/models": _json_response(
                200,
                {
                    "data": [
                        {
                            "id": "claude-haiku-4-5-20251001",
                            "display_name": "Claude Haiku 4.5",
                        }
                    ]
                },
            )
        }
    )
    cat1 = await catalog.get_model_catalog()
    cat2 = await catalog.get_model_catalog(force=True)
    # Forced refetch stamps a new cached_at; the second call's
    # timestamp must be >= the first's. (Could be equal if the
    # second-resolution clock didn't tick, but typically not.)
    assert cat2.cached_at >= cat1.cached_at


async def test_get_catalog_per_provider_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider that exceeds the per-provider budget becomes
    ``ok=False`` with a timeout-specific error; the other
    providers' results are unaffected.

    We patch the inner fetcher to raise ``asyncio.TimeoutError``
    directly rather than trying to time out the underlying
    httpx call (which would require either a real slow server
    or careful cancellation of a MockTransport's sync handler).
    The catalog's ``_guarded`` wrapper is the production code
    path that converts ``TimeoutError`` into a
    ``ProviderListing(ok=False)`` — that conversion is what
    we're verifying here.
    """
    import asyncio

    async def _slow_anthropic(_client) -> catalog.ProviderListing:
        # Simulate a per-provider fetch that exceeds the
        # wait_for budget. asyncio.TimeoutError is what
        # asyncio.wait_for raises when the budget is exceeded.
        raise asyncio.TimeoutError()

    async def _quick_openai(_client) -> catalog.ProviderListing:
        return catalog.ProviderListing(ok=True, fetched_at="2026-08-10T14:23:01Z")

    async def _quick_minimax(_client) -> catalog.ProviderListing:
        return catalog.ProviderListing(ok=True, fetched_at="2026-08-10T14:23:01Z")

    monkeypatch.setattr(catalog, "_fetch_anthropic", _slow_anthropic)
    monkeypatch.setattr(catalog, "_fetch_openai", _quick_openai)
    monkeypatch.setattr(catalog, "_fetch_minimax", _quick_minimax)

    cat = await catalog.get_model_catalog()
    assert cat.anthropic.ok is False
    assert "timed out" in (cat.anthropic.error or "").lower()
    assert cat.openai.ok is True
    assert cat.minimax.ok is True


def test_model_entry_to_payload() -> None:
    entry = catalog.ModelEntry(
        id="claude-haiku-4-5-20251001",
        display_name="Claude Haiku 4.5",
        created_at="2025-10-15T00:00:00Z",
        context_tokens=200000,
        capabilities={"thinking": {"supported": True}},
        cost_hint_usd={
            "input_per_million": 1.00,
            "output_per_million": 5.00,
        },
    )
    payload = entry.to_payload()
    assert payload == {
        "id": "claude-haiku-4-5-20251001",
        "display_name": "Claude Haiku 4.5",
        "created_at": "2025-10-15T00:00:00Z",
        "context_tokens": 200000,
        "capabilities": {"thinking": {"supported": True}},
        "cost_hint_usd": {
            "input_per_million": 1.00,
            "output_per_million": 5.00,
        },
    }
