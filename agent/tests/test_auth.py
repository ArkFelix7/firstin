"""Hosted-mode settings: shared-password auth, CORS extension, public API URL, TTS fallback chain."""
import pytest
from fastapi.testclient import TestClient

CODE = "engine12-s3cret"


@pytest.fixture()
def client(sandbox):
    from agent.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture()
def auth_on(monkeypatch):
    monkeypatch.setenv("FIRSTIN_ACCESS_CODE", CODE)


def test_auth_off_by_default(client, monkeypatch):
    monkeypatch.delenv("FIRSTIN_ACCESS_CODE", raising=False)
    assert client.get("/buildings").status_code == 200
    assert client.get("/incab/active").status_code == 404  # no plan yet, but not 401
    monkeypatch.setenv("FIRSTIN_ACCESS_CODE", "   ")  # blank = off
    assert client.get("/buildings").status_code == 200


def test_auth_required(client, auth_on):
    r = client.get("/buildings")
    assert r.status_code == 401
    assert r.headers["www-authenticate"].startswith("Basic")
    # cross-origin fetch: 401 without the browser-popup header
    assert "www-authenticate" not in client.get("/buildings", headers={"Origin": "http://localhost:3000"}).headers
    assert client.post("/preplan", json={"building_id": "test-001"}).status_code == 401
    assert client.get("/buildings", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/buildings", headers={"Authorization": f"Bearer {CODE}x"}).status_code == 401
    assert client.get("/buildings", auth=("crew", "wrong")).status_code == 401


def test_health_and_preflight_open(client, auth_on):
    assert client.get("/health").status_code == 200
    r = client.options("/preplan", headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST"})
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_bearer_and_basic(client, auth_on):
    assert client.get("/buildings", headers={"Authorization": f"Bearer {CODE}"}).status_code == 200
    # Basic: any username, password = access code
    assert client.get("/buildings", auth=("anyone", CODE)).status_code == 200
    assert client.get("/buildings", auth=("", CODE)).status_code == 200
    assert client.get("/buildings", headers={"Authorization": "Basic !!notbase64"}).status_code == 401


def test_key_param_only_on_media_and_stream(client, auth_on):
    # ?key= works where headers can't be sent (EventSource, <audio>, <img>)
    assert client.get(f"/incab/active?key={CODE}").status_code == 404  # authorised; no approved plan yet
    assert client.get(f"/stream/nope?key={CODE}").status_code == 404  # authorised; unknown run
    assert client.get(f"/static/out/missing.mp3?key={CODE}").status_code == 404
    assert client.get("/static/out/missing.mp3").status_code == 401
    assert client.get("/stream/nope?key=nope").status_code == 401
    # ...but not on regular API routes
    assert client.get(f"/buildings?key={CODE}").status_code == 401


def test_full_flow_with_auth(client, auth_on):
    h = {"Authorization": f"Bearer {CODE}"}
    rid = client.post("/preplan", json={"building_id": "test-001", "notify": False}, headers=h).json()["run_id"]
    with client.stream("GET", f"/stream/{rid}?key={CODE}") as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        for line in r.iter_lines():
            if line.startswith("data:"):
                break


def test_cors_and_public_url(monkeypatch):
    from starlette.requests import Request

    from agent import config, main

    monkeypatch.setenv("FIRSTIN_CORS_ORIGINS", "https://firstin.vercel.app/, https://x.example ,")
    assert config.cors_origins() == ["https://firstin.vercel.app", "https://x.example"]
    monkeypatch.delenv("FIRSTIN_CORS_ORIGINS")
    assert config.cors_origins() == []

    req = Request({"type": "http", "scheme": "http", "server": ("127.0.0.1", 8000), "path": "/", "headers": [],
                   "query_string": b""})
    monkeypatch.delenv("FIRSTIN_PUBLIC_API_URL", raising=False)
    assert main._abs(req, "/static/out/a/brief.mp3") == "http://127.0.0.1:8000/static/out/a/brief.mp3"
    monkeypatch.setenv("FIRSTIN_PUBLIC_API_URL", "https://api.example.com/")
    assert main._abs(req, "/static/out/a/brief.mp3") == "https://api.example.com/static/out/a/brief.mp3"
    assert main._abs(req, "https://cdn/x.mp3") == "https://cdn/x.mp3"


def test_tts_fallback_chain(tmp_path, monkeypatch):
    from agent.tools import render

    used = []

    def fake(name, ok):
        def eng(text, out):
            used.append(name)
            if not ok:
                return None
            p = out.with_suffix(".wav")
            p.write_bytes(b"RIFF")
            return p
        return eng

    monkeypatch.setattr(render, "_to_mp3", lambda src, out: src)
    monkeypatch.setattr(render, "TTS_ENGINES", (("say", fake("say", False)), ("piper", fake("piper", False)),
                                                ("espeak-ng", fake("espeak-ng", True)), ("pico2wave", fake("pico2wave", True))))
    got = render.tts_brief("Four stories. FDC on the north side.", str(tmp_path / "brief.mp3"))
    assert got and got.endswith("brief.wav")
    assert used == ["say", "piper", "espeak-ng"]

    # nothing available: keep a pre-rendered brief, else None
    monkeypatch.setattr(render, "TTS_ENGINES", (("say", fake("say", False)),))
    (tmp_path / "brief.wav").unlink()
    assert render.tts_brief("x", str(tmp_path / "brief.mp3")) is None
    (tmp_path / "brief.mp3").write_bytes(b"ID3")
    assert render.tts_brief("x", str(tmp_path / "brief.mp3")) == str(tmp_path / "brief.mp3")
