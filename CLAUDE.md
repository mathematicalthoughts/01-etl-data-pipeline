# ETL / Data Pipeline App — contexto del proyecto

Repo 1 de 3 del portafolio. Ver `../CLAUDE.md` y `../PORTFOLIO_ROADMAP.md` para el contexto completo. Este archivo es el detalle específico de este proyecto.

## Problema que resuelve
Centralizar y limpiar datos de múltiples fuentes (precios de acciones, commodities relevantes para minería, indicadores macro) en un solo modelo consultable, con observabilidad de calidad de datos.

## Stack de este repo
- Django + DRF
- Celery + django-celery-beat (scheduling) — Redis como broker (Render free Key-Value)
- pandas para transformación/validación
- Neon Postgres (DATABASE_URL vía variable de entorno, nunca hardcodeada)
- Gemini API para el resumen en lenguaje natural de cada corrida

## Modelo de datos (referencia, ajustar según se construya)
- `DataSource(name, type, config_json, active)`
- `IngestionRun(source, status, rows_ingested, errors_json, started_at, finished_at)`
- `RawRecord` / `CleanRecord`

## Apps Django sugeridas
`ingestion`, `quality`, `api`

## Endpoints principales
- `GET /api/runs/`
- `GET /api/runs/{id}/quality-report/`
- `POST /api/sources/{id}/trigger/`

## Flujo del agente de IA
Al finalizar cada `IngestionRun`, un job dispara un resumen en lenguaje natural del run (tasa de éxito, anomalías, filas afectadas) vía Gemini, y lo adjunta al run.

## Definición de "listo para entrevista" (Fase 4)
- Tests con pytest-django cubriendo la lógica de validación/limpieza (no solo happy path).
- CI en GitHub Actions corriendo tests en cada push.
- Deploy activo en Render con al menos una fuente de datos real ingiriendo en cron.
- README con demo/GIF, arquitectura, decisiones técnicas y roadmap futuro.

## Primer prompt sugerido para arrancar
"Lee CLAUDE.md y ../PORTFOLIO_ROADMAP.md. Arranca el proyecto Django con DRF, configura la conexión a Neon Postgres vía variable de entorno DATABASE_URL, y crea el modelo inicial de DataSource e IngestionRun con su migración. No implementes la ingesta todavía, solo el esqueleto y el admin de Django para poder verificar el modelo."
