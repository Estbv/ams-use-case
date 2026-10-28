"""Configuracion central de la aplicacion, leida desde variables de entorno.

Usa pydantic-settings para validar y tipar. La configuracion se carga siempre
incluso sin MAAS_API_KEY; la validacion de requisitos para ejecutar un caso se
delega a `validate_llm_settings()`.
"""
from __future__ import annotations

from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Ajustes de la aplicacion AMS Agentes."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    # --- Huawei Cloud MaaS (GLM) ---
    MAAS_ENDPOINT: str = (
        "https://api-ap-southeast-1.modelarts-maas.com/v2/chat/completions"
    )
    MAAS_MODEL: str = ""
    MAAS_API_KEY: str = ""
    MAAS_TIMEOUT: int = 300
    MAAS_TEMPERATURE: float = 0.2
    MAAS_VERIFY_SSL: bool = True

    # --- Modo de LLM ---
    # maas = llamadas reales a MaaS | fake = respuestas simuladas para pruebas
    LLM_MODE: Literal["maas", "fake"] = "maas"

    # --- Orquestador ---
    INGEST_CONCURRENCY: int = 4
    MAX_TOOL_CALLS: int = 5
    HUMAN_REVIEW: Literal["pause", "continue"] = "pause"

    # --- Expedientes ---
    CASES_DIR: str = "cases"

    @field_validator("MAAS_TEMPERATURE")
    @classmethod
    def _check_temperature(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("MAAS_TEMPERATURE debe estar entre 0.0 y 1.0")
        return v

    @field_validator("MAAS_TIMEOUT")
    @classmethod
    def _check_timeout(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("MAAS_TIMEOUT debe ser un entero positivo")
        return v

    @field_validator("INGEST_CONCURRENCY")
    @classmethod
    def _check_concurrency(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("INGEST_CONCURRENCY debe ser un entero positivo")
        return v

    @field_validator("MAX_TOOL_CALLS")
    @classmethod
    def _check_max_tool_calls(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("MAX_TOOL_CALLS debe ser un entero positivo")
        return v


# Instancia singleton cargada al importar el modulo.
settings = Settings()


def validate_llm_settings() -> list[str]:
    """Comprueba que los ajustes de LLM sean suficientes para ejecutar un caso.

    Devuelve una lista de mensajes de error. Si la lista es vacia, la
    configuracion es valida. En modo `fake` no se requiere API key ni modelo.
    """
    errors: list[str] = []

    if settings.LLM_MODE == "fake":
        return errors

    if not settings.MAAS_API_KEY:
        errors.append(
            "MAAS_API_KEY no esta configurada. Define MAAS_API_KEY en el entorno "
            "o usa LLM_MODE=fake para ejecutar pruebas sin clave."
        )
    if not settings.MAAS_MODEL:
        errors.append(
            "MAAS_MODEL no esta configurado. Define MAAS_MODEL con el nombre del "
            "modelo GLM desplegado en MaaS."
        )
    if not settings.MAAS_ENDPOINT:
        errors.append("MAAS_ENDPOINT no esta configurado.")

    return errors
