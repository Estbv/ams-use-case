"""Expediente del incidente (seccion 1 de la especificacion).

Objeto JSON unico que se va completando fase a fase.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from app.models.agents import (
    CommunicationOutput,
    IngestOutput,
    RcaOutput,
    ResolutionOutput,
    TriageOutput,
)
from app.models.ticket import Ticket


PhaseStatus = Literal["pending", "running", "ok", "degraded", "failed", "skipped"]
CaseStatus = Literal["created", "running", "waiting_review", "completed", "failed"]


class PhaseState(BaseModel):
    """Estado de una fase del flujo."""

    status: PhaseStatus = "pending"
    duration: float = 0.0
    tokens: dict[str, int] = Field(default_factory=dict)
    attempts: int = 0
    error: Optional[str] = None


class AuditRecord(BaseModel):
    """Registro de auditoria de una llamada al modelo."""

    agent: str = ""
    phase: str = ""
    messages_sent: list[str] = Field(default_factory=list)
    responses: list[str] = Field(default_factory=list)
    attempts: int = 0
    tokens: dict[str, int] = Field(default_factory=dict)
    duration: float = 0.0
    warnings: list[str] = Field(default_factory=list)
    timestamp: Optional[str] = None


class Case(BaseModel):
    """Expediente del incidente."""

    id: str
    created_at: datetime = Field(default_factory=datetime.now)
    status: CaseStatus = "created"

    ticket: Optional[Ticket] = None
    sources: list[str] = Field(default_factory=list)
    evidence: list[dict] = Field(default_factory=list)
    trends: list[dict] = Field(default_factory=list)
    masking_stats: dict[str, int] = Field(default_factory=dict)

    triage: Optional[TriageOutput] = None
    rca: Optional[RcaOutput] = None
    plan: Optional[ResolutionOutput] = None
    communications: Optional[CommunicationOutput] = None

    phases: dict[str, PhaseState] = Field(default_factory=dict)
    audit: list[AuditRecord] = Field(default_factory=list)

    def init_phases(self) -> None:
        """Inicializa las fases del flujo."""
        for name in ("preprocess", "ingest", "triage", "rca", "resolution", "communication"):
            if name not in self.phases:
                self.phases[name] = PhaseState()

    def add_audit(self, record: AuditRecord) -> None:
        self.audit.append(record)

    def set_phase(self, name: str, status: PhaseStatus, **kwargs: Any) -> None:
        self.init_phases()
        phase = self.phases[name]
        phase.status = status
        for k, v in kwargs.items():
            if hasattr(phase, k):
                setattr(phase, k, v)
