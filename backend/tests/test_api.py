"""
Endpoint tests for the AssistedAI API. The analysis coordinator is mocked so
these exercise routing, shapes, filtering, and the key-present vs fallback
branches of /analyze without making live calls.
"""

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def test_summary_shape():
    r = client.get("/api/summary")
    assert r.status_code == 200
    d = r.json()
    assert d["total"] == 7
    assert set(d["counts"]) == {"attention", "watch", "improving", "stable"}
    assert d["facility"]["name"]


def test_patients_list_is_lightweight():
    r = client.get("/api/patients")
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 7
    for key in ("id", "name", "room", "status", "summary", "trends", "latest_note"):
        assert key in items[0]


def test_patients_filter_by_status():
    r = client.get("/api/patients", params={"status": "attention"})
    assert r.status_code == 200
    assert all(p["status"] == "attention" for p in r.json())
    assert len(r.json()) >= 1


def test_patients_search_query():
    r = client.get("/api/patients", params={"q": "margaret"})
    items = r.json()
    assert len(items) == 1 and "Margaret" in items[0]["name"]


def test_patient_detail_is_full_record():
    r = client.get("/api/patients/p-204")
    assert r.status_code == 200
    d = r.json()
    assert d["name"] == "Margaret Thompson"
    assert "notes" in d and "adl" in d and "vitals" in d


def test_patient_detail_404():
    assert client.get("/api/patients/nope").status_code == 404


def test_analyze_uses_coordinator_when_key_present(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    fake = {"conclusion": "X", "confidence": "moderate", "areas": ["behavioral"], "research": [], "simulated": False}
    with patch("main.coordinator.run", new_callable=AsyncMock) as run:
        run.return_value = fake
        r = client.post("/api/patients/p-204/analyze")
    assert r.status_code == 200
    assert r.json() == fake


def test_analyze_falls_back_when_no_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    r = client.post("/api/patients/p-204/analyze")
    assert r.status_code == 200
    d = r.json()
    assert d["simulated"] is True
    assert d["conclusion"]


def test_analyze_404():
    assert client.post("/api/patients/nope/analyze").status_code == 404


def test_root_serves_frontend():
    r = client.get("/")
    assert r.status_code == 200
    assert "AssistedAI" in r.text
