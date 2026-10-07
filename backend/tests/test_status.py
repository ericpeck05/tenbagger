def test_status_reports_health_without_leaking_keys(client, monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("FINNHUB_API_KEY", "not-a-real-key")
    get_settings.cache_clear()
    res = client.get("/api/status")
    assert res.status_code == 200
    body = res.json()
    assert body["database"]["ok"] is True
    assert body["keys"]["finnhub"] is True
    assert "not-a-real-key" not in res.text
