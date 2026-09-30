# Copper Market Data Pipeline — contexto para agentes

Repo público de portafolio de J (`munozmartinezja`). Demo: https://copper-market-data-pipeline.onrender.com/

## Qué es
Pipeline Django que ingiere precios diarios OHLCV del futuro del cobre (HG=F) y de 8 instrumentos del sector cobre vía yfinance, los carga de forma idempotente en Postgres (Neon), guarda un reporte de calidad por corrida y genera un resumen en lenguaje natural con LLM y respaldo determinístico.

## Arquitectura en producción
- **Ingesta:** `.github/workflows/scheduled-ingestion.yml` → `python manage.py run_ingestions_now` (síncrono, sin Celery). Escribe directo en Neon. El resumen LLM se genera aquí: toda variable de LLM debe estar en el `env` de este workflow.
- **Web:** Render (plan gratuito), `gunicorn config.wsgi:application`. El build corre `collectstatic` y `migrate`. Health check: `/healthz/` (sin acceso a la base de datos).
- **Keep-alive:** cron-job.org pinguea `/healthz/` cada 10 minutos.
- **Celery / django-celery-beat:** implementado y testeado, no desplegado (un worker 24/7 no entra en el free tier).

## Modelo de datos (app `ingestion`)
- `DataSource(name, type, config_json, active)`
- `IngestionRun(source, status, rows_ingested, rows_created, rows_updated, ticker_stats, errors_json, summary, started_at, finished_at)`
  - `ticker_stats`: `{ticker: {created, updated, errors}}`, capturado en la corrida (migración 0005). Es la fuente de verdad de `quality_report()`.
  - Corridas sin `ticker_stats` son `legacy`: el reporte las marca `legacy: true` y el resumen de respaldo no inventa detalle.
- `PriceRecord(source, ingestion_run, ticker, date, OHLCV)`, único por (source, ticker, date). `update_or_create` reasigna `ingestion_run` a la última corrida: **no derivar métricas históricas desde `price_records`**.

## Reglas de trabajo
1. Antes de cualquier comando git: `pwd`, `git branch --show-current`, `git remote -v`.
2. Cambios siempre en una rama con PR hacia `main`. **Nunca merge**: lo hace J después de revisión.
3. Un commit por cambio lógico (conventional commits), cada uno con tests.
4. Tests: `pytest --cov` (pytest-django, `--reuse-db` por defecto; `--create-db` si cambian modelos). Mockear red (yfinance, LLM) y `sleep`.
5. Antes del PR: `python manage.py makemigrations --check --dry-run` limpio.
6. "Terminado" = PR abierto + workflow **Tests** en verde + reporte con el total de tests y el % de cobertura real.
7. Toda migración nueva se aplica en producción vía el build de Render al hacer merge: debe ser segura sobre datos existentes (AddField con default, sin locks largos).
8. Sin secretos en código, logs ni commits. Config solo por variables de entorno (`python-decouple`).
9. Sin dependencias nuevas salvo que el prompt lo pida explícitamente.
10. No correr comandos que escriban en producción (`backfill_*`, `run_ingestions_now` con el `.env` real) salvo instrucción explícita de J.
11. Prohibido ejecutar migrate, shell o scripts contra hosts neon.tech sin autorización explícita de J.

## Comandos útiles
- `python manage.py run_ingestions_now`: ingesta síncrona de todas las fuentes activas.
- `python manage.py backfill_run_summaries`: rellena resúmenes vacíos con el respaldo determinístico (idempotente).
- `python manage.py ingest_source <nombre>`: ingesta de una fuente.
