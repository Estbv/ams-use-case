"""Asignacion de IDs de evidencia globales (E001, E002, ...).

Se asignan en orden cronologico antes de enviar las fuentes en paralelo
a los agentes de ingesta. Las firmas sin hora van al final.
"""
from __future__ import annotations

from app.preprocess.signatures import Signature


def assign_ids(signatures: list[Signature]) -> list[Signature]:
    """Asigna E001, E002, ... globalmente en orden cronologico.

    Devuelve una nueva lista ordenada. Las firmas sin timestamp van al
    final, conservando su orden relativo.
    """
    with_ts = [s for s in signatures if s.time_first is not None]
    without_ts = [s for s in signatures if s.time_first is None]

    with_ts.sort(key=lambda s: s.time_first)  # type: ignore[arg-type]

    ordered = with_ts + without_ts
    for i, sig in enumerate(ordered, start=1):
        sig.evidence_id = f"E{i:03d}"
    return ordered


def known_ids(signatures: list[Signature]) -> set[str]:
    """Conjunto de IDs asignados, para validacion en merge."""
    return {s.evidence_id for s in signatures if s.evidence_id is not None}
