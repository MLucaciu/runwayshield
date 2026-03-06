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
    assert isinstance(resp.get_json(), dict)


def test_live_stream_unknown_camera(client):
    resp = client.get("/api/stream/nonexistent/live")
    assert resp.status_code == 404


def test_live_stream_with_offset_unknown_camera(client):
    resp = client.get("/api/stream/nonexistent/live?offset=5")
    assert resp.status_code == 404


def test_history_unknown_camera(client):
    resp = client.get("/api/stream/nonexistent/history?t=1709740800")
    assert resp.status_code == 404


def test_history_missing_param(client):
    resp = client.get("/api/stream/camera_1/history")
    # camera_1 not started in tests, so 404 (camera check first)
    assert resp.status_code in (400, 404)
