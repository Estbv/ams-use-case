"""Agente de Comunicacion (4.5)."""
from __future__ import annotations

import json
from typing import Any

from app.agents.base import BaseAgent, now_hhmm, ticket_to_text
from app.models.agents import CommunicationOutput
from app.models.summaries import rca_summary, triage_summary


class CommunicationAgent(BaseAgent):
    def __init__(self, client: Any = None) -> None:
        super().__init__("communication", CommunicationOutput, client)

    def build_inputs(self, case: Any, **extra: Any) -> dict[str, Any]:
        triage_resumen_json = ""
        if case and case.triage:
            triage_resumen_json = json.dumps(
                triage_summary(case.triage), ensure_ascii=False, indent=2
            )

        rca_resumen_json = ""
        if case and case.rca:
            rca_resumen_json = json.dumps(
                rca_summary(case.rca), ensure_ascii=False, indent=2
            )

        plan_json = ""
        if case and case.plan:
            plan_json = case.plan.model_dump_json(indent=2)

        return {
            "ticket_completo": ticket_to_text(case.ticket) if case else "",
            "triage_resumen_json": triage_resumen_json,
            "rca_resumen_json": rca_resumen_json,
            "plan_json": plan_json,
            "hora_actual": now_hhmm(),
        }
