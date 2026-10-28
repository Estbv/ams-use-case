"""Paso 3 - Modelos de datos: esquemas de agentes, expediente y ticket."""
from app.models.ticket import Ticket
from app.models.agents import (
    AgentOutputBase,
    IngestOutput,
    TriageOutput,
    RcaOutput,
    ResolutionOutput,
    CommunicationOutput,
)
from app.models.case import Case, PhaseState, AuditRecord
from app.models.summaries import triage_summary, rca_summary

__all__ = [
    "Ticket",
    "AgentOutputBase",
    "IngestOutput",
    "TriageOutput",
    "RcaOutput",
    "ResolutionOutput",
    "CommunicationOutput",
    "Case",
    "PhaseState",
    "AuditRecord",
    "triage_summary",
    "rca_summary",
]
