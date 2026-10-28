"""Agente de Resolucion (4.4)."""
from __future__ import annotations

from typing import Any

from app.agents.base import BaseAgent, ticket_to_text
from app.models.agents import ResolutionOutput
from app.models.summaries import triage_summary


class ResolutionAgent(BaseAgent):
    def __init__(self, client: Any = None) -> None:
        super().__init__("resolution", ResolutionOutput, client)

    def build_inputs(self, case: Any, **extra: Any) -> dict[str, Any]:
        triage_resumen_json = ""
        if case and case.triage:
            triage_resumen_json = _dump(triage_summary(case.triage))

        rca_json = ""
        if case and case.rca:
            rca_json = case.rca.model_dump_json(indent=2)

        return {
            "ticket_completo": ticket_to_text(case.ticket) if case else "",
            "triage_resumen_json": triage_resumen_json,
            "rca_json": rca_json,
        }


def _dump(obj: dict) -> str:
    import json
    return json.dumps(obj, ensure_ascii=False, indent=2)
