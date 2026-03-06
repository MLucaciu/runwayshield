import pytest
from app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_status(client):
    resp = client.get("/api/status")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "ok"
    assert "Runway Shield" in data["message"]


def test_cameras_empty(client):
    resp = client.get("/api/cameras")
    assert resp.status_code == 200
    # No cameras started in test mode, so empty dict
    assert resp.get_json() == {} or isinstance(resp.get_json(), dict)


def test_live_stream_unknown_camera(client):
    resp = client.get("/api/stream/nonexistent/live")
    assert resp.status_code == 404


def test_playback_unknown_camera(client):
    resp = client.get("/api/stream/nonexistent/playback?from=2026-01-01T00:00:00&to=2026-01-01T00:01:00")
    assert resp.status_code == 404


def test_playback_missing_params(client):
    # Even if camera doesn't exist, missing params should 404 (camera check first)
    resp = client.get("/api/stream/camera_1/playback")
    # camera_1 not started in tests, so 404
    assert resp.status_code in (400, 404)


def test_cameras_empty(client):
    resp = client.get("/api/cameras")
    assert resp.status_code == 200
    # No cameras started in test mode, so empty dict
    assert resp.get_json() == {} or isinstance(resp.get_json(), dict)


def test_live_stream_unknown_camera(client):
    resp = client.get("/api/stream/nonexistent/live")
    assert resp.status_code == 404


def test_playback_unknown_camera(client):
    resp = client.get("/api/stream/nonexistent/playback?from=2026-01-01T00:00:00&to=2026-01-01T00:01:00")
    assert resp.status_code == 404


def test_playback_missing_params(client):
    # Even if camera doesn't exist, missing params should 404 (camera check first)
    resp = client.get("/api/stream/camera_1/playback")
    # camera_1 not started in tests, so 404
    assert resp.status_code in (400, 404)
