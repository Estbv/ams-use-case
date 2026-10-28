"""Pruebas de la API REST (paso 7) con TestClient de FastAPI y FakeClient."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from app import main
from app.config import settings
from app.llm.fake_client import FakeClient

try:
    from fastapi.testclient import TestClient
except ImportError:
    TestClient = None

SAMPLE_DIR = Path("samples/checkout-incident")

INGEST_OK = json.dumps({
    "source": "test", "source_type": "application", "detected_format": "test",
    "time_range": {"start": "2026-10-20 13:00:00", "end": "2026-10-20 14:00:00"},
    "evidence": [{"id": "E001", "time_first": "13:00", "time_last": "13:00", "count": 1,
                  "level": "ERROR", "component": "test", "category": "error",
                  "summary": "test error", "notable": True, "notable_reason": None}],
    "trends": [], "data_quality": [], "residual_sensitive_data": [], "warnings": [],
})

TRIAGE_OK = json.dumps({
    "incident_summary": "Test incident", "user_impact": {"affected": "a", "still_working": "b"},
    "severity": "High", "severity_reason": "test",
    "first_anomaly": {"time": "13:00", "evidence_id": "E001", "description": "d"},
    "first_user_visible_error": {"time": "13:00", "evidence_id": "E001"},
    "themes": [{"id": "T1", "title": "t", "classification": "trigger",
                "evidence_ids": ["E001"], "explanation": "e"}],
    "timeline": [{"time": "13:00", "source": "s", "evidence_id": "E001", "event": "e", "role": "trigger"}],
    "correlations": [], "warnings": [],
})

RCA_OK = json.dumps({
    "hypotheses": [{"rank": 1, "title": "h", "confidence": "High",
                    "causal_chain": ["[E001]"], "supporting_evidence": [{"evidence_id": "E001", "reason": "r"}],
                    "contradicting_evidence": [], "known_issue": None}],
    "most_likely_root_cause": "test cause", "why_misleading": "test",
    "ruled_out": [], "rejected_quick_fixes": [], "verification_checks": [],
    "information_gaps": [], "needs_human_review": False, "warnings": [],
})

RCA_REVIEW = json.dumps({
    "hypotheses": [{"rank": 1, "title": "hypo", "confidence": "Low",
                    "causal_chain": ["[E001]"], "supporting_evidence": [{"evidence_id": "E001", "reason": "r"}],
                    "contradicting_evidence": [], "known_issue": None}],
    "most_likely_root_cause": "probable cause", "why_misleading": "test",
    "ruled_out": [], "rejected_quick_fixes": [], "verification_checks": [],
    "information_gaps": ["info"], "needs_human_review": True, "warnings": [],
})

RESOLUTION_OK = json.dumps({
    "immediate_mitigation": [{"order": 1, "step": "s", "owner": "AMS", "risk": "Low",
                              "rollback": "r", "expected_effect": "e",
                              "requires_change_request": False, "requires_dba": False, "runbook_ref": None}],
    "permanent_fix": [], "validation": [], "risks_and_dependencies": [], "warnings": [],
})

COMM_OK = json.dumps({
    "ticket_note": "test note", "business_update": {"text": "t", "next_update_at": "15:00"},
    "escalation_note": {"to": [], "text": "t", "requests": []},
    "runbook_entry": {"title": "t", "symptoms": [], "diagnosis": [], "resolution": [], "prevention": []},
    "warnings": [],
})

TOKENS = {"prompt": 10, "completion": 20, "total": 30}


def _full_client() -> FakeClient:
    return FakeClient(responses=[
        {"content": INGEST_OK, "tokens": TOKENS} for _ in range(3)
    ] + [
        {"content": TRIAGE_OK, "tokens": TOKENS},
        {"content": RCA_OK, "tokens": TOKENS},
        {"content": RESOLUTION_OK, "tokens": TOKENS},
        {"content": COMM_OK, "tokens": TOKENS},
    ])


def _review_client() -> FakeClient:
    return FakeClient(responses=[
        {"content": INGEST_OK, "tokens": TOKENS} for _ in range(3)
    ] + [
        {"content": TRIAGE_OK, "tokens": TOKENS},
        {"content": RCA_REVIEW, "tokens": TOKENS},
        {"content": RESOLUTION_OK, "tokens": TOKENS},
        {"content": COMM_OK, "tokens": TOKENS},
    ])


def _log_files() -> list[tuple[str, bytes, str]]:
    result = []
    for f in sorted(SAMPLE_DIR.glob("*.log")):
        result.append(("files", (f.name, f.read_bytes(), "text/plain")))
    return result


def _wait_for_status(client, case_id, target, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = client.get(f"/cases/{case_id}")
        if resp.status_code == 200:
            data = resp.json()
            if data["status"] in target:
                return data
        time.sleep(0.3)
    return None


pytestmark = pytest.mark.skipif(TestClient is None, reason="TestClient requiere httpx")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "CASES_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "LLM_MODE", "fake")
    monkeypatch.setattr(main, "_client_override", _full_client())
    yield TestClient(main.app)
    for tid, t in list(main._running_threads.items()):
        t.join(timeout=10)
        main._running_threads.pop(tid, None)
    main._event_queues.clear()


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# Index
# ---------------------------------------------------------------------------

def test_index(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "AMS Agentes" in resp.text


# ---------------------------------------------------------------------------
# Create case
# ---------------------------------------------------------------------------

def test_create_case(client):
    files = _log_files()
    resp = client.post("/cases", files=files, data={
        "ticket_id": "INC-TEST",
        "application": "checkout-service",
        "description": "test",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert "case_id" in data
    assert data["status"] == "created"
    assert data["log_count"] == 4


def test_create_case_no_files(client):
    resp = client.post("/cases", files=[], data={
        "ticket_id": "INC-TEST",
        "application": "checkout-service",
    })
    assert resp.status_code in (400, 422)
    assert "error" in resp.json() or "detail" in resp.json()


def test_create_case_no_ticket(client):
    files = _log_files()
    resp = client.post("/cases", files=files, data={})
    assert resp.status_code == 400
    assert "error" in resp.json()


# ---------------------------------------------------------------------------
# Run case
# ---------------------------------------------------------------------------

def test_run_case_completed(client):
    files = _log_files()
    resp = client.post("/cases", files=files, data={
        "ticket_id": "INC-TEST",
        "application": "checkout-service",
        "description": "test",
    })
    case_id = resp.json()["case_id"]

    resp = client.post(f"/cases/{case_id}/run")
    assert resp.status_code == 202

    data = _wait_for_status(client, case_id, {"completed", "failed"}, timeout=30)
    assert data is not None, "timeout esperando completar"
    assert data["status"] == "completed"
    for phase in ["preprocess", "ingest", "triage", "rca", "resolution", "communication"]:
        assert data["phases"][phase]["status"] == "ok", f"fase {phase} = {data['phases'][phase]['status']}"


def test_run_case_not_found(client):
    resp = client.post("/cases/NO-EXIST/run")
    assert resp.status_code == 404


def test_run_case_duplicate(client):
    files = _log_files()
    resp = client.post("/cases", files=files, data={
        "ticket_id": "INC-TEST",
        "application": "checkout-service",
    })
    case_id = resp.json()["case_id"]
    client.post(f"/cases/{case_id}/run")
    resp = client.post(f"/cases/{case_id}/run")
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Get case
# ---------------------------------------------------------------------------

def test_get_case(client):
    files = _log_files()
    resp = client.post("/cases", files=files, data={
        "ticket_id": "INC-TEST",
        "application": "checkout-service",
    })
    case_id = resp.json()["case_id"]

    resp = client.get(f"/cases/{case_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["case_id"] == case_id
    assert data["status"] == "created"
    assert "phases" in data


def test_get_case_not_found(client):
    resp = client.get("/cases/NO-EXIST")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def test_report(client):
    files = _log_files()
    resp = client.post("/cases", files=files, data={
        "ticket_id": "INC-TEST",
        "application": "checkout-service",
        "description": "test incident",
    })
    case_id = resp.json()["case_id"]
    client.post(f"/cases/{case_id}/run")
    _wait_for_status(client, case_id, {"completed", "failed"}, timeout=30)

    resp = client.get(f"/cases/{case_id}/report")
    assert resp.status_code == 200
    assert "<html" in resp.text.lower()
    assert "INC-TEST" in resp.text
    assert "test cause" in resp.text


def test_report_not_found(client):
    resp = client.get("/cases/NO-EXIST/report")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def test_export(client):
    files = _log_files()
    resp = client.post("/cases", files=files, data={
        "ticket_id": "INC-TEST",
        "application": "checkout-service",
    })
    case_id = resp.json()["case_id"]
    client.post(f"/cases/{case_id}/run")
    _wait_for_status(client, case_id, {"completed", "failed"}, timeout=30)

    resp = client.get(f"/cases/{case_id}/export")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == case_id
    assert "ticket" in data
    assert "phases" in data


def test_export_not_found(client):
    resp = client.get("/cases/NO-EXIST/export")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Review
# ---------------------------------------------------------------------------

@pytest.fixture
def review_client(tmp_path, monkeypatch):
    for tid, t in list(main._running_threads.items()):
        t.join(timeout=10)
        main._running_threads.pop(tid, None)
    main._event_queues.clear()
    main._stop_requested.clear()

    monkeypatch.setattr(settings, "CASES_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "LLM_MODE", "fake")
    monkeypatch.setattr(settings, "HUMAN_REVIEW", "pause")
    monkeypatch.setattr(main, "_client_override", _review_client())
    yield TestClient(main.app)
    for tid, t in list(main._running_threads.items()):
        t.join(timeout=10)
        main._running_threads.pop(tid, None)
    main._event_queues.clear()


def test_review_approve(review_client):
    c = review_client

    files = _log_files()
    resp = c.post("/cases", files=files, data={
        "ticket_id": "INC-REVIEW",
        "application": "checkout-service",
    })
    case_id = resp.json()["case_id"]
    c.post(f"/cases/{case_id}/run")

    data = _wait_for_status(c, case_id, {"waiting_review", "completed", "failed"}, timeout=30)
    assert data is not None
    assert data["status"] == "waiting_review"

    resp = c.post(f"/cases/{case_id}/review", data={"approved": "true", "comment": "ok"})
    assert resp.status_code == 202

    data = _wait_for_status(c, case_id, {"completed", "failed"}, timeout=30)
    assert data is not None
    assert data["status"] == "completed"


def test_review_reject(review_client):
    c = review_client

    files = _log_files()
    resp = c.post("/cases", files=files, data={
        "ticket_id": "INC-REJECT",
        "application": "checkout-service",
    })
    case_id = resp.json()["case_id"]
    c.post(f"/cases/{case_id}/run")
    _wait_for_status(c, case_id, {"waiting_review"}, timeout=30)

    resp = c.post(f"/cases/{case_id}/review", data={"approved": "false", "comment": "no"})
    assert resp.status_code == 202

    data = _wait_for_status(c, case_id, {"completed", "failed"}, timeout=30)
    assert data is not None
    assert data["status"] == "failed"


def test_review_wrong_status(client):
    files = _log_files()
    resp = client.post("/cases", files=files, data={
        "ticket_id": "INC-X",
        "application": "checkout-service",
    })
    case_id = resp.json()["case_id"]
    resp = client.post(f"/cases/{case_id}/review", data={"approved": "true"})
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# List cases
# ---------------------------------------------------------------------------

def test_list_cases(client):
    files = _log_files()
    client.post("/cases", files=files, data={
        "ticket_id": "INC-LIST",
        "application": "checkout-service",
    })
    resp = client.get("/cases")
    assert resp.status_code == 200
    data = resp.json()
    assert "cases" in data
    assert len(data["cases"]) >= 1


# ---------------------------------------------------------------------------
# Error format
# ---------------------------------------------------------------------------

def test_error_format(client):
    resp = client.get("/cases/NO-EXIST")
    body = resp.json()
    assert "error" in body
    assert "detail" in body
