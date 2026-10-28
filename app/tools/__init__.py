"""Paso 4 - Tools de solo lectura para los agentes."""
from app.tools.base import Tool
from app.tools.evidence import GetEvidenceDetail
from app.tools.known_issues import SearchKnownIssues
from app.tools.changes import GetRecentChanges
from app.tools.runbooks import SearchRunbooks
from app.tools.calendar import GetChangeCalendar
from app.tools.registry import (
    TOOLS_BY_AGENT,
    get_tools,
    get_openai_tools,
    executor,
    preload,
)

__all__ = [
    "Tool",
    "GetEvidenceDetail",
    "SearchKnownIssues",
    "GetRecentChanges",
    "SearchRunbooks",
    "GetChangeCalendar",
    "TOOLS_BY_AGENT",
    "get_tools",
    "get_openai_tools",
    "executor",
    "preload",
]
