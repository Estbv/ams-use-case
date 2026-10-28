"""Esquemas de salida de cada agente (seccion 4 de la especificacion).

Mismas claves (en ingles) y mismos valores permitidos que el FORMATO DE SALIDA
de cada agente. Un modelo Pydantic v2 por agente.
"""
from __future__ import annotations

import re
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

_EVIDENCE_ID = re.compile(r"E\d{3,}")


class AgentOutputBase(BaseModel):
    """Base con cited_ids() que escanea todo el JSON del modelo."""

    def cited_ids(self) -> set[str]:
        """Devuelve todos los IDs de evidencia citados (E001, E002, ...)."""
        text = self.model_dump_json()
        return set(_EVIDENCE_ID.findall(text))


# ---------------------------------------------------------------------------
# 4.1 IngestOutput
# ---------------------------------------------------------------------------

class EvidenceItem(BaseModel):
    id: str
    time_first: str
    time_last: str
    count: int = 1
    level: Literal["ERROR", "WARN", "INFO", "DEBUG"]
    component: str
    category: Literal[
        "error", "performance", "deployment", "configuration",
        "database", "network", "security", "health", "routine",
    ]
    summary: str
    notable: bool = False
    notable_reason: Optional[str] = None


class Trend(BaseModel):
    evidence_ids: list[str] = Field(default_factory=list)
    metric: str = ""
    direction: Literal["increasing", "decreasing", "stable"] = "stable"
    from_: str = Field("", alias="from")
    to: str = ""
    comment: str = ""

    model_config = {"populate_by_name": True}


class ResidualSensitiveData(BaseModel):
    evidence_id: str
    type: Literal["password", "token", "card", "email", "personal_data", "other"]


class TimeRange(BaseModel):
    start: str = ""
    end: str = ""


class IngestOutput(AgentOutputBase):
    source: str
    source_type: Literal["application", "database", "proxy", "os", "other"]
    detected_format: str = ""
    time_range: TimeRange = Field(default_factory=TimeRange)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    trends: list[Trend] = Field(default_factory=list)
    data_quality: list[str] = Field(default_factory=list)
    residual_sensitive_data: list[ResidualSensitiveData] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 4.2 TriageOutput
# ---------------------------------------------------------------------------

class UserImpact(BaseModel):
    affected: str = ""
    still_working: str = ""


class FirstAnomaly(BaseModel):
    time: str = ""
    evidence_id: str = ""
    description: str = ""


class FirstUserVisibleError(BaseModel):
    time: str = ""
    evidence_id: str = ""


class Theme(BaseModel):
    id: str
    title: str = ""
    classification: Literal["trigger", "symptom", "noise", "expected"]
    evidence_ids: list[str] = Field(default_factory=list)
    explanation: str = ""


class TimelineEvent(BaseModel):
    time: str = ""
    source: str = ""
    evidence_id: str = ""
    event: str = ""
    role: Literal["context", "trigger", "propagation", "impact"] = "context"


class Correlation(BaseModel):
    cause_id: str
    effect_id: str
    explanation: str = ""


class TriageOutput(AgentOutputBase):
    incident_summary: str = ""
    user_impact: UserImpact = Field(default_factory=UserImpact)
    severity: Literal["Low", "Medium", "High", "Critical"]
    severity_reason: str = ""
    first_anomaly: FirstAnomaly = Field(default_factory=FirstAnomaly)
    first_user_visible_error: Optional[FirstUserVisibleError] = None
    themes: list[Theme] = Field(default_factory=list)
    timeline: list[TimelineEvent] = Field(default_factory=list)
    correlations: list[Correlation] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 4.3 RcaOutput
# ---------------------------------------------------------------------------

class EvidenceRef(BaseModel):
    evidence_id: str
    reason: str = ""


class Hypothesis(BaseModel):
    rank: int
    title: str = ""
    confidence: Literal["High", "Medium", "Low"]
    causal_chain: list[str] = Field(default_factory=list)
    supporting_evidence: list[EvidenceRef] = Field(default_factory=list)
    contradicting_evidence: list[EvidenceRef] = Field(default_factory=list)
    known_issue: Optional[str] = None


