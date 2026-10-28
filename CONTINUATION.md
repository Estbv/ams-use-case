# AMS Agentes - Contexto de continuacion

> **Archivo de contexto para continuar el desarrollo en otra sesion.**
> Pegar el contenido de este archivo como primer mensaje del nuevo chat.

---

## ROL

Eres un ingeniero de software senior en Python especializado en aplicaciones backend
con LLM y sistemas multiagente. Ecribes codigo limpio, tipado, modular y listo para
produccion. Respondes en espanol; el codigo, los nombres y los comentarios tecnicos
pueden ir en ingles.

## CONTEXTO GENERAL

Construimos una aplicacion para equipos de Application Managed Services (AMS) que
analiza los logs de un incidente con agentes que usan el modelo GLM en Huawei Cloud
MaaS. La especificacion completa esta en `agentes-backend-prompts-es.md` (fuente de
verdad: arquitectura, contrato del orquestador, reglas comunes, prompts de cada
agente, esquemas de salida y tools). **No cambies los prompts ni los"esquemas de la
especificacion salvo que yo lo pida.**

- **Directorio del proyecto:** `D:\e50065701\Desktop\Esteban\ams-use-case\ams-agentes`
- **Especificacion:** `D:\e50065701\Desktop\Esteban\ams-use-case\agentes-backend-prompts-es.md`
- **AnexoA (logs de ejemplo):** `D:\e50065701\Desktop\Esteban\ams-use-case\AnexoA.txt`
- **Python:** 3.13.14
- **Plataforma:** Windows / PowerShell

## PROGRESO: Pasos 0-8 completados, 94 tests pasan (1 e2e con clave)

### Paso 0 - Esqueleto y configuracion (DONE)
- `app/config.py`: Pydantic Settings (MAAS_ENDPOINT, MAAS_MODEL, MAAS_API_KEY, MAAS_TIMEOUT=300,
  MAAS_TEMPERATURE=0.2, MAAS_VERIFY_SSL=true, LLM_MODE=maas|fake, INGEST_CONCURRENCY=4,
  MAX_TOOL_CALLS=5, HUMAN_REVIEW=pause|continue, CASES_DIR=cases). `validate_llm_settings()`.
- `app/main.py`: FastAPI con `/health`.
- `app/logging_config.py`: logging estandar con `case_id` y `phase` via contextvars.
- `requirements.txt`: fastapi==0.115.6, uvicorn==0.34.0, pydantic==2.10.4, pydantic-settings==2.7.1,
  requests==2.32.3, jinja2==3.1.5, python-multipart==0.0.20, pytest==8.3.4.

### Paso 1 - Preproceso local sin IA (DONE)
- `app/preprocess/parser.py`: Lee logs UTF-8, detecta 5 formatos de timestamp + JSON logs,
  detecta nivel (ERROR/WARN/INFO/DEBUG), une stack traces a la linea anterior.
- `app/preprocess/masking.py`: Enmascara JWT, Bearer, passwords, emails, tarjetas (Luhn),
  ultimo octeto IPv4 (configurable), patrones custom de `data/masking_rules.json`.
- `app/preprocess/signatures.py`: Agrupa mensajes repetidos en firmas, normaliza UUID/hex/num/IDs
  conservando codigos de error (ORA-00054, HTTP 504). Extrae duraciones.
- `app/preprocess/ids.py`: Asigna E001.. globalmente en orden cronologico.
- `app/preprocess/merge.py`: Fusiona resultados de ingesta, rechaza IDs duplicados/desconocidos.
- `app/preprocess/digest.py`: Genera texto `<logs>`, limita INFO rutinarias, estima tokens.
- `app/preprocess/__main__.py`: `python -m app.preprocess samples/checkout-incident`.
- Muestras del AnexoA en `samples/checkout-incident/` (4 logs + ticket.json).
- 3 fuentes: checkout-service (16 firmas), nginx (7), oracle-db-monitor (10). 33 firmas total.

### Paso 2 - Cliente LLM (DONE)
- `app/llm/maas_client.py`: `MaaSClient.chat(messages, tools)` -> `ChatResult(content, tool_calls, tokens, duration)`.
  Reintentos 429/5xx/timeout (2x, backoff exponencial). Errores 401/403/404 no reintentables.
  `python -m app.llm.maas_client "Hola"`.
- `app/llm/json_utils.py`: `clean_response` (quita fences ```json```, bloques, extrae primer JSON).
  `parse_and_validate` (json.loads + Pydantic + comprobacion IDs E\d{3,}).
- `app/llm/tool_loop.py`: `run_with_tools` ejecuta tools en bucle hasta MAX_TOOL_CALLS.
  Plan B: si HTTP 400 al enviar tools, devuelve `context_preloaded=True`.
- `app/llm/retry.py`: `call_agent_with_validation` llama, limpia, valida, reintenta 1 vez con
  mensaje de correccion. Si vuelve a fallar: `status="degraded"` + texto crudo. Auditoria completa.
- `app/llm/fake_client.py`: `FakeClient` con misma interfaz. Lee fixtures de
  `tests/fixtures/fake_responses/<agente>.json` o respuestas explicitas.

### Paso 3 - Modelos de datos (DONE)
- `app/models/agents.py`: 5 modelos Pydantic v2 (`IngestOutput`, `TriageOutput`, `RcaOutput`,
  `ResolutionOutput`, `CommunicationOutput`) con `Literal` para valores permitidos,
  `Optional[str]` para "string o null", `warnings` con `default_factory=list`, validaciones
  (ranks consecutivos, orders consecutivos, `next_update_at` HH:MM) y `cited_ids()`.
- `app/models/case.py`: `Case` (expediente) con `id`, `status`, `ticket`, `evidence`, `triage`,
  `rca`, `plan`, `communications`, `phases` (dict de `PhaseState`), `audit` (lista de `AuditRecord`).
- `app/models/ticket.py`: `Ticket` con campos opcionales.
- `app/models/summaries.py`: `triage_summary()` y `rca_summary()`.
- `app/models/export.py`: `python -m app.models.export` genera JSON Schemas en `app/models/schemas/`.

### Paso 4 - Tools de solo lectura (DONE)
- `app/tools/base.py`: `Tool` (ABC) con `to_openai_schema()` y `to_mcp_schema()`.
- `app/tools/evidence.py`: `GetEvidenceDetail` (max 10 IDs).
- `app/tools/known_issues.py`: `SearchKnownIssues` (regex/titulo/guia, max 5).
- `app/tools/changes.py`: `GetRecentChanges` (data/changes.json + ticket).
- `app/tools/runbooks.py`: `SearchRunbooks` (data/runbooks/*.md).
- `app/tools/calendar.py`: `GetChangeCalendar` (data/calendar.json).
- `app/tools/registry.py`: `TOOLS_BY_AGENT`, `executor()`, `preload()` (plan B).
  - triage -> get_evidence_detail
  - root_cause -> search_known_issues, get_evidence_detail, get_recent_changes
  - resolution -> search_runbooks, get_change_calendar
  - ingest, communication -> ninguna
- Datos: `data/known_issues.json` (KI-001..006), `data/changes.json` (CHG-55821),
  `data/calendar.json` (BATCH_ARCHIVE), `data/runbooks/pool-agotado.md`.

### Paso 5 - Agentes (DONE)
- `app/agents/base.py`: `BaseAgent` carga system.md, reemplaza `{{REGLAS_COMUNES}}`, rellena
  user.md, ejecuta con tools o preload (plan B), guarda prompt final en auditoria.
  `filter_evidence_by_size()` prioriza ERROR > WARN > INFO notable.
- `app/agents/ingest.py`: `IngestAgent` (ticket resumido, fuente, digest). Entry point CLI.
- `app/agents/triage.py`: `TriageAgent` (ticket, evidencia, tendencias).
- `app/agents/rca.py`: `RcaAgent` (ticket, triage, evidencia).
- `app/agents/resolution.py`: `ResolutionAgent` (ticket, triage_summary, rca).
- `app/agents/communication.py`: `CommunicationAgent` (ticket, triage_summary, rca_summary, plan, hora).
- Prompts en `app/prompts/<agente>/system.md` y `user.md` (verbatim de la especificacion).
  `meta.json` por agente. `common_rules.md` y `correction.md`.

### Paso 6 - Orquestador (DONE)
- `app/orchestrator/store.py`: `save_case` (atomica tmp+rename), `load_case`, `save_raw_logs`.
- `app/orchestrator/pipeline.py`: `Pipeline.run(case_id, log_files, ticket)` - flujo secuencial:
  Fase 0 Preproceso -> Fase 1 Ingesta paralela (ThreadPoolExecutor) + merge ->
  Fase 2 Triage -> Fase 3 RCA (posible waiting_review) -> Fase 4a Resolucion ->
  Fase 4b Comunicacion -> completed. `resume(case_id, approved, comment)`.
  Guarda expediente despues de cada fase. Degraded no detiene. Failed detiene.
- `app/orchestrator/run.py`: `python -m app.orchestrator.run --logs "..." --ticket ...`.
- Eventos de progreso con fase, estado, mensaje y porcentaje.

### Paso 7 - Reporte + API Web (DONE)
- `app/report/html.py`: Genera reporte HTML autocontenido (Jinja2, CSS en linea).
  `generate_html_report(case)` y `generate_json_export(case)`.
  Template en `app/report/templates/report.html` con secciones por fase,
  tooltips de IDs de evidencia, botones de copiar, auditoria plegable.
- `app/main.py`: API REST completa con FastAPI:
  - `POST /cases` (multipart: logs + ticket JSON o campos de formulario)
  - `POST /cases/{id}/run` (hilo en segundo plano, devuelve 202)
  - `GET /cases/{id}` (estado del caso y fases)
  - `GET /cases/{id}/events` (SSE progreso en tiempo real)
  - `POST /cases/{id}/review` (revision humana approved/comment)
  - `GET /cases/{id}/report` (HTML autocontenido)
  - `GET /cases/{id}/export` (JSON del expediente sin logs)
  - `GET /cases` (lista de casos)
  - Limites: 50 MB por archivo, solo .log/.txt para logs.
  - Errores en JSON {"error": "...", "detail": "..."}.
  - Cola de eventos por caso para SSE (queue.Queue + threading).
- `app/web/templates/index.html`: Interfaz web con formulario (drag&drop),
  panel de progreso con 6 fases, panel de revision humana, enlaces a reporte/export.
- `app/web/static/app.js`: Logica de UI (fetch, SSE EventSource, drag&drop).
- `app/web/static/style.css`: Estilos en linea.
- `tests/test_api.py`: 19 tests con TestClient + FakeClient cubren
  creacion, ejecucion, estado, revision, reporte, export, lista, errores.
- `requirements.txt`: anadido httpx==0.28.1 para TestClient.

### Paso 8 - E2E, Docker, README, revision final (DONE)
- `tests/e2e/test_checkout_incident.py`: E2E con MaaS real (pytest.mark.e2e).
  Solo corre con MAAS_API_KEY. Comprueba la "clave del facilitador":
  first_anomaly, temas symptom/expected, ruled_out, causa raiz, rejected_quick_fixes,
  mitigacion, y datos sensibles (errores de seguridad).
- `pytest.ini`: marker e2e registrado, addopts `-m "not e2e"`.
- `Dockerfile`: python:3.11-slim, usuario no root, puerto 8000, HEALTHCHECK /health.
- `docker-compose.yml`: volumen cases/, env_file .env.
- `.dockerignore`: excluye tests, .env, cases, etc.
- `README.md`: arquitectura, instalacion, configuracion, ejecucion, Docker,
  despliegue Huawei Cloud (ECS/CCE/SWR), como agregar datos, como modificar prompts,
  como pasar tools a MCP, limitaciones, buenas practicas.
- Revision final: la implementacion cumple la especificacion.
  Prompts verbatim, modelos Pydantic exactos, tools de solo lectura,
  orquestador en codigo, enmascarado antes de agentes, IDs por codigo,
  auditoria completa, revision humana configurable.

## ESTRUCTURA DE ARCHIVOS

```
  ams-agentes/
  .env / .env.example / .gitignore / pytest.ini / requirements.txt
  Dockerfile / docker-compose.yml / .dockerignore / README.md
  app/
    __init__.py / config.py / logging_config.py / main.py
    agents/     __init__.py, base.py, ingest.py, triage.py, rca.py, resolution.py, communication.py
    llm/        __init__.py, maas_client.py, fake_client.py, json_utils.py, tool_loop.py, retry.py
    models/     __init__.py, agents.py, case.py, ticket.py, summaries.py, export.py
                schemas/ (5 JSON schemas exportados)
    preprocess/ __init__.py, __main__.py, parser.py, masking.py, signatures.py, ids.py, merge.py, digest.py
    prompts/    common_rules.md, correction.md
                ingest/ triage/ root_cause/ resolution/ communication/ (system.md, user.md, meta.json c/u)
    tools/      __init__.py, base.py, evidence.py, known_issues.py, changes.py, runbooks.py, calendar.py, registry.py
    orchestrator/ __init__.py, store.py, pipeline.py, run.py
    report/     __init__.py, html.py, templates/report.html
    web/        __init__.py, templates/index.html, static/app.js, static/style.css
  data/         known_issues.json, changes.json, calendar.json, masking_rules.json, runbooks/pool-agotado.md
  samples/checkout-incident/ (4 logs + ticket.json)
  cases/        (expedientes generados, gitignored)
  tests/        test_config.py, test_health.py, test_preprocess.py, test_llm.py, test_models.py,
                test_tools.py, test_agents.py, test_pipeline.py, test_api.py
                e2e/test_checkout_incident.py
                fixtures/fake_responses/ (6 fixtures JSON)
```

## COMANDOS

```powershell
cd D:\e50065701\Desktop\Esteban\ams-use-case\ams-agentes

# Tests (94 pasan, 1 e2e deseleccionado sin clave)
python -m pytest -v

# Tests e2e con MaaS real (requiere MAAS_API_KEY)
$env:MAAS_API_KEY="<tu_clave>"
$env:MAAS_MODEL="glm-5.2"
python -m pytest -m e2e -v -s

# Preproceso solo
python -m app.preprocess samples/checkout-incident

# Flujo completo con FakeClient (sin clave)
$env:LLM_MODE="fake"
python -m app.orchestrator.run --logs "samples/checkout-incident/*.log" --ticket samples/checkout-incident/ticket.json

# Flujo completo con MaaS real (necesita .env con MAAS_API_KEY y MAAS_MODEL)
python -m app.orchestrator.run --logs "samples/checkout-incident/*.log" --ticket samples/checkout-incident/ticket.json

# Servidor FastAPI
python -m uvicorn app.main:app --reload

# Docker
docker compose up --build

# LLM directo
python -m app.llm.maas_client "Hola"

# Agente de ingesta individual
python -m app.agents.ingest samples/checkout-incident/oracle-db-monitor.log
```

## CONFIGURACION (.env)

```env
MAAS_ENDPOINT=https://api-ap-southeast-1.modelarts-maas.com/v2/chat/completions
MAAS_MODEL=glm-5.2
MAAS_API_KEY=<tu_clave>
MAAS_TEMPERATURE=0.2
MAAS_VERIFY_SSL=false
LLM_MODE=maas
```

## QUE FALTA

Nada. La aplicacion esta completa (pasos 0-8).
Mejoras opcionales: SSE con reconexion automatica, mas tests de la interfaz web,
reporte con graficos, export a PDF, pasar tools a servidores MCP reales.

## NOTAS DE IMPLEMENTACION

- Los prompts en `app/prompts/` son copias verbatim de la especificacion. No cambiar.
- Los modelos en `app/models/agents.py` siguen exactamente los esquemas de la seccion 4.
- `FakeClient` detecta el agente por el system prompt (busca "Ingesta", "Triage", etc.).
- Los fixtures de `tests/fixtures/fake_responses/` cumplen los modelos Pydantic.
- El orquestador es en codigo (no LLM): flujo fijo preproceso -> ingesta -> triage -> rca -> resolucion -> comunicacion.
- La ingesta es el unico paso paralelo (ThreadPoolExecutor, INGEST_CONCURRENCY=4).
- Los IDs de evidencia (E001..) los asigna el codigo, no el modelo.
- El enmascarado es en codigo antes de cualquier agente.
- Todas las tools son de solo lectura.
- `HUMAN_REVIEW=pause` detiene el flujo antes de Resolucion si `rca.needs_human_review=True`.
- El logging incluye `case_id` y `phase` via contextvars.
- `uvicorn` no esta en PATH; usar `python -m uvicorn app.main:app`.
