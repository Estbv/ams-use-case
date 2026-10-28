"""Agente de Causa Raiz (4.3)."""
from __future__ import annotations

from typing import Any

from app.agents.base import BaseAgent, evidence_to_text, ticket_to_text
from app.models.agents import RcaOutput


class RcaAgent(BaseAgent):
    def __init__(self, client: Any = None) -> None:
        super().__init__("root_cause", RcaOutput, client)

    def build_inputs(self, case: Any, **extra: Any) -> dict[str, Any]:
        triage_json = ""
        if case and case.triage:
            triage_json = case.triage.model_dump_json(indent=2)

        return {
            "ticket_completo": ticket_to_text(case.ticket) if case else "",
            "triage_json": triage_json,
            "evidencia_fusionada": evidence_to_text(case.evidence) if case else "[]",
        }
