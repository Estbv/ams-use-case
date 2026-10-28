"""Clase base Tool: interfaz compatible con OpenAI function calling y MCP."""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Tool(ABC):
    """Tool de solo lectura. Subclases implementan run()."""

    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)

    @abstractmethod
    def run(self, args: dict[str, Any], case: Any = None) -> dict[str, Any]:
        """Ejecuta la tool. Devuelve siempre un dict, nunca lanza."""
        ...

    # -- esquemas -----------------------------------------------------------

    def to_openai_schema(self) -> dict[str, Any]:
        """Formato de function calling de OpenAI / MaaS (seccion 5)."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def to_mcp_schema(self) -> dict[str, Any]:
        """Formato de definicion de tool de MCP (name, description, inputSchema)."""
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.parameters,
        }
