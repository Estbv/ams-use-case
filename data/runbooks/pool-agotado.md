# Pool de conexiones agotado (HikariCP)

## Sintomas
- Mensaje "Connection is not available, request timed out after 30000ms"
- Pool monitor muestra active=max, idle=0, waiting>0
- Errores 500/504 en los endpoints que usan la base de datos

## Diagnostico
1. Revisar si hay SQL de larga duracion (full scan, queries sin indice)
2. Verificar si una migracion Flyway fallo y dejo indices sin crear
3. Comprobar si un job programado (BATCH_ARCHIVE) tiene locks exclusivos

## Resolucion inmediata
1. Desactivar el feature flag que dispara el query lento
2. NO aumentar el tamano del pool: es un sintoma, no la causa

## Solucion definitiva
1. Recrear el indice faltante
2. Activar spring.flyway.fail-on-error=true
3. Revisar el plan de ejecucion del query con EXPLAIN PLAN

## Prevencion
- Monitorear migraciones Flyway con fail-on-error=true
- Alertar si elapsed > 1000ms en queries de checkout
