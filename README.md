# ETL / Data Pipeline — Market & Commodities Data

> **Estado:** 🚧 en construcción (Fase 1 del roadmap del portafolio)

<!-- GIF o captura del demo funcionando va aquí -->

## Qué hace
Ingesta, valida y normaliza datos de precios de mercado y commodities desde múltiples fuentes en un solo modelo consultable, con observabilidad de calidad de datos y un resumen en lenguaje natural de cada corrida (generado por IA).

## Demo
🔗 (link al deploy en Render — agregar cuando esté desplegado)

## Arquitectura
<!-- Diagrama simple: fuentes → ingestion → validación/limpieza → API → agente de resumen -->

## Quickstart local
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # completar DATABASE_URL, REDIS_URL, GEMINI_API_KEY
python manage.py migrate
python manage.py runserver
```

## Decisiones técnicas
- **Por qué Neon Postgres y no SQLite:** desde el día 1 el modelo de datos y las validaciones se prueban contra el motor real de producción.
- **Por qué Celery + Redis y no solo cron:** permite reintentos con backoff y visibilidad de estado por corrida, no solo "corrió o no corrió".

### Scheduling: Celery Beat vs GitHub Actions
Este repo tiene **dos mecanismos de scheduling**, a propósito, para dos escenarios distintos:

- **Celery + Redis + django-celery-beat** (`ingestion/tasks.py`, `python manage.py setup_schedule`) es la arquitectura pensada para **producción a escala**: un worker corriendo 24/7 consume la cola, django-celery-beat lee el `PeriodicTask` desde la base de datos (nada hardcodeado en código) y dispara `run_scheduled_ingestions.delay()` cada 4 horas en horario de mercado. Esto da reintentos, colas separadas, visibilidad de tareas en curso y la posibilidad de escalar workers horizontalmente.
- **GitHub Actions** (`.github/workflows/scheduled-ingestion.yml` + `python manage.py run_ingestions_now`) es el **trigger real que efectivamente corre este portafolio**, porque un worker de Celery Beat corriendo 24/7 no entra en el free tier de Render (Render free tier apaga servicios sin tráfico HTTP; un worker en background 24/7 requiere un plan pago). `run_ingestions_now` llama la lógica de `run_scheduled_ingestions()` directamente en el mismo proceso —sin `.delay()`, sin broker, sin worker— así que el único costo es el minuto de ejecución del runner de Actions.
- El cron de GitHub Actions (`schedule:`) corre siempre en **UTC fijo** y no ajusta por horario de verano; el comentario en el workflow documenta el desfase de ~1 hora que esto genera fuera de horario de verano en EE.UU.
- Si en algún momento hay presupuesto para un worker 24/7 (Render pago, Fly.io, etc.), el camino de Celery Beat ya está armado y probado — solo hace falta desplegar el worker y dejar de correr el workflow de Actions.

## Tests
```bash
pytest --cov
```

> **Nota Neon:** el endpoint `-pooler` de Neon puede dejar una conexión colgada que
> bloquea el `DROP DATABASE` de la base de test al finalizar la corrida. Por eso
> `pytest.ini` fija `--reuse-db` por default (reusa la DB de test entre corridas
> en vez de recrearla). Si cambiaste modelos/migraciones, corre
> `pytest --create-db` una vez para forzar la recreación del esquema de test.

## Roadmap futuro
- [ ] Agregar fuente de datos de commodities (cobre) relevante para minería
- [ ] Dashboard de calidad de datos con series históricas de completitud
- [ ] Alertas automáticas cuando una fuente falla 2+ veces seguidas
