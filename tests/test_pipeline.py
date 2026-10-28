"""Pruebas del orquestador (paso 6) con FakeClient."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from app.config import settings
from app.llm.fake_client import FakeClient
from app.models.ticket import Ticket
from app.orchestrator.pipeline import Pipeline, ProgressEvent
from app.orchestrator.store import load_case

SAMPLE_DIR = Path("samples/checkout-incident")


# ---------------------------------------------------------------------------
# Fixtures validas para cada agente
# ---------------------------------------------------------------------------

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

RCA_NEEDS_REVIEW = json.dumps({
    "hypotheses": [{"rank": 1, "title": "h", "confidence": "Low",
                    "causal_chain": ["[E001]"], "supporting_evidence": [{"evidence_id": "E001", "reason": "r"}],
                    "contradicting_evidence": [], "known_issue": None}],
    "most_likely_root_cause": "test cause", "why_misleading": "test",
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
    "ticket_note": "test", "business_update": {"text": "t", "next_update_at": "15:00"},
    "escalation_note": {"to": [], "text": "t", "requests": []},
    "runbook_entry": {"title": "t", "symptoms": [], "diagnosis": [], "resolution": [], "prevention": []},
    "warnings": [],
})

TOKENS = {"prompt": 10, "completion": 20, "total": 30}


def _full_client() -> FakeClient:
    """FakeClient con respuestas validas para todo el flujo."""
    return FakeClient(responses=[
        {"content": INGEST_OK, "tokens": TOKENS},  # ingest fuente 1
        {"content": INGEST_OK, "tokens": TOKENS},  # ingest fuente 2
        {"content": INGEST_OK, "tokens": TOKENS},  # ingest fuente 3
        {"content": TRIAGE_OK, "tokens": TOKENS},  # triage
        {"content": RCA_OK, "tokens": TOKENS},     # rca
        {"content": RESOLUTION_OK, "tokens": TOKENS},  # resolution
        {"content": COMM_OK, "tokens": TOKENS},    # communication
    ])


def _ticket() -> Ticket:
    return Ticket(
        ticket_id="INC-TEST", application="checkout-service",
        description="Checkout falla", recent_changes="release 2.14.0",
    )


def _log_files() -> list[Path]:
    return sorted(SAMPLE_DIR.glob("*.log"))


# ---------------------------------------------------------------------------
# 1. El flujo completo termina en completed y todas las fases en ok
# ---------------------------------------------------------------------------

def test_full_pipeline_completed(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "CASES_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "LLM_MODE", "fake")

    client = _full_client()
    pipeline = Pipeline(client=client)
    case = pipeline.run("TEST-001", _log_files(), _ticket())

    assert case.status == "completed"
    for name in ("preprocess", "ingest", "triage", "rca", "resolution", "communication"):
        assert case.phases[name].status == "ok", f"fase {name} = {case.phases[name].status}"


# ---------------------------------------------------------------------------
# 2. La ingesta se ejecuta en paralelo (se solapan en el tiempo)
# ---------------------------------------------------------------------------

def test_ingest_parallel(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "CASES_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "LLM_MODE", "fake")

    call_times: list[tuple[str, float]] = []

    class SlowFakeClient(FakeClient):
        def chat(self, messages, tools=None):
            system = ""
            for m in messages:
                if m.get("role") == "system":
                    system = m.get("content", "")
                    break
            if "Ingesta" in system:
                call_times.append(("start", time.time()))
                time.sleep(0.3)
                call_times.append(("end", time.time()))
            return super().chat(messages, tools)

    client = SlowFakeClient(responses=[
        {"content": INGEST_OK, "tokens": TOKENS} for _ in range(3)
    ] + [
        {"content": TRIAGE_OK, "tokens": TOKENS},
        {"content": RCA_OK, "tokens": TOKENS},
        {"content": RESOLUTION_OK, "tokens": TOKENS},
        {"content": COMM_OK, "tokens": TOKENS},
    ])

    pipeline = Pipeline(client=client)
    case = pipeline.run("TEST-PAR", _log_files(), _ticket())

    # Si se ejecutan en paralelo, los starts ocurren antes de los ends
    starts = [t for label, t in call_times if label == "start"]
    ends = [t for label, t in call_times if label == "end"]
    if len(starts) >= 2 and len(ends) >= 2:
        # El segundo start debe ser antes del primer end (solapamiento)
        assert starts[1] < ends[0], "la ingesta no se solapo en el tiempo"


# ---------------------------------------------------------------------------
# 3. needs_human_review + HUMAN_REVIEW=pause -> waiting_review, resume completa
# ---------------------------------------------------------------------------

def test_human_review_pause_and_resume(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "CASES_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "LLM_MODE", "fake")
    monkeypatch.setattr(settings, "HUMAN_REVIEW", "pause")

    client = FakeClient(responses=[
        {"content": INGEST_OK, "tokens": TOKENS} for _ in range(3)
    ] + [
        {"content": TRIAGE_OK, "tokens": TOKENS},
        {"content": RCA_NEEDS_REVIEW, "tokens": TOKENS},
        {"content": RESOLUTION_OK, "tokens": TOKENS},
        {"content": COMM_OK, "tokens": TOKENS},
    ])

    pipeline = Pipeline(client=client)
    case = pipeline.run("TEST-REV", _log_files(), _ticket())

    assert case.status == "waiting_review"
    assert case.phases["rca"].status == "ok"

    # Resume
    case2 = pipeline.resume("TEST-REV", approved=True, comment="aprobado por DBA")
    assert case2.status == "completed"
    assert case2.phases["resolution"].status == "ok"
    assert case2.phases["communication"].status == "ok"


# ---------------------------------------------------------------------------
# 4. Respuesta invalida dos veces en Triage -> degraded, el flujo sigue
# ---------------------------------------------------------------------------

def test_triage_degraded_continues(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "CASES_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "LLM_MODE", "fake")

    client = FakeClient(responses=[
        {"content": INGEST_OK, "tokens": TOKENS} for _ in range(3)
    ] + [
        {"content": "invalid1", "tokens": TOKENS},  # triage intent 1
        {"content": "invalid2", "tokens": TOKENS},  # triage intent 2 (degraded)
        {"content": RCA_OK, "tokens": TOKENS},
        {"content": RESOLUTION_OK, "tokens": TOKENS},
        {"content": COMM_OK, "tokens": TOKENS},
    ])

    pipeline = Pipeline(client=client)
    case = pipeline.run("TEST-DEG", _log_files(), _ticket())

    assert case.phases["triage"].status == "degraded"
    assert case.status == "completed"
    assert case.phases["rca"].status == "ok"
