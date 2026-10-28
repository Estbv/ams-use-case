"""Pruebas de los modelos de datos (paso 3)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.models.agents import (
    CommunicationOutput,
    IngestOutput,
    RcaOutput,
    ResolutionOutput,
    TriageOutput,
)
from app.models.case import Case
from app.models.summaries import rca_summary, triage_summary
from app.models.ticket import Ticket

FIXTURES = Path("tests/fixtures/fake_responses")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_first_response(agent: str) -> str:
    """Carga el content del primer response valido del fixture."""
    data = json.loads((FIXTURES / f"{agent}.json").read_text(encoding="utf-8"))
    for resp in data["responses"]:
        if resp["content"] and resp["content"].startswith("{"):
            return resp["content"]
    raise ValueError(f"no hay response valido para {agent}")


# ---------------------------------------------------------------------------
# 1. Un ejemplo valido de cada agente pasa la validacion
# ---------------------------------------------------------------------------

class TestValidExamples:
    def test_ingest(self) -> None:
        content = _load_first_response("ingest")
        obj = IngestOutput.model_validate_json(content)
        assert obj.source == "checkout-service"

    def test_triage(self) -> None:
        content = _load_first_response("triage")
        obj = TriageOutput.model_validate_json(content)
        assert obj.severity == "Critical"

    def test_root_cause(self) -> None:
        content = _load_first_response("root_cause")
        obj = RcaOutput.model_validate_json(content)
        assert obj.hypotheses[0].rank == 1

    def test_resolution(self) -> None:
        content = _load_first_response("resolution")
        obj = ResolutionOutput.model_validate_json(content)
        assert obj.immediate_mitigation[0].order == 1

    def test_communication(self) -> None:
        content = _load_first_response("communication")
        obj = CommunicationOutput.model_validate_json(content)
        assert obj.business_update.next_update_at == "14:40"


# ---------------------------------------------------------------------------
# 2. Valores invalidos fallan con error claro
# ---------------------------------------------------------------------------

class TestInvalidValues:
    def test_invalid_severity(self) -> None:
        content = _load_first_response("triage")
        data = json.loads(content)
        data["severity"] = "Urgente"
        with pytest.raises(ValidationError) as exc_info:
            TriageOutput.model_validate(data)
        assert "severity" in str(exc_info.value)

    def test_invalid_classification(self) -> None:
        content = _load_first_response("triage")
        data = json.loads(content)
        data["themes"][0]["classification"] = "bug"
        with pytest.raises(ValidationError) as exc_info:
            TriageOutput.model_validate(data)
        assert "classification" in str(exc_info.value)

    def test_invalid_confidence(self) -> None:
        content = _load_first_response("root_cause")
        data = json.loads(content)
        data["hypotheses"][0]["confidence"] = "Maybe"
        with pytest.raises(ValidationError) as exc_info:
            RcaOutput.model_validate(data)
        assert "confidence" in str(exc_info.value)

    def test_invalid_next_update_at(self) -> None:
        content = _load_first_response("communication")
        data = json.loads(content)
        data["business_update"]["next_update_at"] = "14:40:00"
        with pytest.raises(ValidationError) as exc_info:
            CommunicationOutput.model_validate(data)
        assert "next_update_at" in str(exc_info.value)

    def test_non_consecutive_ranks(self) -> None:
        content = _load_first_response("root_cause")
        data = json.loads(content)
        data["hypotheses"].append({
            "rank": 3, "title": "otra", "confidence": "Low",
            "causal_chain": [], "supporting_evidence": [],
            "contradicting_evidence": [], "known_issue": None,
        })
        with pytest.raises(ValidationError) as exc_info:
            RcaOutput.model_validate(data)
        assert "consecutivos" in str(exc_info.value)

    def test_non_consecutive_orders(self) -> None:
        content = _load_first_response("resolution")
        data = json.loads(content)
        data["immediate_mitigation"].append({
            "order": 5, "step": "otro", "owner": "AMS", "risk": "Low",
            "rollback": "n/a", "expected_effect": "n/a",
            "requires_change_request": False, "requires_dba": False, "runbook_ref": None,
        })
        with pytest.raises(ValidationError) as exc_info:
            ResolutionOutput.model_validate(data)
        assert "consecutivos" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 3. cited_ids() devuelve los IDs correctos
# ---------------------------------------------------------------------------

class TestCitedIds:
    def test_triage_cited_ids(self) -> None:
        content = _load_first_response("triage")
        obj = TriageOutput.model_validate_json(content)
        ids = obj.cited_ids()
        assert "E011" in ids  # first_anomaly.evidence_id
        assert "E026" in ids  # first_user_visible_error.evidence_id + correlations.effect_id

    def test_rca_cited_ids_from_text(self) -> None:
        content = _load_first_response("root_cause")
        obj = RcaOutput.model_validate_json(content)
        ids = obj.cited_ids()
        assert "E011" in ids  # supporting_evidence + causal_chain [E011]
        assert "E026" in ids  # causal_chain [E026]
        assert "E021" in ids  # ruled_out.evidence_id

    def test_ingest_cited_ids(self) -> None:
        content = _load_first_response("ingest")
        obj = IngestOutput.model_validate_json(content)
        ids = obj.cited_ids()
        assert "E001" in ids  # evidence[0].id


# ---------------------------------------------------------------------------
# 4. Case y Ticket
# ---------------------------------------------------------------------------

class TestCaseAndTicket:
    def test_ticket(self) -> None:
        t = Ticket(
            ticket_id="INC-2026-10482",
            application="checkout-service",
            description="Checkout falla",
        )
        assert t.ticket_id == "INC-2026-10482"

    def test_case_init_phases(self) -> None:
        c = Case(id="CASE-001")
        c.init_phases()
        assert c.phases["preprocess"].status == "pending"
        assert c.phases["communication"].status == "pending"

    def test_case_set_phase(self) -> None:
        c = Case(id="CASE-001")
        c.set_phase("triage", "ok", duration=1.5, tokens={"total": 300})
        assert c.phases["triage"].status == "ok"
        assert c.phases["triage"].duration == 1.5


# ---------------------------------------------------------------------------
# 5. Summaries
# ---------------------------------------------------------------------------

class TestSummaries:
    def test_triage_summary(self) -> None:
        content = _load_first_response("triage")
        triage = TriageOutput.model_validate_json(content)
        s = triage_summary(triage)
        assert s["severity"] == "Critical"
        assert "incident_summary" in s
        assert "first_anomaly" in s

    def test_rca_summary(self) -> None:
        content = _load_first_response("root_cause")
        rca = RcaOutput.model_validate_json(content)
        s = rca_summary(rca)
        assert s["top_hypothesis_confidence"] == "High"
        assert "most_likely_root_cause" in s
        assert len(s["ruled_out"]) == 1
