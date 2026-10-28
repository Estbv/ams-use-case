# AMS Agentes

Analisis de logs de incidentes con agentes LLM (Huawei Cloud MaaS / GLM).

La aplicacion procesa los logs de un incidente con un flujo de 5 agentes
que usan el modelo GLM en Huawei Cloud MaaS, y produce un reporte HTML
con la causa raiz, el plan de accion y las comunicaciones listas para enviar.

---

## Arquitectura

```
                      ORQUESTADOR (codigo, no LLM): estado del caso, validacion, reintentos, auditoria
                      ──────────────────────────────────────────────────────────────────────────────
 logs ─► [0. Preproceso local, sin IA]  parseo - enmascarado - agrupacion en firmas - IDs E001..
               |
               ├──► Agente de Ingesta (fuente 1) ─┐
               ├──► Agente de Ingesta (fuente 2) ─┼─ EN PARALELO ─► [Fusion en codigo: linea de tiempo unica]
               └──► Agente de Ingesta (fuente N) ─┘
                                                           |
                                                  Agente de Triage
                                                           |
                                                  Agente de Causa Raiz ◄── tools: problemas conocidos,
                                                           |                     detalle de evidencia, cambios
                                           [Revision humana opcional si la confianza es baja]
                                                           |
                                                  Agente de Resolucion ◄── tools: runbooks, calendario de cambios
                                                           |
                                                  Agente de Comunicacion
                                                           |
                                                    Reporte (HTML / JSON / ticket)
```

### Las 5 fases

| Fase | Agente | Que hace | Tools |
|------|--------|----------|-------|
| 0 | Preproceso (codigo) | Parseo, enmascarado, firmas, IDs E001.. | - |
| 1 | Ingesta (xN, en paralelo) | Clasifica evidencia por fuente | ninguna |
| 2 | Triage | Severidad, primera anomalia, temas, linea de tiempo | get_evidence_detail |
| 3 | Causa Raiz | Hipotesis, causa probable, comprobaciones | search_known_issues, get_evidence_detail, get_recent_changes |
| 4a | Resolucion | Plan de mitigacion y solucion definitiva | search_runbooks, get_change_calendar |
| 4b | Comunicacion | Nota de ticket, comunicado, escalamiento, runbook | ninguna |

---

## Instalacion

### Requisitos

- Python 3.11+ (probado con 3.13.14)
- pip

### Pasos

```powershell
cd ams-agentes

# Crear entorno virtual
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Instalar dependencias
pip install -r requirements.txt
```

---

## Configuracion

Copia `.env.example` a `.env` y completa los valores:

```powershell
Copy-Item .env.example .env
```

| Variable | Por defecto | Descripcion |
|----------|-------------|-------------|
| `MAAS_ENDPOINT` | `https://api-ap-southeast-1.modelarts-maas.com/v2/chat/completions` | Endpoint de MaaS (compatible con OpenAI) |
| `MAAS_MODEL` | (vacio) | Nombre del modelo GLM desplegado en MaaS |
| `MAAS_API_KEY` | (vacio) | API key de MaaS. **No la subas al repositorio.** |
| `MAAS_TIMEOUT` | `300` | Timeout HTTP en segundos |
| `MAAS_TEMPERATURE` | `0.2` | Temperatura del modelo (0.1 - 0.2 recomendado) |
| `MAAS_VERIFY_SSL` | `true` | Verificar certificado SSL |
| `LLM_MODE` | `maas` | `maas` = llamadas reales, `fake` = respuestas simuladas para pruebas |
| `INGEST_CONCURRENCY` | `4` | Concurrencia maxima para la ingesta por fuente |
| `MAX_TOOL_CALLS` | `5` | Maximo de llamadas a tools por agente |
| `HUMAN_REVIEW` | `pause` | `pause` = detener antes de Resolucion si `needs_human_review`, `continue` = seguir |
| `CASES_DIR` | `cases` | Directorio donde se guardan los expedientes |

---

## Ejecucion

### Local (modo real)

