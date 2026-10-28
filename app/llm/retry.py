"""Reintento con validacion: llama al modelo, limpia y valida.

Si la validacion falla, reintenta UNA vez con el mensaje de correccion.
Si vuelve a fallar, devuelve status="degraded" con el texto crudo.
Siempre devuelve un registro de auditoria.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic import BaseModel

from app.llm.json_utils import parse_and_validate
from app.llm.maas_client import ChatResult, MaaSError
from app.llm.tool_loop import run_with_tools
from app.logging_config import get_logger

logger = get_logger(__name__)


# Mensaje de correccion (seccion 5 de la especificacion)
CORRECTION_MESSAGE = (
    "Tu respuesta anterior no es valida: {motivo}\n"
    "(por ejemplo: \"no es JSON valido\", \"falta la clave 'severity'\", "
    "\"el ID E214 no existe\").\n"
    "Devuelve UNICAMENTE el objeto JSON completo y corregido, "
    "cumpliendo el esquema de salida.\n"
    "No agregues explicaciones."
)


@dataclass
class AgentResult:
    """Resultado de call_agent_with_validation."""

    status: str  # "ok" | "degraded" | "context_preloaded"
    data: BaseModel | None = None
    raw_text: str = ""
    errors: list[str] = field(default_factory=list)
    attempts: int = 0
    audit: dict[str, Any] = field(default_factory=dict)
    context_preloaded: bool = False


def call_agent_with_validation(
    client: object,
    system_prompt: str,
    user_prompt: str,
    schema_model: type[BaseModel],
    known_ids: set[str] | None = None,
    tools: list[dict] | None = None,
    tool_executor: Callable[[str, str], str] | None = None,
    max_tool_calls: int = 5,
) -> AgentResult:
    """Llama al modelo, limpia, valida y reintente si es necesario.

    Flujo:
    1. Construye mensajes [system, user].
    2. Llama al modelo (con tools si aplica).
    3. Limpia y valida la respuesta.
    4. Si falla, reinteta una vez con el mensaje de correccion.
    5. Si vuelve a fallar, devuelve status="degraded".
    """
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    audit: dict[str, Any] = {
        "messages_sent": [system_prompt, user_prompt],
        "responses": [],
        "attempts": 0,
        "tokens": {"prompt": 0, "completion": 0, "total": 0},
        "duration": 0.0,
        "warnings": [],
    }

    start = time.time()

    # --- Intento 1 ---
    content, conv_messages, tokens, warnings = _call_model(
        client, messages, tools, tool_executor, max_tool_calls
    )

    audit["responses"].append(content or "")
    audit["warnings"].extend(warnings)
    _accumulate_tokens(audit["tokens"], tokens)

    if warnings and any("contexto pre-cargado" in w for w in warnings):
        audit["duration"] = time.time() - start
        return AgentResult(
            status="context_preloaded",
            raw_text="",
            attempts=0,
            audit=audit,
            context_preloaded=True,
        )

    obj, errors = parse_and_validate(content or "", schema_model, known_ids)
    audit["attempts"] = 1

    if not errors:
        audit["duration"] = time.time() - start
        return AgentResult(
            status="ok",
            data=obj,
            raw_text=content or "",
            attempts=1,
            audit=audit,
        )

    # --- Intento 2 (reintento con correccion) ---
    motivo = "; ".join(errors)
    correction = CORRECTION_MESSAGE.format(motivo=motivo)
    conv_messages.append({"role": "assistant", "content": content or ""})
    conv_messages.append({"role": "user", "content": correction})
    audit["messages_sent"].append(correction)

    try:
        result: ChatResult = client.chat(conv_messages)  # type: ignore[attr-defined]
        content2 = result.content or ""
        tokens2 = result.tokens
    except MaaSError as exc:
        audit["duration"] = time.time() - start
        return AgentResult(
            status="degraded",
            raw_text="",
            errors=[f"error de MaaS en reintento: {exc.message}"],
            attempts=2,
            audit=audit,
        )

    audit["responses"].append(content2)
    _accumulate_tokens(audit["tokens"], tokens2)

    obj2, errors2 = parse_and_validate(content2, schema_model, known_ids)
    audit["attempts"] = 2

    if not errors2:
        audit["duration"] = time.time() - start
        return AgentResult(
            status="ok",
            data=obj2,
            raw_text=content2,
            attempts=2,
            audit=audit,
        )

    # --- Degraded ---
    audit["duration"] = time.time() - start
    return AgentResult(
        status="degraded",
        raw_text=content2,
        errors=errors2,
        attempts=2,
        audit=audit,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _call_model(
    client: object,
    messages: list[dict],
    tools: list[dict] | None,
    tool_executor: Callable[[str, str], str] | None,
    max_tool_calls: int,
) -> tuple[str | None, list[dict], dict[str, int], list[str]]:
    """Llama al modelo con o sin tools. Devuelve (content, messages, tokens, warnings)."""
    if tools and tool_executor:
        tl_result = run_with_tools(
            client, messages, tools, tool_executor, max_tool_calls
        )
        return tl_result.content, tl_result.messages, tl_result.tokens, tl_result.warnings

    result: ChatResult = client.chat(messages)  # type: ignore[attr-defined]
    conv = messages + [{"role": "assistant", "content": result.content}]
    return result.content, conv, result.tokens, []


def _accumulate_tokens(total: dict[str, int], chunk: dict[str, int]) -> None:
    for k in total:
        total[k] += chunk.get(k, 0)
