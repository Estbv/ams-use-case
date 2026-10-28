"""Almacenamiento del expediente (Case) con escritura atomica."""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import settings
from app.logging_config import get_logger
from app.models.case import Case

logger = get_logger(__name__)


def _cases_root() -> Path:
    return Path(settings.CASES_DIR)


def case_dir(case_id: str) -> Path:
    return _cases_root() / case_id


def logs_dir(case_id: str) -> Path:
    return case_dir(case_id) / "logs"


def save_case(case: Case) -> Path:
    """Guarda el expediente como JSON con escritura atomica."""
    d = case_dir(case.id)
    d.mkdir(parents=True, exist_ok=True)

    target = d / "case.json"
    tmp = d / "case.json.tmp"

    data = case.model_dump_json(indent=2)
    tmp.write_text(data, encoding="utf-8")
    os.replace(tmp, target)  # atomic

    logger.info("Expediente guardado: %s", target)
    return target


def load_case(case_id: str) -> Case:
    """Carga un expediente desde CASES_DIR/<case_id>/case.json."""
    path = case_dir(case_id) / "case.json"
    if not path.exists():
        raise FileNotFoundError(f"no existe el expediente {case_id}")
    data = json.loads(path.read_text(encoding="utf-8"))
    return Case.model_validate(data)


def save_raw_logs(case_id: str, log_files: list[Path]) -> Path:
    """Copia los logs originales a CASES_DIR/<case_id>/logs/."""
    d = logs_dir(case_id)
    d.mkdir(parents=True, exist_ok=True)
    for src in log_files:
        dst = d / src.name
        dst.write_bytes(src.read_bytes())
    return d


def case_exists(case_id: str) -> bool:
    return (case_dir(case_id) / "case.json").exists()
