"""Generacion de reporte HTML autocontenido (Jinja2).

El reporte es un unico archivo HTML con CSS en linea, sin recursos externos.
"""
from __future__ import annotations

import html
import json
import math
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.config import settings
from app.models.case import Case

_TEMPLATES_DIR = Path(__file__).parent / "templates"

_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
    trim_blocks=True,
    lstrip_blocks=True,
)


def _phase_status_map(status: str) -> str:
    mapping = {
        "ok": "ok",
        "running": "running",
        "pending": "pending",
        "degraded": "degraded",
        "failed": "failed",
        "skipped": "skipped",
    }
    return mapping.get(status, "pending")


def _build_evidence_map(case: Case) -> dict[str, str]:
    """Construye un mapa de ID de evidencia -> texto descriptivo."""
    result: dict[str, str] = {}
    for ev in case.evidence or []:
        if not isinstance(ev, dict):
            continue
        eid = ev.get("id", "")
        if not eid:
            continue
        parts = []
        if ev.get("level"):
            parts.append(f"[{ev['level']}]")
        if ev.get("component"):
            parts.append(ev["component"])
        if ev.get("summary"):
            parts.append(ev["summary"])
        if ev.get("sample_line"):
            parts.append(f"\nLinea: {ev['sample_line']}")
        if ev.get("count", 1) > 1:
            parts.append(f"(x{ev['count']})")
        result[eid] = " ".join(parts) if parts else eid
    return result


def _eid_tag(eid: str, evidence_map: dict[str, str]) -> str:
    """Genera un span HTML para un ID de evidencia con tooltip."""
    if not eid:
        return ""
    tooltip = evidence_map.get(eid, eid)
    tooltip_escaped = html.escape(tooltip)
    eid_escaped = html.escape(eid)
    return (
        f'<span class="eid">{eid_escaped}'
        f'<span class="tooltip">{tooltip_escaped}</span></span>'
    )


def _masking_summary(stats: dict[str, int]) -> str:
    if not stats:
        return "Sin enmascarado"
    parts = []
    for key, val in sorted(stats.items()):
        if val > 0:
            parts.append(f"{key}: {val}")
    return ", ".join(parts) if parts else "Sin datos"


def generate_html_report(case: Case) -> str:
    """Genera el reporte HTML completo para un expediente.

    Devuelve una cadena HTML autocontenida (CSS en linea, sin recursos externos).
    """
    template = _env.get_template("report.html")

    evidence_map = _build_evidence_map(case)

    # Fases
    def phase_status(name: str) -> str:
        ph = case.phases.get(name)
        return ph.status if ph else "pending"

    def phase_class(name: str) -> str:
        return _phase_status_map(phase_status(name))

    def phase_dur(name: str) -> float:
        ph = case.phases.get(name)
        return ph.duration if ph else 0.0

    def phase_tokens(name: str) -> str:
        ph = case.phases.get(name)
        if not ph or not ph.tokens:
            return ""
        total = ph.tokens.get("total", 0)
        return str(total) if total else ""

    def degraded_text(name: str) -> str:
        ph = case.phases.get(name)
        if ph and ph.status == "degraded" and ph.error:
            return ph.error
        return ""

    def eid_tag(eid: str) -> str:
        return _eid_tag(eid, evidence_map)

    # Evidencia notable
    notable_evidence = []
    for ev in case.evidence or []:
        if isinstance(ev, dict) and ev.get("notable"):
            notable_evidence.append(ev)

    # Severidad
    severity = ""
    if case.triage:
        severity = case.triage.severity

    # Tiempo total
    total_duration = sum(
        (ph.duration if ph else 0.0) for ph in case.phases.values()
    )

    # Ticket info
    ticket_id = ""
    application = ""
    if case.ticket:
        ticket_id = case.ticket.ticket_id
        application = case.ticket.application

    # Case status class
    case_status_class = _phase_status_map(case.status) if case.status != "waiting_review" else "waiting"

    # Model
    model = settings.MAAS_MODEL or settings.LLM_MODE

    context = {
        "case": case,
        "ticket_id": ticket_id,
        "application": application,
        "severity": severity,
        "total_duration": total_duration,
        "model": model,
        "case_status_class": case_status_class,
        "notable_evidence": notable_evidence,
        "masking_summary": _masking_summary(case.masking_stats),
        "phase_status": phase_status,
        "phase_class": phase_class,
        "phase_dur": phase_dur,
        "phase_tokens": phase_tokens,
        "degraded_text": degraded_text,
        "eid_tag": eid_tag,
    }

    return template.render(**context)


def generate_json_export(case: Case) -> str:
    """Genera un JSON del expediente sin los logs originales."""
    data = case.model_dump(mode="json")
    # Remover campos internos si existen
    data.pop("_source_data", None)
    data.pop("_known_ids", None)
    return json.dumps(data, indent=2, ensure_ascii=False, default=str)
