"""Stream-control router — accept allowed types, reject unknown ones."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from tradefarm.api.stream_control import router as stream_router


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(stream_router)
    return TestClient(app)


def test_stream_cmd_accepts_known_type() -> None:
    client = _client()
    r = client.post(
        "/stream/cmd",
        json={"type": "stream_scene", "payload": {"scene_id": "hero"}},
    )
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_stream_cmd_rejects_unknown_type() -> None:
    client = _client()
    r = client.post(
        "/stream/cmd",
        json={"type": "stream_unknown", "payload": {}},
    )
    assert r.status_code == 400
