"""search_runbooks: busca en los archivos Markdown de data/runbooks/."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.tools.base import Tool

_RUNBOOKS_DIR = Path("data/runbooks")
MAX_RESULTS = 5
FRAGMENT_CHARS = 500


class SearchRunbooks(Tool):
    def __init__(self) -> None:
        super().__init__(
            name="search_runbooks",
            description=(
                "Busca runbooks y procedimientos existentes del equipo. "
                "Devuelve el titulo y un fragmento del runbook."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Texto a buscar, p. ej. 'pool agotado'",
                    }
                },
                "required": ["query"],
            },
        )

    def run(self, args: dict[str, Any], case: Any = None) -> dict[str, Any]:
        query: str = args.get("query", "").strip()
        if not query:
            return {"error": "query vacio"}

        if not _RUNBOOKS_DIR.exists():
            return {"results": [], "note": "no hay runbooks"}

        q_lower = query.lower()
        results: list[dict] = []

        for md_file in sorted(_RUNBOOKS_DIR.glob("*.md")):
            text = md_file.read_text(encoding="utf-8", errors="replace")
            text_lower = text.lower()

            if q_lower not in text_lower:
                # Buscar palabras individuales
                words = [w for w in q_lower.split() if len(w) >= 3]
                if not words or not all(w in text_lower for w in words):
                    continue

            # Extraer titulo (primer # o nombre del archivo)
            title_match = re.search(r"^#\s+(.+)", text, re.MULTILINE)
            title = title_match.group(1).strip() if title_match else md_file.stem

            # Fragmento alrededor de la coincidencia
            idx = text_lower.find(q_lower)
            if idx == -1:
                fragment = text[:FRAGMENT_CHARS]
            else:
                start = max(0, idx - 100)
                end = min(len(text), idx + FRAGMENT_CHARS - 100)
                fragment = text[start:end]

            results.append({
                "file": md_file.name,
                "title": title,
                "fragment": fragment.strip(),
            })

            if len(results) >= MAX_RESULTS:
                break

        return {"results": results, "count": len(results)}
