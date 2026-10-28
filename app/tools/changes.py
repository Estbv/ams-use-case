"""get_recent_changes: lee data/changes.json y los recent_changes del ticket."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from app.tools.base import Tool

_DATA_PATH = Path("data/changes.json")


class GetRecentChanges(Tool):
    def __init__(self) -> None:
        super().__init__(
            name="get_recent_changes",
            description=(
                "Despliegues y cambios en la ventana del incidente. "
                "Lee data/changes.json y los recent_changes del ticket."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "app": {"type": "string", "description": "Nombre de la aplicacion"},
                    "from": {"type": "string", "description": "Fecha/hora inicial (ISO)"},
                    "to": {"type": "string", "description": "Fecha/hora final (ISO)"},
                },
                "required": ["app"],
            },
        )

    def run(self, args: dict[str, Any], case: Any = None) -> dict[str, Any]:
        app: str = args.get("app", "").strip()
        if not app:
            return {"error": "app vacio"}

        changes = _load_changes()
        results: list[dict] = []

        # Filtrar por aplicacion
        app_lower = app.lower()
        for ch in changes:
            ch_app = str(ch.get("app", ch.get("application", ""))).lower()
            if app_lower in ch_app or ch_app in app_lower:
                results.append(ch)

        # Incluir recent_changes del ticket del caso
        if case is not None:
            ticket = getattr(case, "ticket", None)
            if ticket is not None:
                recent = getattr(ticket, "recent_changes", None)
                if recent:
                    results.append({
                        "source": "ticket",
                        "app": app,
                        "description": recent,
                    })

        return {"changes": results, "count": len(results)}


def _load_changes() -> list[dict]:
    if not _DATA_PATH.exists():
        return []
    try:
        data = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []
