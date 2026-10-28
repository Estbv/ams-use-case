"""Configuracion de logging estandar de Python.

El formato incluye el ID del caso y la fase en curso, propagados via
contextvars para que funcionen correctamente con concurrencia (asyncio / hilos
de la ingesta en paralelo).
"""
from __future__ import annotations

import logging
import sys
from contextvars import ContextVar
from typing import ContextManager

# Contexto por caso/fase. Valores por defecto neutros.
case_id_var: ContextVar[str] = ContextVar("case_id", default="-")
phase_var: ContextVar[str] = ContextVar("phase", default="-")

_LOG_FORMAT = (
    "%(asctime)s | %(levelname)-7s | case=%(case_id)s | phase=%(phase)s "
    "| %(name)s | %(message)s"
)


class _CaseContextFilter(logging.Filter):
    """Inyecta case_id y phase en cada registro de log."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.case_id = case_id_var.get()
        record.phase = phase_var.get()
        return True


def setup_logging(level: str | int = logging.INFO) -> None:
    """Configura el logger raiz con el formato del proyecto.

    Idempotente: limpia handlers previos para no duplicar lineas.
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    handler.addFilter(_CaseContextFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
    root.addFilter(_CaseContextFilter())


def get_logger(name: str) -> logging.Logger:
    """Devuelve un logger con el nombre dado."""
    return logging.getLogger(name)


def bind_context(case_id: str, phase: str = "-") -> ContextManager[None]:
    """Context manager que fija case_id y phase mientras dura el bloque.

    Uso:
        with bind_context("CASE-001", "triage"):
            logger.info("analizando evidencia")
    """
    from contextlib import contextmanager

    @contextmanager
    def _ctx():
        t_case = case_id_var.set(case_id)
        t_phase = phase_var.set(phase)
        try:
            yield
        finally:
            case_id_var.reset(t_case)
            phase_var.reset(t_phase)

    return _ctx()
