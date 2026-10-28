"""Modelo del ticket del incidente."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class Ticket(BaseModel):
    """Ticket del incidente, entrada del flujo."""

    ticket_id: str = Field(..., description="Identificador del ticket, p. ej. INC-2026-10482")
    application: str = Field(..., description="Aplicacion afectada")
    reported_at: Optional[str] = Field(None, description="Fecha/hora de reporte")
    description: str = Field("", description="Descripcion del incidente")
    recent_changes: Optional[str] = Field(None, description="Cambios recientes")
    environment: Optional[str] = Field(None, description="Entorno tecnologico")
    business_rules: Optional[str] = Field(None, description="Reglas de negocio")