```powershell
# Con .env configurado con MAAS_API_KEY y MAAS_MODEL
python -m uvicorn app.main:app --reload
# Abrir http://localhost:8000
```

### Local (modo fake, sin clave)

```powershell
$env:LLM_MODE="fake"
python -m uvicorn app.main:app --reload
```

### CLI (flujo completo sin interfaz web)

```powershell
# Con FakeClient
$env:LLM_MODE="fake"
python -m app.orchestrator.run --logs "samples/checkout-incident/*.log" --ticket samples/checkout-incident/ticket.json

# Con MaaS real
python -m app.orchestrator.run --logs "samples/checkout-incident/*.log" --ticket samples/checkout-incident/ticket.json
```

### Docker

```powershell
docker compose up --build
# Abrir http://localhost:8000
```

---

## Despliegue en Huawei Cloud

### Opcion A: ECS (Elastic Cloud Server)

1. **Construir y subir la imagen a SWR (Software Repository for Containers):**

```bash
# En tu maquina local
docker build -t ams-agentes:latest .

# Etiquetar para SWR
docker tag ams-agentes:latest <region>.swr.myhuaweicloud.com/<organization>/ams-agentes:latest

# Iniciar sesion en SWR
docker login <region>.swr.myhuaweicloud.com

# Subir la imagen
docker push <region>.swr.myhuaweicloud.com/<organization>/ams-agentes:latest
```

2. **Crear una ECS** con Docker instalado (Ubuntu 22.04 o superior).

3. **Desplegar el contenedor:**

```bash
# Iniciar sesion en SWR desde la ECS
docker login <region>.swr.myhuaweicloud.com

# Descargar la imagen
docker pull <region>.swr.myhuaweicloud.com/<organization>/ams-agentes:latest

# Ejecutar con variables de entorno como secretos
docker run -d \
  --name ams-agentes \
  -p 8000:8000 \
  -v /opt/ams/cases:/app/cases \
  -e MAAS_API_KEY=$(cat /opt/ams/secrets/maas_key) \
  -e MAAS_MODEL=glm-5.2 \
  -e MAAS_ENDPOINT=https://api-ap-southeast-1.modelarts-maas.com/v2/chat/completions \
  -e LLM_MODE=maas \
  --restart unless-stopped \
  <region>.swr.myhuaweicloud.com/<organization>/ams-agentes:latest
```

4. **Configurar el grupo de seguridad** para abrir el puerto 8000 (o el puerto detras de un balanceador).

### Opcion B: CCE (Cloud Container Engine)

1. Subir la imagen a SWR (igual que arriba).
2. Crear un workload de Deployment en CCE.
3. Configurar las variables de entorno como **Secrets** de CCE (no como texto plano):
   - `MAAS_API_KEY` -> Secret
   - `MAAS_MODEL` -> ConfigMap
   - `MAAS_ENDPOINT` -> ConfigMap
4. Montar un PVC (PersistentVolumeClaim) para `/app/cases`.
5. Exponer el servicio via LoadBalancer o Ingress.

### Importante: la clave nunca va en la imagen

La `MAAS_API_KEY` se inyecta siempre como variable de entorno o secret en runtime.
**Nunca** se copia en el Dockerfile ni en la imagen.

---

## Como agregar datos

### Agregar un problema conocido

Edita `data/known_issues.json`:

```json
[
  {
    "id": "KI-007",
    "title": "Mi nuevo problema",
    "pattern": "texto del patron|regex opcional",
    "guidance": "Que hacer cuando aparece este patron."
  }
]
```

### Agregar un runbook

Crea un archivo Markdown en `data/runbooks/`:

```markdown
# Titulo del runbook

## Sintomas
- Sintoma 1
- Sintoma 2

## Diagnostico
1. Paso 1
2. Paso 2

## Resolucion
- Accion 1
- Accion 2
```

El agente de Resolucion lo encontrara via `search_runbooks`.

### Agregar una regla de enmascarado

Edita `data/masking_rules.json`:

