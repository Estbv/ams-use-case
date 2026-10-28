"""Comando de consola para ejecutar el flujo completo.

Uso:
  python -m app.orchestrator.run --logs "samples/checkout-incident/*.log" --ticket samples/checkout-incident/ticket.json
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

from app.logging_config import setup_logging
from app.models.ticket import Ticket
from app.orchestrator.pipeline import Pipeline, ProgressEvent


def _parse_args(argv: list[str]) -> dict[str, str]:
    args: dict[str, str] = {}
    i = 0
    while i < len(argv):
        if argv[i] in ("--logs", "--ticket", "--case-id"):
            args[argv[i]] = argv[i + 1]
            i += 2
        else:
            i += 1
    return args


def _progress(ev: ProgressEvent) -> None:
    print(f"  [{ev.percent:5.0f}%] {ev.phase:14s} {ev.status:12s} {ev.message}")


def main(argv: list[str] | None = None) -> None:
    setup_logging()
    raw = argv if argv is not None else sys.argv[1:]
    args = _parse_args(raw)

    logs_glob = args.get("--logs", "samples/checkout-incident/*.log")
    ticket_path = args.get("--ticket", "samples/checkout-incident/ticket.json")
    case_id = args.get("--case-id") or f"CASE-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    # Expandir glob
    log_files = sorted(Path().glob(logs_glob)) if "*" in logs_glob else [Path(logs_glob)]
    if not log_files:
        print(f"ERROR: no se encontraron logs en {logs_glob}")
        sys.exit(1)

    # Cargar ticket
    ticket_data = json.loads(Path(ticket_path).read_text(encoding="utf-8"))
    ticket = Ticket.model_validate(ticket_data)

    print(f"Caso: {case_id}")
    print(f"Logs: {len(log_files)} archivos")
    print(f"Ticket: {ticket.ticket_id} - {ticket.application}")
    print()

    pipeline = Pipeline(progress_cb=_progress)
    case = pipeline.run(case_id, log_files, ticket)

    print()
    print(f"Status: {case.status}")
    print(f"Expediente: cases/{case_id}/case.json")
    for name, phase in case.phases.items():
        print(f"  {name:14s} {phase.status}")


if __name__ == "__main__":
    main()
