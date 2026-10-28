# session-service-incident

Caso de prueba para comparar el desempeno de modelos LLM en AMS Agentes.

## Escenario

**Servicio afectado:** `session-service` (validacion de sesiones de usuario)
**Sintoma:** Los usuarios no pueden iniciar sesion ni validar sesiones activas.
**Severidad:** Critical (afecta autenticacion)

## Causa raiz conocida

El despliegue v3.2.0 (CHG-77231) introdujo un **connection leak** en la clase
`ParallelSessionValidator`. El nuevo codigo adquiere conexiones Redis para
validacion paralela pero nunca las libera al pool. Las conexiones se acumulan
hasta agotar el pool (maxTotal=50), provocando que todas las validaciones
fallen con `Could not get a resource from the pool`.

## Red herrings (pistas enganosas)

Un buen modelo debe identificar la causa raiz y NO confundirse con:

1. **Redis memory al 85%** - sintoma del leak, no causa
2. **Connected clients subiendo a 9987** - consecuencia del leak
3. **BGSAVE a las 10:00** - completa normalmente en 2.3s, sin correlacion
4. **Slow Redis operations** - causadas por pool casi agotado, no por Redis lento
5. **maxclients reached en Redis** - consecuencia, no causa

## Archivos

| Archivo | Descripcion |
|---------|-------------|
| `session-service.log` | Logs de la aplicacion Java (Spring Boot) |
| `redis-server.log` | Logs del servidor Redis 7.2.1 |
| `nginx-access.log` | Access logs del Nginx gateway |
| `nginx-error.log` | Error logs del Nginx gateway |
| `ticket.json` | Ticket del incidente |
| `ground_truth.json` | Causa raiz, hipotesis, verificaciones y criterios de scoring |

## Como comparar dos modelos

```powershell
# Modelo A
$env:MAAS_MODEL="glm-4"
$env:MAAS_API_KEY="<clave>"
python -m app.orchestrator.run --logs "samples/session-service-incident/*.log" --ticket samples/session-service-incident/ticket.json

# Modelo B
$env:MAAS_MODEL="glm-5.2"
python -m app.orchestrator.run --logs "samples/session-service-incident/*.log" --ticket samples/session-service-incident/ticket.json
```

Luego comparar el `most_likely_root_cause` de cada resultado contra `ground_truth.json`.

## Criterios de evaluacion

El `ground_truth.json` incluye una seccion `scoring` con:

- **must_identify:** puntos que el modelo DEBE identificar para considerar correcta
  la causa raiz (connection leak, ParallelSessionValidator, CHG-77231, pool exhaustion)
- **must_not_confuse_with:** errores comunes que indican que el modelo se equivoco
  (Redis down, network issue, BGSAVE, traffic spike)
- **partial_credit_for:** identificaciones parciales que merecen credito parcial