```json
[
  {"pattern": "mi-patron-sensible-\\d+", "replacement": "[REDACTED]"}
]
```

Las reglas son regex de Python aplicadas despues del enmascarado estandar.

---

## Como modificar el prompt de un agente

Los prompts estan en `app/prompts/<agente>/`:

```
app/prompts/
  common_rules.md        # Reglas comunes a todos los agentes
  correction.md          # Mensaje de correccion (reintento)
  ingest/
    system.md            # Prompt de sistema del agente de Ingesta
    user.md              # Plantilla del mensaje de usuario
    meta.json            # Version y metadatos
  triage/
    system.md  user.md  meta.json
  root_cause/
    system.md  user.md  meta.json
  resolution/
    system.md  user.md  meta.json
  communication/
    system.md  user.md  meta.json
```

1. Edita `system.md` o `user.md` del agente que quieres cambiar.
2. Incrementa la version en `meta.json`:
   ```json
   {"version": "2", "agent": "triage", "tools": ["get_evidence_detail"]}
   ```
3. Los placeholders `{{...}}` en `user.md` se reemplazan por el orquestador.
4. `{{REGLAS_COMUNES}}` en `system.md` se reemplaza por `common_rules.md`.

### Probar un agente individual

```powershell
# Modo fake
$env:LLM_MODE="fake"
python -m app.agents.ingest samples/checkout-incident/oracle-db-monitor.log

# Modo real
python -m app.agents.ingest samples/checkout-incident/oracle-db-monitor.log
```

---

## Como pasar una tool a un servidor MCP

Cada tool tiene `to_mcp_schema()` que genera el esquema compatible con MCP:

```python
from app.tools.known_issues import SearchKnownIssues

tool = SearchKnownIssues()
mcp_schema = tool.to_mcp_schema()
# {
#   "name": "search_known_issues",
#   "description": "Busca en la base de problemas conocidos...",
#   "inputSchema": {"type": "object", "properties": {"query": ...}, "required": ["query"]}
# }
```

Para migrar a un servidor MCP:

1. Crea un servidor MCP que exponga la tool con el esquema de `to_mcp_schema()`.
2. Cambia el `executor()` en `app/tools/registry.py` para que llame al servidor MCP.
3. Los prompts no cambian: la interfaz de la tool es la misma.

---

## Pruebas

```powershell
# Tests unitarios y de integracion (sin MaaS real)
python -m pytest

# Tests end-to-end con MaaS real (requiere MAAS_API_KEY)
$env:MAAS_API_KEY="<tu-clave>"
$env:MAAS_MODEL="glm-5.2"
python -m pytest -m e2e -v

# Solo un modulo
python -m pytest tests/test_api.py -v
```

---

## Limitaciones conocidas

- **El enmascarado no sustituye la politica de datos de la empresa.** Es una capa
  adicional de proteccion, no la unica. Revisa los logs antes de subirlos.
- **Los resultados del modelo son propuestas, no verdades.** Un ingeniero debe
  revisar la causa raiz y el plan antes de ejecutarlos.
- **Las tools son de solo lectura.** Ningun agente ejecuta cambios en produccion.
- **El modo fake** usa respuestas simuladas y no refleja la calidad del modelo real.
- **El preproceso** detecta 5 formatos de timestamp. Logs con formatos no reconocidos
  se procesan sin hora (time_first = "Desconocido").
- **La ingesta en paralelo** usa un ThreadPoolExecutor con `INGEST_CONCURRENCY` workers.

---

## Buenas practicas

1. **Revisa los resultados antes de actuar.** El modelo puede equivocarse.
2. **Usa `HUMAN_REVIEW=pause`** en produccion para revisar causas de baja confianza.
3. **No expongas la clave de MaaS** en logs, imagenes ni repositorios.
4. **Audita las llamadas.** El expediente guarda prompts, respuestas, tokens y tiempos.
5. **Mantén actualizada la base de problemas conocidos** (`data/known_issues.json`).
6. **El enmascarado no sustituye la politica de datos de la empresa.**
