"""Enmascarado de datos sensibles.

Se aplica al cuerpo del mensaje y a las lineas de stack trace antes de
cualquier agente. Devuelve el texto enmascarado y un contador por tipo.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

from app.preprocess.parser import LogLine


# ---------------------------------------------------------------------------
# Patrones
# ---------------------------------------------------------------------------

_JWT = re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")
_BEARER = re.compile(r"\bBearer\s+\S+", re.I)
_PASSWORD = re.compile(
    r"(password|passwd|pwd|secret|api[_-]?key|access[_-]?token)"
    r"\s*[=:]\s*\S+",
    re.I,
)
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_CARD = re.compile(r"(?:\d{4}[\s-]?){3}\d{4}")
_IPV4 = re.compile(r"\b(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})\b")


# ---------------------------------------------------------------------------
# Validacion de Luhn
# ---------------------------------------------------------------------------

def _luhn_valid(digits: str) -> bool:
    if len(digits) < 13 or not digits.isdigit():
        return False
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def _mask_cards(text: str) -> tuple[str, int]:
    count = 0

    def _repl(m: re.Match) -> str:
        nonlocal count
        digits = re.sub(r"[\s-]", "", m.group(0))
        if _luhn_valid(digits):
            count += 1
            return "****"
        return m.group(0)

    return _CARD.sub(_repl, text), count


def _mask_ipv4(text: str) -> tuple[str, int]:
    count = 0

    def _repl(m: re.Match) -> str:
        nonlocal count
        parts = [int(g) for g in m.groups()]
        if all(0 <= p <= 255 for p in parts):
            count += 1
            return f"{parts[0]}.{parts[1]}.{parts[2]}.0"
        return m.group(0)

    return _IPV4.sub(_repl, text), count


# ---------------------------------------------------------------------------
# API publica
# ---------------------------------------------------------------------------

def mask_text(
    text: str,
    mask_ipv4: bool = True,
    custom_rules: list[dict] | None = None,
) -> tuple[str, dict[str, int]]:
    """Enmascara datos sensibles en *text*.

    Devuelve (texto_enmascarado, contadores_por_tipo).
    """
    counters: dict[str, int] = defaultdict(int)

    text, n = _JWT.subn("***JWT***", text)
    counters["jwt"] += n

    text, n = _BEARER.subn("Bearer ***", text)
    counters["bearer"] += n

    text, n = _PASSWORD.subn(lambda m: m.group(1) + "=***", text)
    counters["password"] += n

    text, n = _EMAIL.subn("***@***", text)
    counters["email"] += n

    text, n = _mask_cards(text)
    counters["card"] += n

    if mask_ipv4:
        text, n = _mask_ipv4(text)
        counters["ipv4"] += n

    if custom_rules:
        for rule in custom_rules:
            pattern = re.compile(rule["pattern"])
            replacement = rule.get("replacement", "***")
            text, n = pattern.subn(replacement, text)
            counters["custom"] += n

    return text, dict(counters)


def mask_lines(
    lines: list[LogLine],
    mask_ipv4: bool = True,
    custom_rules: list[dict] | None = None,
) -> tuple[list[LogLine], dict[str, int]]:
    """Enmascara el mensaje y el stack trace de cada LogLine.

    Devuelve (nuevas_lineas_enmascaradas, contadores_totales).
    """
    masked: list[LogLine] = []
    total: dict[str, int] = defaultdict(int)

    for line in lines:
        msg, c = mask_text(line.message, mask_ipv4, custom_rules)
        for k, v in c.items():
            total[k] += v

        stack: list[str] = []
        for s in line.stack_trace:
            ms, sc = mask_text(s, mask_ipv4, custom_rules)
            stack.append(ms)
            for k, v in sc.items():
                total[k] += v

        masked.append(LogLine(
            timestamp=line.timestamp,
            level=line.level,
            message=msg,
            stack_trace=stack,
            raw="",
            source=line.source,
        ))

    return masked, dict(total)


def load_masking_rules(path: str | Path = "data/masking_rules.json") -> list[dict]:
    """Carga patrones custom desde un JSON. Devuelve [] si no existe."""
    p = Path(path)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return data if isinstance(data, list) else []
