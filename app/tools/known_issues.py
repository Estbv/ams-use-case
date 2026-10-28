"""search_known_issues: busca en data/known_issues.json."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.tools.base import Tool

_DATA_PATH = Path("data/known_issues.json")
MAX_RESULTS = 5


class SearchKnownIssues(Tool):
    def __init__(self) -> None:
        super().__init__(
            name="search_known_issues",
            description=(
                "Busca en la base de problemas conocidos del equipo AMS. "
                "Devuelve id, titulo, patron y guia."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Codigo de error, componente o sintoma, "
                            "p. ej. 'ORA-12170' o 'pool agotado'"
                        ),
                    }
                },
                "required": ["query"],
            },
        )

    def run(self, args: dict[str, Any], case: Any = None) -> dict[str, Any]:
        query: str = args.get("query", "").strip()
        if not query:
            return {"error": "query vacio"}

        issues = _load_known_issues()
        if not issues:
            return {"results": [], "note": "base de problemas conocidos vacia"}

        q_lower = query.lower()
        scored: list[tuple[int, dict]] = []

        for issue in issues:
            score = 0
            pattern = issue.get("pattern", "")
            title = issue.get("title", "")
            guidance = issue.get("guidance", "")

            # Coincidencia de patron regex
            try:
                if re.search(pattern, query, re.IGNORECASE):
                    score += 10
            except re.error:
                pass

            # Coincidencia del query contra el patron como texto
            if q_lower in pattern.lower():
                score += 5

            # Palabras del titulo y la guia
            if q_lower in title.lower():
                score += 3
            if q_lower in guidance.lower():
                score += 1

            # Palabras individuales del query en titulo/guia
            for word in q_lower.split():
                if len(word) >= 3:
                    if word in title.lower():
                        score += 2
                    if word in guidance.lower():
                        score += 1

            if score > 0:
                scored.append((score, issue))

        scored.sort(key=lambda x: x[0], reverse=True)
        top = [issue for _, issue in scored[:MAX_RESULTS]]

        return {"results": top, "count": len(top)}


def _load_known_issues() -> list[dict]:
    if not _DATA_PATH.exists():
        return []
    try:
        data = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []
