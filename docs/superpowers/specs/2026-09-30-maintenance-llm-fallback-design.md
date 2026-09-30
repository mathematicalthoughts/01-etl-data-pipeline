# Maintenance and LLM Fallback Design

## Goal

Make run summaries resilient to Gemini saturation, expose their provenance, update dashboard attribution, modernize CI, and make local tests safe and reproducible.

## Summary provider chain

`generate_run_summary` evaluates configured providers in this order: the primary Gemini model, an optional fallback Gemini model, optional Groq through its OpenAI-compatible HTTP endpoint, then the deterministic summary. Empty configuration values disable optional providers; an empty `GEMINI_MODEL` resolves to the existing default model.

Each network provider receives at most two attempts. HTTP 429, HTTP 5xx, `httpx.TransportError`, and empty response text are transient. Other HTTP 4xx errors immediately advance to the next provider. Retries use a two-second backoff bounded by one shared monotonic deadline so total retry waiting never exceeds 20 seconds. Tests replace both network boundaries and sleep.

Successful summaries persist their provenance as `gemini:<model>`, `groq:<model>`, or `fallback`. Migration `0006` adds the field and classifies existing summaries: deterministic-prefix summaries become `fallback`, other non-empty summaries become `gemini:legacy`, and empty summaries remain empty.

## Dashboard and branding

The latest-summary card derives its heading from `summary_source`. LLM sources render as `Resumen IA - provider/model`; deterministic output renders as `Resumen automatico (sin IA)`. A new 30-day KPI divides runs whose source is neither empty nor `fallback` by all runs in the period. The application shell, title, and navigation use `Copper Market Data Pipeline`.

## CI and dependencies

Both workflows use `ubuntu-24.04`, `actions/checkout@v7`, and `actions/setup-python@v7`. Scheduled ingestion uses a non-cancelling `scheduled-ingestion` concurrency group and receives model names from GitHub Variables plus the Groq key from GitHub Secrets. `httpx>=0.28.1,<1` is an explicit dependency.

## Reproducible tests

During pytest, Django uses plain `StaticFilesStorage`, while CI keeps `collectstatic`. Docker Compose exposes PostgreSQL 16 on port 5433 with database `etl_test`. `.env.test.example` and the README document the exact local command and warn against production database URLs. Pytest aborts on a Neon hostname unless `ALLOW_REMOTE_TEST_DB=1` is explicitly set.

## Verification

Each section begins with failing behavior tests, then minimal implementation. Final verification runs the full suite with coverage against Docker PostgreSQL and `makemigrations --check --dry-run`.
