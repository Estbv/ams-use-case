"""Fusion de los resultados de los agentes de ingesta.

Combina la evidencia de todas las fuentes en una lista unica ordenada por
hora, mas las tendencias. Rechaza IDs duplicados o desconocidos.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MergeResult:
    evidence: list[dict] = field(default_factory=list)
    trends: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def merge_ingest_results(
    results: list[dict],
    known_ids: set[str] | None = None,
) -> MergeResult:
    """Fusiona resultados de ingesta (uno por fuente).

    Cada *result* sigue el esquema de salida del Agente de Ingesta:
    {"source": ..., "evidence": [...], "trends": [...]}.
    """
    merged_ev: list[dict] = []
    merged_trends: list[dict] = []
    warnings: list[str] = []
    seen: set[str] = set()

    for result in results:
        source = result.get("source", "unknown")

        for ev in result.get("evidence", []):
            ev_id = ev.get("id")
            if not ev_id:
                warnings.append(f"{source}: evidencia sin ID, omitida")
                continue
            if ev_id in seen:
                warnings.append(f"{source}: ID duplicado {ev_id}, omitido")
                continue
            if known_ids is not None and ev_id not in known_ids:
                warnings.append(f"{source}: ID desconocido {ev_id}, omitido")
                continue
            seen.add(ev_id)
            merged_ev.append(ev)

        for trend in result.get("trends", []):
            merged_trends.append(trend)

    merged_ev.sort(key=lambda e: e.get("time_first", "Desconocido"))

    return MergeResult(
        evidence=merged_ev,
        trends=merged_trends,
        warnings=warnings,
    )
