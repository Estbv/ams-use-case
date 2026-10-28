"""get_evidence_detail: devuelve lineas completas y stack trace de evidencias."""
from __future__ import annotations

from typing import Any

from app.tools.base import Tool


class GetEvidenceDetail(Tool):
    def __init__(self) -> None:
        super().__init__(
            name="get_evidence_detail",
            description=(
                "Devuelve las lineas completas (enmascaradas) y los stack traces "
                "de las evidencias indicadas. Maximo 10 IDs por llamada."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "IDs de evidencia, p. ej. [\"E001\", \"E002\"]",
                    }
                },
                "required": ["ids"],
            },
        )

    def run(self, args: dict[str, Any], case: Any = None) -> dict[str, Any]:
        ids: list[str] = args.get("ids", [])
        if not ids:
            return {"error": "no se proporcionaron IDs"}
        if len(ids) > 10:
            return {"error": f"maximo 10 IDs por llamada, recibidos {len(ids)}"}

        evidence_map: dict[str, dict] = {}
        if case is not None:
            for ev in getattr(case, "evidence", []) or []:
                eid = ev.get("id") if isinstance(ev, dict) else getattr(ev, "id", None)
                if eid:
                    evidence_map[eid] = ev if isinstance(ev, dict) else ev.model_dump()

        results: list[dict] = []
        missing: list[str] = []
        for eid in ids:
            if eid in evidence_map:
                ev = evidence_map[eid]
                results.append({
                    "id": eid,
                    "time_first": ev.get("time_first", ""),
                    "time_last": ev.get("time_last", ""),
                    "level": ev.get("level", ""),
                    "component": ev.get("component", ""),
                    "summary": ev.get("summary", ""),
                    "example": ev.get("example", ""),
                    "stack_trace": ev.get("example_stack", ev.get("stack_trace", [])),
                })
            else:
                missing.append(eid)

        if missing and not results:
            return {"error": f"IDs no encontrados: {', '.join(missing)}"}

        output: dict[str, Any] = {"evidence": results}
        if missing:
            output["not_found"] = missing
        return output
