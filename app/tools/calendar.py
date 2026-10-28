"""get_change_calendar: lee data/calendar.json (ventanas de cambio y jobs)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.tools.base import Tool

_DATA_PATH = Path("data/calendar.json")


class GetChangeCalendar(Tool):
    def __init__(self) -> None:
        super().__init__(
            name="get_change_calendar",
            description=(
                "Ventanas de cambio y jobs programados en un rango de fechas. "
                "Lee data/calendar.json."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "from": {"type": "string", "description": "Fecha/hora inicial (ISO)"},
                    "to": {"type": "string", "description": "Fecha/hora final (ISO)"},
                },
            },
        )

    def run(self, args: dict[str, Any], case: Any = None) -> dict[str, Any]:
        from_str: str = args.get("from", "")
        to_str: str = args.get("to", "")

        entries = _load_calendar()
        if not entries:
            return {"entries": [], "note": "calendario vacio"}

        results: list[dict] = []
        for entry in entries:
            if from_str and to_str:
                start = str(entry.get("start", entry.get("from", "")))
                end = str(entry.get("end", entry.get("to", "")))
                # Filtro simple por prefijo de fecha
                if start and start > to_str:
                    continue
                if end and end < from_str:
                    continue
            results.append(entry)

        return {"entries": results, "count": len(results)}


def _load_calendar() -> list[dict]:
    if not _DATA_PATH.exists():
        return []
    try:
        data = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []
