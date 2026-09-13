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

## Tests
```bash
pytest --cov
```

## Roadmap futuro
- [ ] Agregar fuente de datos de commodities (cobre) relevante para minería
- [ ] Dashboard de calidad de datos con series históricas de completitud
- [ ] Alertas automáticas cuando una fuente falla 2+ veces seguidas
