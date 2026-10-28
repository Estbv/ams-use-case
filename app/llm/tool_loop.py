"""Bucle de llamadas a tools (function calling).

Si el modelo pide tools, las ejecuta y vuelve a llamar hasta obtener la
respuesta final o llegar a MAX_TOOL_CALLS. Plan B: si el endpoint rechaza
el parametro "tools" (HTTP 400), devuelve marca para modo contexto pre-cargado.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

from app.llm.maas_client import ChatResult, MaaSError
from app.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class ToolLoopResult:
    """Resultado del bucle de tools."""

    content: str | None
    messages: list[dict] = field(default_factory=list)
    tool_calls_made: list[dict] = field(default_factory=list)
    tokens: dict[str, int] = field(default_factory=dict)
    duration: float = 0.0
    warnings: list[str] = field(default_factory=list)
    context_preloaded: bool = False


def run_with_tools(
    client: object,
    messages: list[dict],
    tools: list[dict],
    executor: Callable[[str, str], str],
    max_calls: int = 5,
) -> ToolLoopResult:
    """Ejecuta el bucle de tools hasta obtener la respuesta final.

    *executor* recibe (tool_name, arguments_json) y devuelve el resultado.
    """
    warnings: list[str] = []
    tool_calls_made: list[dict] = []
    total_tokens: dict[str, int] = {"prompt": 0, "completion": 0, "total": 0}
    start = time.time()
    current_messages = list(messages)
    calls = 0

    while calls < max_calls:
        try:
            result: ChatResult = client.chat(current_messages, tools=tools)  # type: ignore[attr-defined]
        except MaaSError as exc:
            if exc.status_code == 400 and calls == 0:
                warnings.append(
                    "El endpoint rechazo el parametro 'tools' (HTTP 400). "
                    "Usar modo contexto pre-cargado: ejecutar tools antes "
                    "del agente e incluir resultados en <contexto>."
                )
                return ToolLoopResult(
                    content=None,
                    messages=current_messages,
                    tool_calls_made=[],
                    tokens=total_tokens,
                    duration=time.time() - start,
                    warnings=warnings,
                    context_preloaded=True,
                )
            raise

        _accumulate_tokens(total_tokens, result.tokens)

        # Sin tool_calls -> respuesta final
        if not result.tool_calls:
            current_messages.append(
                {"role": "assistant", "content": result.content}
            )
            return ToolLoopResult(
                content=result.content,
                messages=current_messages,
                tool_calls_made=tool_calls_made,
                tokens=total_tokens,
                duration=time.time() - start,
                warnings=warnings,
                context_preloaded=False,
            )

        # Ejecutar tool calls
        calls += 1
        current_messages.append({
            "role": "assistant",
            "content": result.content,
            "tool_calls": result.tool_calls,
        })

        for tc in result.tool_calls:
            func = tc.get("function", {})
            name = func.get("name", "")
            args = func.get("arguments", "{}")
            try:
                tool_result = executor(name, args)
            except Exception as exc:
                tool_result = f"Error ejecutando {name}: {exc}"
                warnings.append(f"Tool {name} fallo: {exc}")

            current_messages.append({
                "role": "tool",
                "tool_call_id": tc.get("id", ""),
                "content": tool_result,
            })
            tool_calls_made.append({
                "name": name,
                "arguments": args,
                "result": tool_result,
            })

    # Limite alcanzado: pedir respuesta final sin tools
    warnings.append(
        f"Limite de {max_calls} llamadas a tools alcanzado. "
        "Pidiendo respuesta final sin tools."
    )
    result = client.chat(current_messages, tools=None)  # type: ignore[attr-defined]
    _accumulate_tokens(total_tokens, result.tokens)
    current_messages.append({"role": "assistant", "content": result.content})

    return ToolLoopResult(
        content=result.content,
        messages=current_messages,
        tool_calls_made=tool_calls_made,
        tokens=total_tokens,
        duration=time.time() - start,
        warnings=warnings,
        context_preloaded=False,
    )


def _accumulate_tokens(total: dict[str, int], chunk: dict[str, int]) -> None:
    for k in total:
        total[k] += chunk.get(k, 0)
