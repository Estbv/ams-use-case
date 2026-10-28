"""Funciones para generar resumenes que reciben los agentes posteriores.

Segun la tabla de la seccion 1:
- triage_summary(triage): incident_summary, user_impact, severity, first_anomaly.
- rca_summary(rca): most_likely_root_cause, confianza de la hipotesis 1, ruled_out.
"""
from __future__ import annotations

from app.models.agents import RcaOutput, TriageOutput


def triage_summary(triage: TriageOutput) -> dict:
    """Resumen del triage para los agentes de Resolucion y Comunicacion."""
    return {
        "incident_summary": triage.incident_summary,
        "user_impact": triage.user_impact.model_dump(),
        "severity": triage.severity,
        "first_anomaly": triage.first_anomaly.model_dump(),
    }


def rca_summary(rca: RcaOutput) -> dict:
    """Resumen de la causa raiz para el agente de Comunicacion."""
    top_confidence = ""
    if rca.hypotheses:
        top_confidence = rca.hypotheses[0].confidence

    return {
        "most_likely_root_cause": rca.most_likely_root_cause,
        "top_hypothesis_confidence": top_confidence,
        "needs_human_review": rca.needs_human_review,
        "ruled_out": [item.model_dump() for item in rca.ruled_out],
    }