class RuledOutItem(BaseModel):
    item: str = ""
    reason: str = ""
    evidence_id: str = ""
    known_issue: Optional[str] = None


class RejectedQuickFix(BaseModel):
    action: str = ""
    why_wrong: str = ""


class VerificationCheck(BaseModel):
    check: str = ""
    type: Literal["sql", "log_query", "console"]
    command: str = ""
    confirms_if: str = ""
    refutes_if: str = ""
    run_by: Literal["DBA", "AMS", "Desarrollo", "Infraestructura"] = "AMS"


class RcaOutput(AgentOutputBase):
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    most_likely_root_cause: str = ""
    why_misleading: str = ""
    ruled_out: list[RuledOutItem] = Field(default_factory=list)
    rejected_quick_fixes: list[RejectedQuickFix] = Field(default_factory=list)
    verification_checks: list[VerificationCheck] = Field(default_factory=list)
    information_gaps: list[str] = Field(default_factory=list)
    needs_human_review: bool = False
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_ranks(self) -> "RcaOutput":
        if self.hypotheses:
            ranks = [h.rank for h in self.hypotheses]
            expected = list(range(1, len(ranks) + 1))
            if ranks != expected:
                raise ValueError(f"ranks deben ser consecutivos desde 1, recibido {ranks}")
        return self


# ---------------------------------------------------------------------------
# 4.4 ResolutionOutput
# ---------------------------------------------------------------------------

class MitigationStep(BaseModel):
    order: int
    step: str = ""
    owner: str = ""
    risk: Literal["Low", "Medium", "High"] = "Medium"
    rollback: str = ""
    expected_effect: str = ""
    requires_change_request: bool = False
    requires_dba: bool = False
    runbook_ref: Optional[str] = None


class PermanentFix(BaseModel):
    action: str = ""
    owner: str = ""
    prevents: str = ""
    requires_change_request: bool = False


class ValidationCriterion(BaseModel):
    criterion: str = ""
    target: str = ""
    how: str = ""


class ResolutionOutput(AgentOutputBase):
    immediate_mitigation: list[MitigationStep] = Field(default_factory=list)
    permanent_fix: list[PermanentFix] = Field(default_factory=list)
    validation: list[ValidationCriterion] = Field(default_factory=list)
    risks_and_dependencies: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_orders(self) -> "ResolutionOutput":
        if self.immediate_mitigation:
            orders = [m.order for m in self.immediate_mitigation]
            expected = list(range(1, len(orders) + 1))
            if orders != expected:
                raise ValueError(f"orders deben ser consecutivos desde 1, recibido {orders}")
        return self


# ---------------------------------------------------------------------------
# 4.5 CommunicationOutput
# ---------------------------------------------------------------------------

class BusinessUpdate(BaseModel):
    text: str = ""
    next_update_at: str = ""

    @field_validator("next_update_at")
    @classmethod
    def _validate_hhmm(cls, v: str) -> str:
        if v and not re.match(r"^\d{2}:\d{2}$", v):
            raise ValueError("next_update_at debe tener formato HH:MM")
        return v


class EscalationNote(BaseModel):
    to: list[str] = Field(default_factory=list)
    text: str = ""
    requests: list[str] = Field(default_factory=list)


class RunbookEntry(BaseModel):
    title: str = ""
    symptoms: list[str] = Field(default_factory=list)
    diagnosis: list[str] = Field(default_factory=list)
    resolution: list[str] = Field(default_factory=list)
    prevention: list[str] = Field(default_factory=list)


class CommunicationOutput(AgentOutputBase):
    ticket_note: str = ""
    business_update: BusinessUpdate = Field(default_factory=BusinessUpdate)
    escalation_note: EscalationNote = Field(default_factory=EscalationNote)
    runbook_entry: RunbookEntry = Field(default_factory=RunbookEntry)
    warnings: list[str] = Field(default_factory=list)
