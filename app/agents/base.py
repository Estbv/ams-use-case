"""Clase base de los agentes.

Carga prompts, reemplaza {{REGLAS_COMUNES}}, rellena plantillas de usuario,
ejecuta con tools o preload (plan B) y valida la salida.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from app.config import settings
from app.llm.fake_client import FakeClient
from app.llm.maas_client import MaaSClient
from app.llm.retry import AgentResult, call_agent_with_validation
from app.logging_config import get_logger
from app.tools.registry import TOOLS_BY_AGENT, executor, get_openai_tools, preload

logger = get_logger(__name__)

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
MAX_EVIDENCE_TOKENS = 4000
_PLACEHOLDER_RE = re.compile(r"\{\{.*?\}\}")


# ---------------------------------------------------------------------------
# Control de tamano de evidencia
# ---------------------------------------------------------------------------

_LEVEL_PRIORITY = {"ERROR": 0, "WARN": 1, "INFO": 2, "DEBUG": 3}


def filter_evidence_by_size(
    evidence: list[dict],
    max_tokens: int = MAX_EVIDENCE_TOKENS,
) -> tuple[list[dict], list[dict]]:
    """Prioriza ERROR > WARN > INFO notable > INFO > DEBUG.

    Devuelve (mantenida, omitida).
    """
    sorted_ev = sorted(
        evidence,
        key=lambda e: (
            _LEVEL_PRIORITY.get(e.get("level", "INFO"), 2),
            not e.get("notable", False),
        ),
    )
    max_chars = max_tokens * 4
    kept: list[dict] = []
    omitted: list[dict] = []
    total = 0
    for ev in sorted_ev:
        ev_chars = len(json.dumps(ev, ensure_ascii=False))
        if total + ev_chars <= max_chars:
            kept.append(ev)
            total += ev_chars
        else:
            omitted.append(ev)
    return kept, omitted


# ---------------------------------------------------------------------------
# BaseAgent
# ---------------------------------------------------------------------------

class BaseAgent:
    """Base de todos los agentes. Subclases definen build_inputs()."""

    def __init__(
        self,
        agent_name: str,
        output_model: type[BaseModel],
        client: Any = None,
    ) -> None:
        self.agent_name = agent_name
        self.output_model = output_model
        self.prompts_dir = PROMPTS_DIR / agent_name
        self._client = client
        self._case: Any = None

    # -- cliente ------------------------------------------------------------

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        if settings.LLM_MODE == "fake":
            return FakeClient(fixtures_dir="tests/fixtures/fake_responses")
        return MaaSClient()

    # -- prompts ------------------------------------------------------------

    def load_system_prompt(self) -> str:
        """Carga system.md y reemplaza {{REGLAS_COMUNES}}."""
        system = (self.prompts_dir / "system.md").read_text(encoding="utf-8")
        common = (PROMPTS_DIR / "common_rules.md").read_text(encoding="utf-8")
        system = system.replace("{{REGLAS_COMUNES}}", common)
        remaining = _PLACEHOLDER_RE.findall(system)
        if remaining:
            raise ValueError(f"placeholders sin reemplazar en system.md: {remaining}")
        return system

    def load_user_template(self) -> str:
        return (self.prompts_dir / "user.md").read_text(encoding="utf-8")

    def render_user_prompt(self, **kwargs: Any) -> str:
        """Rellena user.md con los datos. Los valores se insertan tal cual."""
        template = self.load_user_template()
        for key, value in kwargs.items():
            template = template.replace(f"{{{{{key}}}}}", str(value))
        return template

    def build_inputs(self, case: Any, **extra: Any) -> dict[str, Any]:
        """Extrae los inputs del caso. Override en cada subclase."""
        raise NotImplementedError

    # -- IDs conocidos ------------------------------------------------------

    def _known_ids(self, case: Any) -> set[str]:
        ids: set[str] = set()
        for ev in getattr(case, "evidence", []) or []:
            eid = ev.get("id") if isinstance(ev, dict) else getattr(ev, "id", None)
            if eid:
                ids.add(eid)
        return ids

    # -- tool executor ------------------------------------------------------

    def _tool_executor(self, tool_name: str, args: str) -> str:
        return executor(tool_name, args, self._case)

    # -- ejecucion ----------------------------------------------------------

    def run(self, case: Any, **extra: Any) -> AgentResult:
        """Ejecuta el agente sobre el caso."""
        self._case = case
        client = self._get_client()
        system_prompt = self.load_system_prompt()
        inputs = self.build_inputs(case, **extra)
        user_prompt = self.render_user_prompt(**inputs)

        tool_names = TOOLS_BY_AGENT.get(self.agent_name, [])
        tools = get_openai_tools(self.agent_name) if tool_names else None
        known_ids = self._known_ids(case)

        # Intento con tools (si las tiene)
        if tools:
            result = call_agent_with_validation(
                client=client,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                schema_model=self.output_model,
                known_ids=known_ids or None,
                tools=tools,
                tool_executor=self._tool_executor,
                max_tool_calls=settings.MAX_TOOL_CALLS,
            )
            # Plan B: endpoint no admite tools
            if result.context_preloaded:
                logger.info("Plan B: preload tools para %s", self.agent_name)
                context = preload(self.agent_name, case)
                if context:
                    ctx_text = "\n".join(
                        f"[{name}] {result}" for name, result in context.items()
                    )
                    user_prompt += f"\n\n<contexto>\n{ctx_text}\n</contexto>"

                result = call_agent_with_validation(
                    client=client,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    schema_model=self.output_model,
                    known_ids=known_ids or None,
                )
        else:
            result = call_agent_with_validation(
                client=client,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                schema_model=self.output_model,
                known_ids=known_ids or None,
            )

        # Guardar prompt final en auditoria
        result.audit["system_prompt"] = system_prompt
        result.audit["user_prompt"] = user_prompt
        result.audit["agent"] = self.agent_name

        return result


# ---------------------------------------------------------------------------
# Helpers para build_inputs
# ---------------------------------------------------------------------------

def ticket_to_text(ticket: Any) -> str:
    """Convierte un Ticket a texto legible para el prompt."""
    if ticket is None:
        return ""
    if isinstance(ticket, BaseModel):
        return ticket.model_dump_json(indent=2)
    return json.dumps(ticket, ensure_ascii=False, indent=2)


def evidence_to_text(evidence: list[dict]) -> str:
    """Convierte la evidencia a texto para el prompt."""
    return json.dumps(evidence, ensure_ascii=False, indent=2)


def trends_to_text(trends: list[dict]) -> str:
    return json.dumps(trends, ensure_ascii=False, indent=2)


def now_hhmm() -> str:
    return datetime.now().strftime("%H:%M")
