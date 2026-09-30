# Maintenance and LLM Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the approved provider-chain, dashboard, CI, and local-test maintenance work as exactly four tested commits.

**Architecture:** Keep orchestration in `ingestion.services`, with small provider-specific call functions sharing retry/deadline logic. Persist provenance on `IngestionRun`; views consume that provenance without probing providers.

**Tech Stack:** Django 5, pytest/pytest-django, google-genai, httpx, GitHub Actions, Docker Compose/PostgreSQL 16.

**Spec:** `docs/superpowers/specs/2026-09-30-maintenance-llm-fallback-design.md`

## Global Constraints

- Work only on `chore/maintenance-llm-fallback` from `9954729`.
- Produce exactly four conventional commits and do not push.
- Make no real Gemini or Groq calls; mock network and sleep.
- Keep total retry waiting at or below 20 seconds.
- Use `httpx>=0.28.1,<1`.

## Review Focus

- Empty provider configuration disables that provider without constructing a client.
- A non-429 4xx advances immediately and does not consume a retry sleep.
- Empty provider responses retry once, then advance.
- The global budget truncates or skips sleeps and provider work at the deadline.
- Neon test URLs abort before Django can connect unless explicitly allowed.

---

### Task 1: Provider chain and provenance

**Files:** `ingestion/services.py`, `ingestion/models.py`, `ingestion/migrations/0006_ingestionrun_summary_source.py`, `api/serializers.py`, `ingestion/tests.py`, `api/tests.py`, `config/settings.py`, `config/test_settings_validation.py`, `.env.example`, `.github/workflows/scheduled-ingestion.yml`, and the design/plan documents.

**Interfaces:** `generate_run_summary(run) -> str` persists both `summary` and `summary_source`; `quality_report()` and serializers expose `summary_source`.

- [ ] Add failing tests for provider ordering, retry classification, empty responses, the global wait budget, settings defaults, migration data classification, and API/report exposure.
- [ ] Run focused tests and confirm expected failures.
- [ ] Implement provider helpers, retry orchestration, settings, field, migration, and exposure.
- [ ] Run focused and full tests until green.
- [ ] Commit as `feat: add resilient run summary provider chain`.

### Task 2: Dashboard attribution and branding

**Files:** `ingestion/views.py`, `templates/dashboard.html`, `templates/base.html`, `templates/partials/_nav.html`, `ingestion/test_frontend_views.py`.

**Interfaces:** dashboard context provides `ai_summary_rate_30d` and an attributed heading for `latest_summary_run`.

- [ ] Add failing view tests for LLM/fallback labels, KPI calculation, and branding.
- [ ] Run focused tests and confirm expected failures.
- [ ] Implement query aggregation, labels, KPI markup, and branding.
- [ ] Run focused and full tests until green.
- [ ] Commit as `feat: attribute AI summaries in dashboard`.

### Task 3: CI and dependency maintenance

**Files:** `.github/workflows/tests.yml`, `.github/workflows/scheduled-ingestion.yml`, `requirements.txt`, plus configuration tests where behavior is executable.

**Interfaces:** workflows run on Ubuntu 24.04 with current Node 24-based action majors; scheduled runs serialize under one concurrency group.

- [ ] Add or extend executable configuration tests for dependency/settings behavior where applicable.
- [ ] Update runner/action versions, concurrency, and explicit httpx constraint.
- [ ] Run settings/configuration tests and the full suite.
- [ ] Commit as `chore: modernize CI and pin httpx`.

### Task 4: Reproducible and safe local tests

**Files:** `config/settings.py`, `conftest.py`, `config/test_settings_validation.py`, `docker-compose.yml`, `.env.test.example`, `README.md`.

**Interfaces:** pytest uses `StaticFilesStorage`; `_guard_remote_test_database(url, allow_remote)` rejects Neon hosts without opt-in.

- [ ] Add failing tests for static storage and the remote-database guard.
- [ ] Run focused tests and confirm expected failures.
- [ ] Implement the storage switch, early guard, Docker service, and documentation.
- [ ] Start Docker PostgreSQL and run `pytest --cov --cov-report=term-missing` without local collectstatic.
- [ ] Run `python manage.py makemigrations --check --dry-run`.
- [ ] Commit as `test: make local test runs reproducible`.
