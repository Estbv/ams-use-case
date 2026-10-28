"""Agrupacion de mensajes repetidos en firmas.

Normaliza el mensaje (UUID, hex, numeros, IDs -> marcadores) conservando
los codigos de error (ORA-00054, HTTP 504, KI-xxx). Extrae duraciones.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from app.preprocess.parser import LogLine


@dataclass
class Signature:
    """Una firma agrupa mensajes repetidos de la misma fuente."""

    source: str
    level: str
    template: str  # mensaje normalizado para agrupar
    count: int = 0
    time_first: datetime | None = None
    time_last: datetime | None = None
    example: str = ""  # linea de ejemplo enmascarada
    example_stack: list[str] = field(default_factory=list)
    duration_first: float | None = None  # ms
    duration_max: float | None = None  # ms
    duration_last: float | None = None  # ms
    evidence_id: str | None = None  # asignado por ids.py


# ---------------------------------------------------------------------------
# Normalizacion para agrupar
# ---------------------------------------------------------------------------

_UUID = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
_LONG_ID = re.compile(r"\b[a-z0-9]{12,}\b")
_BUSINESS_ID = re.compile(r"\b[A-Z]{2,}-\d+\b")
_NUMBER = re.compile(r"\b\d+\b")
# Patrones a preservar (codigos de error)
_PRESERVE = re.compile(r"(ORA-\d+|KI-\d+|HTTP/\d\.\d\"\s+\d{3})")


def normalize_for_signature(message: str) -> str:
    """Normaliza el mensaje para agrupar repeticiones.

    Reemplaza UUID, hexadecimales largos, numeros e IDs por marcadores,
    pero conserva los codigos de error (ORA-00054, HTTP status, KI-xxx).
    """
    # Preservar codigos de error con sentinels
    stash: dict[str, str] = {}

    def _stash(m: re.Match) -> str:
        token = f"\x00S{len(stash)}\x00"
        stash[token] = m.group(0)
        return token

    s = _PRESERVE.sub(_stash, message)

    s = _UUID.sub("<uuid>", s)
    s = _LONG_ID.sub("<id>", s)
    s = _BUSINESS_ID.sub("<ID>", s)
    s = _NUMBER.sub("<num>", s)

    for token, val in stash.items():
        s = s.replace(token, val)
    return s


# ---------------------------------------------------------------------------
# Extraccion de duraciones
# ---------------------------------------------------------------------------

_DUR_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"took\s+(\d+(?:\.\d+)?)ms"), "ms"),
    (re.compile(r"completed in\s+(\d+(?:\.\d+)?)ms"), "ms"),
    (re.compile(r"rt=([\d.]+)"), "s"),
    (re.compile(r"elapsed=([\d.]+)s"), "s"),
    (re.compile(r"took\s+([\d.]+)s"), "s"),
]


def extract_duration_ms(message: str) -> float | None:
    """Extrae una duracion en ms del mensaje, o None."""
    for pattern, unit in _DUR_PATTERNS:
        m = pattern.search(message)
        if m:
            value = float(m.group(1))
            return value * 1000 if unit == "s" else value
    return None


# ---------------------------------------------------------------------------
# Seleccion de stack trace para el ejemplo
# ---------------------------------------------------------------------------

def _select_stack(stack: list[str]) -> list[str]:
    """Hasta 3 lineas 'at'/excepcion + todas las 'Caused by'."""
    selected: list[str] = []
    at_count = 0
    for line in stack:
        s = line.strip()
        if s.startswith("Caused by:"):
            selected.append(line)
        elif at_count < 3:
            selected.append(line)
            at_count += 1
    return selected


# ---------------------------------------------------------------------------
# Construccion de firmas
# ---------------------------------------------------------------------------

def build_signatures(lines: list[LogLine], source: str) -> list[Signature]:
    """Agrupa lineas en firmas por (source, level, template)."""
    groups: dict[tuple[str, str, str], Signature] = {}
    order: list[tuple[str, str, str]] = []

    for line in lines:
        template = normalize_for_signature(line.message)
        key = (source, line.level, template)

        if key not in groups:
            sig = Signature(
                source=source,
                level=line.level,
                template=template,
                example=line.message,
                example_stack=_select_stack(line.stack_trace),
            )
            groups[key] = sig
            order.append(key)

        sig = groups[key]
        sig.count += 1

        # Tiempos (min / max)
        ts = line.timestamp
        if ts is not None:
            if sig.time_first is None or ts < sig.time_first:
                sig.time_first = ts
            if sig.time_last is None or ts > sig.time_last:
                sig.time_last = ts

        # Mejorar el ejemplo si esta linea tiene mas stack trace
        if len(line.stack_trace) > len(sig.example_stack):
            sig.example = line.message
            sig.example_stack = _select_stack(line.stack_trace)

        # Duraciones
        dur = extract_duration_ms(line.message)
        if dur is not None:
            if sig.duration_first is None:
                sig.duration_first = dur
            sig.duration_last = dur
            if sig.duration_max is None or dur > sig.duration_max:
                sig.duration_max = dur

    return [groups[k] for k in order]
