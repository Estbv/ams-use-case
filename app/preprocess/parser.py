"""Parser de logs: lectura, deteccion de timestamp, nivel y union de stack traces.

Funciones puras, sin llamadas a red. Toda la salida de texto que sale del
paquete pasa despues por masking; este modulo trabaja con texto en bruto
unicamente de forma interna.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable


@dataclass
class LogLine:
    """Una linea de log parseada (puede incluir lineas de stack trace anexas)."""

    timestamp: datetime | None
    level: str  # ERROR | WARN | INFO | DEBUG
    message: str  # contenido sin el timestamp
    stack_trace: list[str] = field(default_factory=list)
    raw: str = ""
    source: str = ""


# ---------------------------------------------------------------------------
# Deteccion de marcas de tiempo
# ---------------------------------------------------------------------------

def _parse_std(ts: str) -> datetime | None:
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(ts, fmt)
        except ValueError:
            continue
    return None


def _parse_iso(ts: str) -> datetime | None:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_nginx(ts: str) -> datetime | None:
    try:
        return datetime.strptime(ts, "%d/%b/%Y:%H:%M:%S %z")
    except ValueError:
        return None


def _parse_slash(ts: str) -> datetime | None:
    try:
        return datetime.strptime(ts, "%Y/%m/%d %H:%M:%S")
    except ValueError:
        return None


# (regex, parser)  -- el regex captura la cadena de timestamp en el grupo 1
TIMESTAMP_PATTERNS: list[tuple[re.Pattern, Callable[[str], datetime | None]]] = [
    (re.compile(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d+)?)"), _parse_std),
    (re.compile(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2}))"), _parse_iso),
    (re.compile(r"\[(\d{2}/\w{3}/\d{4}:\d{2}:\d{2}:\d{2} [+-]\d{4})\]"), _parse_nginx),
    (re.compile(r"(\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2})"), _parse_slash),
]


def extract_timestamp(line: str) -> tuple[datetime | None, int, int]:
    """Busca la primera marca de tiempo valida en *line*.

    Devuelve (datetime, start_pos, end_pos) o (None, -1, -1).
    """
    for pattern, parser in TIMESTAMP_PATTERNS:
        m = pattern.search(line)
        if m:
            dt = parser(m.group(1))
            if dt is not None:
                if dt.tzinfo is not None:
                    dt = dt.replace(tzinfo=None)
                return dt, m.start(), m.end()
    return None, -1, -1


# ---------------------------------------------------------------------------
# Deteccion de nivel
# ---------------------------------------------------------------------------

_LEVEL_MAP = {
    "FATAL": "ERROR", "CRITICAL": "ERROR", "SEVERE": "ERROR", "ERROR": "ERROR",
    "WARN": "WARN", "WARNING": "WARN",
    "INFO": "INFO",
    "DEBUG": "DEBUG", "TRACE": "DEBUG",
}
_LEVEL_WORDS = set(_LEVEL_MAP)
_BRACKET_LEVEL = re.compile(r"\[(error|warn|warning|info|debug|trace|fatal|critical|severe)\]", re.I)
_LEVEL_AFTER_TS = re.compile(r"(\w+)")
_HTTP_STATUS = re.compile(r'HTTP/\d\.\d"\s+(\d{3})')
_ANY_LEVEL = re.compile(r"\b(TRACE|DEBUG|INFO|WARN|WARNING|ERROR|FATAL|CRITICAL|SEVERE)\b")


def _normalize_level(word: str) -> str:
    return _LEVEL_MAP.get(word.upper(), "INFO")


def _http_status_to_level(status: int) -> str:
    if 500 <= status <= 599:
        return "ERROR"
    if 400 <= status <= 499:
        return "WARN"
    return "INFO"


def detect_level(line: str, ts_start: int, ts_end: int) -> str:
    """Determina el nivel de la linea de log."""
    # 1. Nginx error style: [error], [warn], ...
    m = _BRACKET_LEVEL.search(line)
    if m:
        return _normalize_level(m.group(1))

    # 2. Nivel como primera palabra despues del timestamp (Java/Oracle)
    if ts_end > 0:
        rest = line[ts_end:].lstrip()
        m = _LEVEL_AFTER_TS.match(rest)
        if m and m.group(1).upper() in _LEVEL_WORDS:
            return _normalize_level(m.group(1))

    # 3. Codigo HTTP en access logs
    m = _HTTP_STATUS.search(line)
    if m:
        return _http_status_to_level(int(m.group(1)))

    # 4. Cualquier palabra de nivel en la linea
    m = _ANY_LEVEL.search(line)
    if m:
        return _normalize_level(m.group(1))

    return "INFO"


# ---------------------------------------------------------------------------
# Deteccion de stack traces
# ---------------------------------------------------------------------------

_AT_LINE = re.compile(r"^\s+at\s")
_CAUSED_BY = re.compile(r"^\s*Caused by:")
_N_MORE = re.compile(r"^\s*\.\.\.\s+\d+\s+more")
_EX_CLASS = re.compile(r"^(?:[a-zA-Z_$][\w$]*\.)+[a-zA-Z_$][\w$]*(?:Exception|Error|Throwable)")


def is_stack_trace_line(line: str) -> bool:
    """Indica si una linea sin timestamp es continuacion (stack trace)."""
    if not line.strip():
        return False
    if _AT_LINE.match(line):
        return True
    if _CAUSED_BY.match(line):
        return True
    if _N_MORE.match(line):
        return True
    if _EX_CLASS.match(line.strip()):
        return True
    return False


# ---------------------------------------------------------------------------
# Logs en JSON
# ---------------------------------------------------------------------------

def _try_json_log(line: str) -> dict | None:
    stripped = line.strip()
    if not stripped.startswith("{"):
        return None
    try:
        obj = json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        return None
    if isinstance(obj, dict) and any(k in obj for k in ("ts", "timestamp", "time", "@timestamp")):
        return obj
    return None


def _json_timestamp(obj: dict) -> datetime | None:
    for key in ("ts", "timestamp", "time", "@timestamp"):
        if key in obj:
            dt, _, _ = extract_timestamp(str(obj[key]))
            if dt is not None:
                return dt
    return None


def _json_level(obj: dict) -> str:
    for key in ("level", "severity", "loglevel"):
        if key in obj:
            return _normalize_level(str(obj[key]))
    return "INFO"


def _json_message(obj: dict) -> str:
    for key in ("msg", "message", "event", "text"):
        if key in obj:
            return str(obj[key])
    return json.dumps(obj, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Parseo principal
# ---------------------------------------------------------------------------

def parse_text(text: str, source: str = "") -> list[LogLine]:
    """Parsea un bloque de texto en una lista de LogLine.

    Las lineas de stack trace se anexan a la linea principal anterior.
    Las lineas sin marca de tiempo que no son stack trace se conservan
    con timestamp = None.
    """
    lines = text.splitlines()
    result: list[LogLine] = []

    for raw_line in lines:
        if not raw_line.strip():
            continue

        # Intentar JSON
        obj = _try_json_log(raw_line)
        if obj is not None:
            ts = _json_timestamp(obj)
            level = _json_level(obj)
            msg = _json_message(obj)
            result.append(LogLine(
                timestamp=ts, level=level, message=msg,
                stack_trace=[], raw=raw_line, source=source,
            ))
            continue

        # Timestamp normal
        dt, ts_start, ts_end = extract_timestamp(raw_line)
        if dt is not None:
            message = (raw_line[:ts_start] + raw_line[ts_end:]).strip()
            level = detect_level(raw_line, ts_start, ts_end)
            result.append(LogLine(
                timestamp=dt, level=level, message=message,
                stack_trace=[], raw=raw_line, source=source,
            ))
            continue

        # Sin timestamp: ¿stack trace?
        if is_stack_trace_line(raw_line) and result:
            result[-1].stack_trace.append(raw_line)
            continue

        # Sin timestamp, no es stack trace: linea independiente
        result.append(LogLine(
            timestamp=None, level="INFO", message=raw_line.strip(),
            stack_trace=[], raw=raw_line, source=source,
        ))

    return result


def parse_file(path: str | Path, source: str | None = None) -> list[LogLine]:
    """Lee un archivo de log (UTF-8, errors=replace) y lo parsea."""
    p = Path(path)
    text = p.read_text(encoding="utf-8", errors="replace")
    src = source if source is not None else p.name
    return parse_text(text, source=src)
