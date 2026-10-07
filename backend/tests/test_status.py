from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app


def test_status_reports_health_without_leaking_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("FINNHUB_API_KEY", "not-a-real-key")
    get_settings.cache_clear()
    import app.db.session as session

    monkeypatch.setattr(session, "_engine", None)

    res = TestClient(create_app()).get("/api/status")

    assert res.status_code == 200
    body = res.json()
    assert body["database"]["ok"] is True
    assert body["keys"]["finnhub"] is True
    assert "not-a-real-key" not in res.text
    get_settings.cache_clear()
