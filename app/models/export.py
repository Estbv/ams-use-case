"""Exporta el JSON Schema de cada modelo de agente.

Uso: python -m app.models.export
Genera app/models/schemas/<agente>.json
"""
from __future__ import annotations

import json
from pathlib import Path

from app.models.agents import (
    CommunicationOutput,
    IngestOutput,
    RcaOutput,
    ResolutionOutput,
    TriageOutput,
)

SCHEMA_DIR = Path(__file__).parent / "schemas"

MODELS = {
    "ingest": IngestOutput,
    "triage": TriageOutput,
    "root_cause": RcaOutput,
    "resolution": ResolutionOutput,
    "communication": CommunicationOutput,
}


def export_all(out_dir: Path | None = None) -> list[Path]:
    """Exporta todos los esquemas. Devuelve la lista de archivos generados."""
    target = out_dir or SCHEMA_DIR
    target.mkdir(parents=True, exist_ok=True)

    generated: list[Path] = []
    for name, model in MODELS.items():
        schema = model.model_json_schema()
        path = target / f"{name}.json"
        path.write_text(json.dumps(schema, indent=2, ensure_ascii=False), encoding="utf-8")
        generated.append(path)
        print(f"  {path}")

    return generated


def main() -> None:
    print(f"Exportando esquemas a {SCHEMA_DIR}...")
    generated = export_all()
    print(f"OK: {len(generated)} esquemas generados.")


if __name__ == "__main__":
    main()
