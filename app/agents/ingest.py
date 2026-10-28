"""Agente de Ingesta (4.1). Procesa UNA fuente."""
from __future__ import annotations

import sys
from typing import Any

from app.agents.base import BaseAgent, ticket_to_text
from app.models.agents import IngestOutput


class IngestAgent(BaseAgent):
    def __init__(self, client: Any = None) -> None:
        super().__init__("ingest", IngestOutput, client)

    def build_inputs(
        self,
        case: Any,
        source_name: str = "",
        source_file: str = "",
        total_lines: int = 0,
        digest_text: str = "",
        **extra: Any,
    ) -> dict[str, Any]:
        ticket_resumen = ""
        if case and case.ticket:
            ticket_resumen = case.ticket.description or ticket_to_text(case.ticket)

        return {
            "ticket_resumen": ticket_resumen,
            "nombre_fuente": source_name,
            "archivo": source_file,
            "total_lineas": total_lines,
            "firmas_enmascaradas": digest_text,
        }


# ---------------------------------------------------------------------------
# Entry point: python -m app.agents.ingest <logfile>
# ---------------------------------------------------------------------------

def _main() -> None:
    from pathlib import Path

    from app.config import validate_llm_settings
    from app.logging_config import setup_logging
    from app.models.case import Case
    from app.models.ticket import Ticket
    from app.preprocess.digest import build_digest
    from app.preprocess.ids import assign_ids
    from app.preprocess.masking import load_masking_rules, mask_lines
    from app.preprocess.parser import parse_file
    from app.preprocess.signatures import build_signatures

    setup_logging()

    if len(sys.argv) < 2:
        print("Uso: python -m app.agents.ingest <logfile>")
        sys.exit(1)

    log_path = Path(sys.argv[1])
    if not log_path.exists():
        print(f"ERROR: no existe {log_path}")
        sys.exit(1)

    errors = validate_llm_settings()
    if errors:
        for e in errors:
            print(f"ERROR: {e}")
        sys.exit(1)

    # Preproceso
    source = log_path.stem
    lines = parse_file(log_path, source=source)
    custom_rules = load_masking_rules()
    masked, counters = mask_lines(lines, custom_rules=custom_rules)
    sigs = build_signatures(masked, source)
    sigs = assign_ids(sigs)
    digest_text = build_digest(sigs, source)

    # Caso minimal
    case = Case(id="CLI", ticket=Ticket(
        ticket_id="CLI", application=source, description="",
    ))
    case.evidence = [s.__dict__ for s in sigs]

    # Ejecutar agente
    agent = IngestAgent()
    result = agent.run(
        case,
        source_name=source,
        source_file=log_path.name,
        total_lines=len(lines),
        digest_text=digest_text,
    )

    print(f"Status: {result.status}")
    print(f"Attempts: {result.attempts}")
    if result.data:
        print(result.data.model_dump_json(indent=2))
    else:
        print(f"Raw: {result.raw_text}")
        print(f"Errors: {result.errors}")


if __name__ == "__main__":
    _main()
