"""Agente de Triage (4.2)."""
from __future__ import annotations

from typing import Any

from app.agents.base import BaseAgent, evidence_to_text, ticket_to_text, trends_to_text
from app.models.agents import TriageOutput


class TriageAgent(BaseAgent):
    def __init__(self, client: Any = None) -> None:
        super().__init__("triage", TriageOutput, client)

    def build_inputs(self, case: Any, **extra: Any) -> dict[str, Any]:
        return {
            "ticket_completo": ticket_to_text(case.ticket) if case else "",
            "evidencia_fusionada": evidence_to_text(case.evidence) if case else "[]",
            "tendencias": trends_to_text(case.trends) if case else "[]",
        }
