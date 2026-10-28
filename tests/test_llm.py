"""Pruebas del paquete app/llm/ con FakeClient y sin red."""
from __future__ import annotations

import json

import pytest
from pydantic import BaseModel, Field

from app.llm.fake_client import FakeClient
from app.llm.json_utils import clean_response, parse_and_validate
from app.llm.tool_loop import run_with_tools
from app.llm.retry import call_agent_with_validation


# ---------------------------------------------------------------------------
# Esquema de prueba
# ---------------------------------------------------------------------------

class FakeOutput(BaseModel):
    severity: str
    summary: str
    warnings: list[str] = Field(default_factory=list)


def _tokens(p: int = 10, c: int = 20) -> dict[str, int]:
    return {"prompt": p, "completion": c, "total": p + c}


# ---------------------------------------------------------------------------
# 1. clean_response
# ---------------------------------------------------------------------------

class TestCleanResponse:
    def test_fences_json(self) -> None:
        text = 'Resultado:\n```json\n{"severity": "High", "summary": "x"}\n```\nFin.'
        assert json.loads(clean_response(text)) == {"severity": "High", "summary": "x"}

    def test_fences_plain(self) -> None:
        text = '```\n{"severity": "Low", "summary": "y"}\n```'
        assert json.loads(clean_response(text)) == {"severity": "Low", "summary": "y"}

    def test_text_before_and_after(self) -> None:
        text = 'Antes\n{"severity": "Medium", "summary": "z"}\nDespues'
        assert json.loads(clean_response(text)) == {"severity": "Medium", "summary": "z"}

    def test_think_block_removed(self) -> None:
        text = '▪razonamiento interno▪{"severity": "High", "summary": "w"}'
        assert json.loads(clean_response(text)) == {"severity": "High", "summary": "w"}

    def test_nested_json(self) -> None:
        text = '{"severity": "High", "summary": "x", "warnings": ["a", "b"]}'
        result = json.loads(clean_response(text))
        assert result["warnings"] == ["a", "b"]

    def test_empty(self) -> None:
        assert clean_response("") == ""


# ---------------------------------------------------------------------------
# 2. JSON invalido en primer intento, valido en el segundo -> ok, 2 intentos
# ---------------------------------------------------------------------------

def test_invalid_then_valid_ok_two_attempts() -> None:
    client = FakeClient(responses=[
        {"content": "esto no es json", "tokens": _tokens()},
        {"content": '{"severity": "High", "summary": "ok"}', "tokens": _tokens()},
    ])
    result = call_agent_with_validation(
        client, "system", "user", FakeOutput, known_ids=None,
    )
    assert result.status == "ok"
    assert result.attempts == 2
    assert result.data is not None
    assert result.data.severity == "High"


# ---------------------------------------------------------------------------
# 3. Dos intentos invalidos -> degraded, texto crudo guardado
# ---------------------------------------------------------------------------

def test_two_invalid_degraded() -> None:
    client = FakeClient(responses=[
        {"content": "invalido_1", "tokens": _tokens()},
        {"content": "invalido_2", "tokens": _tokens()},
    ])
    result = call_agent_with_validation(
        client, "system", "user", FakeOutput, known_ids=None,
    )
    assert result.status == "degraded"
    assert result.raw_text == "invalido_2"
    assert len(result.errors) > 0


# ---------------------------------------------------------------------------
# 4. ID inexistente (E999) provoca error de validacion
# ---------------------------------------------------------------------------

def test_unknown_id_validation_error() -> None:
    client = FakeClient(responses=[
        {"content": '{"severity": "High", "summary": "ver E999"}', "tokens": _tokens()},
        {"content": '{"severity": "High", "summary": "ver E999"}', "tokens": _tokens()},
    ])
    result = call_agent_with_validation(
        client, "system", "user", FakeOutput,
        known_ids={"E001", "E002"},
    )
    assert result.status == "degraded"
    assert any("E999" in e for e in result.errors)


# ---------------------------------------------------------------------------
# 5. El bucle de tools se detiene en MAX_TOOL_CALLS
# ---------------------------------------------------------------------------

def test_tool_loop_stops_at_max_calls() -> None:
    tool_call = [{
        "id": "call_1",
        "type": "function",
        "function": {"name": "search_known_issues", "arguments": '{"query": "ORA"}'},
    }]

    # 5 respuestas con tool_calls + 1 respuesta final sin tools
    responses = []
    for _ in range(5):
        responses.append({
            "content": None,
            "tool_calls": tool_call,
            "tokens": _tokens(),
        })
    responses.append({
        "content": '{"severity": "High", "summary": "final"}',
        "tokens": _tokens(),
    })

    client = FakeClient(responses=responses)
    executor = lambda name, args: "resultado de tool"  # noqa: E731
    tool_def = {
        "type": "function",
        "function": {
            "name": "search_known_issues",
            "description": "busca problemas conocidos",
            "parameters": {"type": "object", "properties": {}},
        },
    }

    result = run_with_tools(
        client,
        [{"role": "user", "content": "test"}],
        [tool_def],
        executor,
        max_calls=5,
    )
    assert len(result.tool_calls_made) == 5
    assert result.content == '{"severity": "High", "summary": "final"}'
    assert any("Limite" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# Extra: parse_and_validate directo
# ---------------------------------------------------------------------------

def test_parse_and_validate_ok() -> None:
    text = '{"severity": "Critical", "summary": "test", "warnings": []}'
    obj, errors = parse_and_validate(text, FakeOutput, known_ids=None)
    assert errors == []
    assert obj is not None
    assert obj.severity == "Critical"


def test_parse_and_validate_missing_field() -> None:
    text = '{"severity": "High"}'
    obj, errors = parse_and_validate(text, FakeOutput, known_ids=None)
    assert obj is None
    assert any("summary" in e for e in errors)
