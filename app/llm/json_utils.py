"""Limpieza y validacion de respuestas JSON del modelo.

clean_response: quita fences de markdown, bloques ▪ y extrae el primer JSON.
parse_and_validate: json.loads + Pydantic + comprobacion de IDs de evidencia.
"""
from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, ValidationError


# ---------------------------------------------------------------------------
# Limpieza
# ---------------------------------------------------------------------------

_THINK_BLOCK = re.compile(r"▪.*?▪", re.DOTALL)
_FENCE = re.compile(r"```(?:json)?\s*\n?(.*?)```", re.DOTALL)


def clean_response(text: str) -> str:
    """Quita bloques ▪, fences de markdown y extrae el primer objeto JSON.

    Maneja:
    - Bloques ▪...▪ (razonamiento del modelo).
    - Fences ```json ... ``` o ``` ... ```.
    - Texto antes y despues del JSON.
    - Objetos JSON anidados.
    """
    if not text:
        return ""

    # 1. Quitar bloques de razonamiento
    text = _THINK_BLOCK.sub("", text)

    # 2. Extraer de fences si los hay
    m = _FENCE.search(text)
    if m:
        text = m.group(1)

    # 3. Extraer el primer objeto JSON completo
    return _extract_first_json(text)


def _extract_first_json(text: str) -> str:
    """Extrae el primer objeto JSON balanceado (maneja anidacion y strings)."""
    start = text.find("{")
    if start == -1:
        return text.strip()

    depth = 0
    in_string = False
    escape = False

    for i in range(start, len(text)):
        ch = text[i]

        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue

        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]

    return text[start:].strip()


# ---------------------------------------------------------------------------
# Validacion
# ---------------------------------------------------------------------------

_EVIDENCE_ID = re.compile(r"E\d{3,}")


def parse_and_validate(
    text: str,
    schema_model: type[BaseModel],
    known_ids: set[str] | None = None,
) -> tuple[BaseModel | None, list[str]]:
    """Limpia, parsea y valida la respuesta del modelo.

    Devuelve (objeto_validado, []) si todo es correcto,
    o (None, [errores]) si falla.
    """
    errors: list[str] = []

    # 1. Limpiar
    try:
        cleaned = clean_response(text)
    except Exception as exc:
        return None, [f"limpieza fallida: {exc}"]

    # 2. JSON parse
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        return None, [f"no es JSON valido: {exc}"]

    # 3. Validar contra el esquema Pydantic
    try:
        obj = schema_model.model_validate(data)
    except ValidationError as exc:
        errors.extend(_format_pydantic_errors(exc))
        return None, errors

    # 4. Comprobar IDs de evidencia citados
    if known_ids is not None:
        cited = set(_EVIDENCE_ID.findall(cleaned))
        unknown = cited - known_ids
        if unknown:
            errors.append(
                f"IDs de evidencia no encontrados: {', '.join(sorted(unknown))}"
            )
            return None, errors

    return obj, []


def _format_pydantic_errors(exc: ValidationError) -> list[str]:
    """Convierte errores de Pydantic en mensajes legibles."""
    result: list[str] = []
    for err in exc.errors():
        loc = ".".join(str(x) for x in err["loc"])
        result.append(f"falta o es invalido el campo '{loc}': {err['msg']}")
    return result


def find_cited_ids(text: str) -> set[str]:
    """Devuelve todos los IDs E\\d{3,} citados en el texto."""
    return set(_EVIDENCE_ID.findall(text))
