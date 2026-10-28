"""Registro de tools por agente + executor + preload (plan B).

Tabla de la seccion 1:
  Triage        -> get_evidence_detail
  Causa Raiz    -> search_known_issues, get_evidence_detail, get_recent_changes
  Resolucion    -> search_runbooks, get_change_calendar
  Ingesta       -> ninguna
  Comunicacion  -> ninguna
"""
from __future__ import annotations

import json
import re
from typing import Any

from app.logging_config import get_logger
from app.tools.base import Tool
from app.tools.calendar import GetChangeCalendar
from app.tools.changes import GetRecentChanges
from app.tools.evidence import GetEvidenceDetail
from app.tools.known_issues import SearchKnownIssues
from app.tools.runbooks import SearchRunbooks

logger = get_logger(__name__)

MAX_RESPONSE_CHARS = 8000

# Instancias singleton
_TOOLS: dict[str, Tool] = {
    "get_evidence_detail": GetEvidenceDetail(),
    "search_known_issues": SearchKnownIssues(),
    "get_recent_changes": GetRecentChanges(),
    "search_runbooks": SearchRunbooks(),
    "get_change_calendar": GetChangeCalendar(),
}

# Registro por agente
TOOLS_BY_AGENT: dict[str, list[str]] = {
    "ingest": [],
    "triage": ["get_evidence_detail"],
    "root_cause": ["search_known_issues", "get_evidence_detail", "get_recent_changes"],
    "resolution": ["search_runbooks", "get_change_calendar"],
    "communication": [],
}


def get_tools(agent: str) -> list[Tool]:
    """Devuelve las instancias de Tool para un agente."""
    return [_TOOLS[name] for name in TOOLS_BY_AGENT.get(agent, [])]


def get_openai_tools(agent: str) -> list[dict]:
    """Esquemas OpenAI function calling para un agente."""
    return [t.to_openai_schema() for t in get_tools(agent)]


def executor(tool_name: str, args: str | dict, case: Any = None) -> str:
    """Ejecuta una tool por nombre. Devuelve JSON string.

    Valida argumentos, ejecuta, limita el tamano de la respuesta
    y nunca lanza excepcion: devuelve {"error": ...} en su lugar.
    """
    tool = _TOOLS.get(tool_name)
    if tool is None:
        return json.dumps({"error": f"tool desconocida: {tool_name}"})

    # Parsear args si vienen como string
    if isinstance(args, str):
        try:
            parsed_args = json.loads(args)
        except json.JSONDecodeError:
            return json.dumps({"error": f"argumentos no son JSON valido: {args}"})
    else:
        parsed_args = args

    try:
        result = tool.run(parsed_args, case)
    except Exception as exc:
        logger.warning("Tool %s fallo: %s", tool_name, exc)
        return json.dumps({"error": f"error ejecutando {tool_name}: {exc}"})

    # Limitar tamano
    text = json.dumps(result, ensure_ascii=False)
    if len(text) > MAX_RESPONSE_CHARS:
        text = text[:MAX_RESPONSE_CHARS] + '..."}'

    logger.info("Tool %s ejecutada, respuesta %d chars", tool_name, len(text))
    return text


def preload(agent: str, case: Any) -> dict[str, str]:
    """Plan B: ejecuta las tools del agente con argumentos derivados del caso.

    Devuelve un dict {tool_name: resultado_json} para incluir en <contexto>.
    """
    results: dict[str, str] = {}
    tool_names = TOOLS_BY_AGENT.get(agent, [])

    if not tool_names:
        return results

    # Derivar argumentos del caso
    error_codes = _extract_error_codes(case)

    for name in tool_names:
        if name == "search_known_issues":
            for code in error_codes[:3]:
                results[f"search_known_issues({code})"] = executor(
                    "search_known_issues", {"query": code}, case
                )
        elif name == "get_recent_changes":
            app = _get_app_name(case)
            if app:
                results["get_recent_changes"] = executor(
                    "get_recent_changes", {"app": app}, case
                )
        elif name == "search_runbooks":
            for code in error_codes[:2]:
                results[f"search_runbooks({code})"] = executor(
                    "search_runbooks", {"query": code}, case
                )
        elif name == "get_change_calendar":
            results["get_change_calendar"] = executor(
                "get_change_calendar", {}, case
            )

    return results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ERROR_CODE_RE = re.compile(r"\b(ORA-\d+|HTTP[_\s]?\d{3}|KI-\d+)\b")


def _extract_error_codes(case: Any) -> list[str]:
    """Extrae codigos de error de la evidencia del caso."""
    codes: list[str] = []
    evidence = getattr(case, "evidence", []) or []
    for ev in evidence:
        text = ""
        if isinstance(ev, dict):
            text = ev.get("summary", "") + " " + ev.get("example", "")
        else:
            text = getattr(ev, "summary", "") + " " + getattr(ev, "example", "")
        codes.extend(_ERROR_CODE_RE.findall(text))
    # Unicos preservando orden
    seen: set[str] = set()
    unique: list[str] = []
    for c in codes:
        if c not in seen:
            seen.add(c)
            unique.append(c)
    return unique


def _get_app_name(case: Any) -> str:
    ticket = getattr(case, "ticket", None)
    if ticket is not None:
        return getattr(ticket, "application", "") or ""
    return ""
