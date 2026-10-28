"""Cliente de Huawei Cloud MaaS (endpoint compatible con OpenAI).

Usa MAAS_ENDPOINT, MAAS_MODEL y MAAS_API_KEY de la configuracion.
Nunca registra la clave en logs ni errores.
"""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from typing import Any

import requests

from app.config import settings
from app.logging_config import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Excepciones y resultados
# ---------------------------------------------------------------------------

class MaaSError(Exception):
    """Error de comunicacion con MaaS."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        retryable: bool = False,
    ):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.retryable = retryable


@dataclass
class ChatResult:
    """Resultado de una llamada chat."""

    content: str | None
    tool_calls: list[dict] | None = None
    tokens: dict[str, int] = field(default_factory=dict)
    duration: float = 0.0
    raw: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Cliente
# ---------------------------------------------------------------------------

class MaaSClient:
    """Cliente para el endpoint de chat completions de MaaS."""

    def __init__(
        self,
        endpoint: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        timeout: int | None = None,
        temperature: float | None = None,
        verify_ssl: bool | None = None,
    ) -> None:
        self.endpoint = endpoint or settings.MAAS_ENDPOINT
        self.model = model or settings.MAAS_MODEL
        self.api_key = api_key or settings.MAAS_API_KEY
        self.timeout = timeout if timeout is not None else settings.MAAS_TIMEOUT
        self.temperature = (
            temperature if temperature is not None else settings.MAAS_TEMPERATURE
        )
        self.verify_ssl = (
            verify_ssl if verify_ssl is not None else settings.MAAS_VERIFY_SSL
        )

    # -- nucleo -------------------------------------------------------------

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> ChatResult:
        """Llama al modelo y devuelve contenido, tool_calls, tokens y duracion."""
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        data: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
        }
        if tools is not None:
            data["tools"] = tools

        return self._post_with_retry(headers, data)

    # -- reintentos para 429 / 5xx / timeout --------------------------------

    def _post_with_retry(
        self,
        headers: dict[str, str],
        data: dict[str, Any],
        max_retries: int = 2,
    ) -> ChatResult:
        last_error: MaaSError | None = None

        for attempt in range(max_retries + 1):
            try:
                start = time.time()
                response = requests.post(
                    self.endpoint,
                    headers=headers,
                    json=data,
                    timeout=self.timeout,
                    verify=self.verify_ssl,
                )
                duration = time.time() - start
                return self._handle_response(response, duration)

            except requests.Timeout:
                last_error = MaaSError(
                    f"Timeout despues de {self.timeout}s.",
                    status_code=None,
                    retryable=True,
                )
            except requests.ConnectionError as exc:
                last_error = MaaSError(
                    f"Error de conexion: {exc}",
                    status_code=None,
                    retryable=True,
                )

            if attempt < max_retries and last_error is not None and last_error.retryable:
                wait = 2 ** attempt
                logger.warning(
                    "Reintento %d/%d tras error en %.1fs...",
                    attempt + 1, max_retries, wait,
                )
                time.sleep(wait)
            else:
                break

        assert last_error is not None
        raise last_error

    # -- respuesta ----------------------------------------------------------

    def _handle_response(self, response: requests.Response, duration: float) -> ChatResult:
        status = response.status_code

        if status == 200:
            return self._parse_response(response, duration)

        if status in (401, 403):
            raise MaaSError(
                f"Error de autenticacion (HTTP {status}): "
                "verifica MAAS_API_KEY.",
                status_code=status,
                retryable=False,
            )
        if status == 404:
            raise MaaSError(
                "Endpoint o modelo no encontrado (HTTP 404): "
                "verifica MAAS_ENDPOINT y MAAS_MODEL.",
                status_code=404,
                retryable=False,
            )
        if status == 429:
            raise MaaSError(
                "Limite de peticiones excedido (HTTP 429).",
                status_code=429,
                retryable=True,
            )
        if status >= 500:
            raise MaaSError(
                f"Error del servidor (HTTP {status}).",
                status_code=status,
                retryable=True,
            )

        # 4xx incluido 400
        raise MaaSError(
            f"Error HTTP {status}: {response.text[:300]}",
            status_code=status,
            retryable=False,
        )

    def _parse_response(self, response: requests.Response, duration: float) -> ChatResult:
        body = response.json()
        choices = body.get("choices", [])
        if not choices:
            raise MaaSError("Respuesta sin choices.", status_code=200)

        message = choices[0].get("message", {})
        content = message.get("content")
        tool_calls = message.get("tool_calls")

        usage = body.get("usage", {})
        tokens = {
            "prompt": usage.get("prompt_tokens", 0),
            "completion": usage.get("completion_tokens", 0),
            "total": usage.get("total_tokens", 0),
        }

        return ChatResult(
            content=content,
            tool_calls=tool_calls,
            tokens=tokens,
            duration=duration,
            raw=body,
        )


# ---------------------------------------------------------------------------
# Entry point: python -m app.llm.maas_client "Hola"
# ---------------------------------------------------------------------------

def _main() -> None:
    from app.config import validate_llm_settings
    from app.logging_config import setup_logging

    setup_logging()
    errors = validate_llm_settings()
    if errors:
        for e in errors:
            print(f"ERROR: {e}")
        sys.exit(1)

    text = sys.argv[1] if len(sys.argv) > 1 else "Hola"
    client = MaaSClient()
    result = client.chat([{"role": "user", "content": text}])
    print(result.content)
    print(f"Tokens: {result.tokens}")


if __name__ == "__main__":
    _main()
