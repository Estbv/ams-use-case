"""FakeClient con la misma interfaz que MaaSClient (LLM_MODE=fake).

Permite probar todo el flujo sin clave ni red. Devuelve respuestas de
ejemplo leidas de tests/fixtures/fake_responses/<agente>.json, o pasadas
explicitamente. Simula: JSON con fences, JSON invalido en el primer
intento y valido en el segundo, y tool_calls.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.llm.maas_client import ChatResult


class FakeClient:
    """Cliente simulado para pruebas sin red ni clave."""

    def __init__(
        self,
        responses: list[dict] | None = None,
        fixtures_dir: str | Path | None = None,
    ) -> None:
        self._responses = responses or []
        self._index = 0
        self._fixtures_dir = Path(fixtures_dir) if fixtures_dir else None
        self._fixture_cache: dict[str, list[dict]] = {}
        self.call_count = 0

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> ChatResult:
        self.call_count += 1

        if self._responses:
            resp = self._next_from_list(self._responses)
            return self._make_result(resp)

        if self._fixtures_dir:
            agent = self._detect_agent(messages)
            fixture = self._load_fixture(agent)
            if fixture:
                resp = self._next_from_list(fixture)
                return self._make_result(resp)

        return ChatResult(
            content="{}",
            tool_calls=None,
            tokens={"prompt": 0, "completion": 0, "total": 0},
            duration=0.0,
            raw={},
        )

    # -- helpers ------------------------------------------------------------

    def _next_from_list(self, items: list[dict]) -> dict:
        if self._index < len(items):
            resp = items[self._index]
            self._index += 1
        else:
            resp = items[-1]
        return resp

    def _make_result(self, resp: dict[str, Any]) -> ChatResult:
        return ChatResult(
            content=resp.get("content"),
            tool_calls=resp.get("tool_calls"),
            tokens=resp.get("tokens", {"prompt": 0, "completion": 0, "total": 0}),
            duration=resp.get("duration", 0.0),
            raw=resp,
        )

    def _detect_agent(self, messages: list[dict]) -> str:
        system = ""
        for m in messages:
            if m.get("role") == "system":
                system = m.get("content", "")
                break
        if "Ingesta" in system:
            return "ingest"
        if "Triage" in system:
            return "triage"
        if "Causa Ra" in system:
            return "root_cause"
        if "Resoluci" in system:
            return "resolution"
        if "Comunicaci" in system:
            return "communication"
        return "default"

    def _load_fixture(self, agent: str) -> list[dict]:
        if agent not in self._fixture_cache:
            assert self._fixtures_dir is not None
            path = self._fixtures_dir / f"{agent}.json"
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                self._fixture_cache[agent] = data.get("responses", [])
            else:
                self._fixture_cache[agent] = []
        return self._fixture_cache[agent]

    def reset(self) -> None:
        """Reinicia el contador para reutilizar el cliente en otro agente."""
        self._index = 0
        self.call_count = 0
