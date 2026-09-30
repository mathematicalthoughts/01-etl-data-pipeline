from importlib import import_module
import threading
import time as stdlib_time
from unittest.mock import MagicMock, patch

import httpx
import pytest
from django.apps import apps
from django.test import override_settings
from google.genai import errors as genai_errors

from ingestion import services as summary_services
from ingestion.models import DataSource, IngestionRun
from ingestion.services import generate_run_summary


@pytest.fixture
def stock_source(db):
    return DataSource.objects.create(
        name="summary-provider-source",
        type=DataSource.SourceType.STOCK_PRICE,
        config_json={"tickers": ["AAPL"]},
    )


@pytest.fixture
def run(stock_source):
    return IngestionRun.objects.create(
        source=stock_source,
        status=IngestionRun.Status.SUCCESS,
        rows_ingested=1,
        ticker_stats={"AAPL": {"created": 1, "updated": 0, "errors": 0}},
    )


def gemini_response(text):
    response = MagicMock()
    response.text = text
    return response


def groq_response(text, status_code=200):
    return httpx.Response(
        status_code,
        json={"choices": [{"message": {"content": text}}]},
        request=httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions"),
    )


def groq_error_response(status_code, body):
    return httpx.Response(
        status_code,
        text=body,
        request=httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions"),
    )


@pytest.mark.django_db
@override_settings(
    GEMINI_API_KEY="gemini-key",
    GEMINI_MODEL="gemini-primary",
    GEMINI_FALLBACK_MODEL="",
    GROQ_API_KEY="",
    GROQ_MODEL="",
)
def test_primary_gemini_success_persists_source(run):
    client = MagicMock()
    client.models.generate_content.return_value = gemini_response("Resumen primario")

    with patch("ingestion.services.genai.Client", return_value=client):
        assert generate_run_summary(run) == "Resumen primario"

    run.refresh_from_db()
    assert run.summary_source == "gemini:gemini-primary"
    assert client.models.generate_content.call_args.kwargs["model"] == "gemini-primary"


@pytest.mark.django_db
@override_settings(
    GEMINI_API_KEY="gemini-key",
    GEMINI_MODEL="gemini-primary",
    GEMINI_FALLBACK_MODEL="gemini-secondary",
    GROQ_API_KEY="",
    GROQ_MODEL="",
)
def test_primary_503_twice_then_fallback_gemini_succeeds(run):
    error = genai_errors.ServerError(
        503, {"error": {"code": 503, "message": "busy", "status": "UNAVAILABLE"}}
    )
    client = MagicMock()
    client.models.generate_content.side_effect = [
        error,
        error,
        gemini_response("Resumen secundario"),
    ]

    with (
        patch("ingestion.services.genai.Client", return_value=client),
        patch("ingestion.services.time.sleep") as sleep,
    ):
        assert generate_run_summary(run) == "Resumen secundario"

    assert [call.kwargs["model"] for call in client.models.generate_content.call_args_list] == [
        "gemini-primary",
        "gemini-primary",
        "gemini-secondary",
    ]
    sleep.assert_called_once_with(2)
    run.refresh_from_db()
    assert run.summary_source == "gemini:gemini-secondary"


@pytest.mark.django_db
@override_settings(
    GEMINI_API_KEY="gemini-key",
    GEMINI_MODEL="gemini-primary",
    GEMINI_FALLBACK_MODEL="gemini-secondary",
    GROQ_API_KEY="groq-key",
    GROQ_MODEL="llama-test",
    GROQ_BASE_URL="https://api.groq.com/openai/v1",
)
def test_both_gemini_models_exhaust_503_then_groq_succeeds(run):
    error = genai_errors.ServerError(
        503, {"error": {"code": 503, "message": "busy", "status": "UNAVAILABLE"}}
    )
    client = MagicMock()
    client.models.generate_content.side_effect = [error, error, error, error]

    with (
        patch("ingestion.services.genai.Client", return_value=client),
        patch("ingestion.services.httpx.post", return_value=groq_response("Resumen Groq")) as post,
        patch("ingestion.services.time.sleep"),
    ):
        assert generate_run_summary(run) == "Resumen Groq"

    assert client.models.generate_content.call_count == 4
    assert post.call_count == 1
    assert post.call_args.args[0] == "https://api.groq.com/openai/v1/chat/completions"
    assert post.call_args.kwargs["json"]["model"] == "llama-test"
    assert post.call_args.kwargs["json"]["max_completion_tokens"] == 1024
    assert post.call_args.kwargs["json"]["reasoning_effort"] == "low"
    assert post.call_args.kwargs["json"]["include_reasoning"] is False
    assert "max_tokens" not in post.call_args.kwargs["json"]
    run.refresh_from_db()
    assert run.summary_source == "groq:llama-test"


@pytest.mark.django_db
@override_settings(
    GEMINI_API_KEY="gemini-key",
    GEMINI_MODEL="gemini-primary",
    GEMINI_FALLBACK_MODEL="",
    GROQ_API_KEY="groq-key",
    GROQ_MODEL="llama-test",
    GROQ_BASE_URL="https://api.groq.com/openai/v1",
)
def test_gemini_hangs_twice_then_groq_responds_within_budget(run):
    class FakeClock:
        def __init__(self):
            self.now = 0.0
            self.sleeps = []

        def monotonic(self):
            return self.now

        def sleep(self, seconds):
            self.sleeps.append(seconds)
            self.now += seconds

    clock = FakeClock()
    call_timeouts = []

    def simulate_deadline_then_call(provider, timeout):
        call_timeouts.append(timeout)
        if len(call_timeouts) <= 2:
            clock.now += timeout
            raise summary_services._ProviderDeadlineError("provider hung")
        return provider(timeout)

    with (
        patch(
            "ingestion.services._call_before_deadline",
            side_effect=simulate_deadline_then_call,
        ),
        patch(
            "ingestion.services.httpx.post",
            return_value=groq_response("Resumen Groq"),
        ) as post,
        patch("ingestion.services.time.monotonic", side_effect=clock.monotonic),
        patch("ingestion.services.time.sleep", side_effect=clock.sleep),
    ):
        assert generate_run_summary(run) == "Resumen Groq"

    assert len(call_timeouts) == 3
    assert all(0 < timeout <= 15 for timeout in call_timeouts)
    assert all(timeout >= 10 for timeout in call_timeouts[:2])
    assert clock.now <= 60
    assert post.call_args.kwargs["timeout"] <= 15
    assert post.call_args.kwargs["json"]["max_completion_tokens"] == 1024
    assert post.call_args.kwargs["json"]["reasoning_effort"] == "low"
    assert post.call_args.kwargs["json"]["include_reasoning"] is False
    run.refresh_from_db()
    assert run.summary_source == "groq:llama-test"


@pytest.mark.django_db
@override_settings(
    GEMINI_API_KEY="",
    GEMINI_MODEL="gemini-primary",
    GEMINI_FALLBACK_MODEL="",
    GROQ_API_KEY="",
    GROQ_MODEL="",
)
def test_unconfigured_groq_reaches_deterministic_fallback_without_network(run):
    with (
        patch("ingestion.services.genai.Client") as gemini,
        patch("ingestion.services.httpx.post") as post,
    ):
        summary = generate_run_summary(run)

    assert summary.startswith("[Resumen automático sin LLM]")
    gemini.assert_not_called()
    post.assert_not_called()
    run.refresh_from_db()
    assert run.summary_source == "fallback"


@pytest.mark.django_db
@override_settings(
    GEMINI_API_KEY="gemini-key",
    GEMINI_MODEL="gemini-primary",
    GEMINI_FALLBACK_MODEL="",
    GROQ_API_KEY="groq-key",
    GROQ_MODEL="llama-test",
    GROQ_BASE_URL="https://api.groq.com/openai/v1",
)
def test_gemini_400_moves_to_groq_without_retry_or_sleep(run):
    error = genai_errors.ClientError(
        400, {"error": {"code": 400, "message": "bad request", "status": "INVALID_ARGUMENT"}}
    )
    client = MagicMock()
    client.models.generate_content.side_effect = error

    with (
        patch("ingestion.services.genai.Client", return_value=client),
        patch("ingestion.services.httpx.post", return_value=groq_response("Resumen Groq")),
        patch("ingestion.services.time.sleep") as sleep,
    ):
        assert generate_run_summary(run) == "Resumen Groq"

    assert client.models.generate_content.call_count == 1
    sleep.assert_not_called()


@pytest.mark.django_db
@override_settings(
    GEMINI_API_KEY="gemini-key",
    GEMINI_MODEL="gemini-primary",
    GEMINI_FALLBACK_MODEL="",
    GROQ_API_KEY="",
    GROQ_MODEL="",
)
def test_gemini_timeout_is_never_below_ten_seconds(run):
    client = MagicMock()
    client.models.generate_content.return_value = gemini_response("Resumen primario")

    with (
        patch("ingestion.services.SUMMARY_WAIT_BUDGET_SECONDS", 12),
        patch("ingestion.services.genai.Client", return_value=client) as gemini_client,
    ):
        assert generate_run_summary(run) == "Resumen primario"

    timeout_ms = gemini_client.call_args.kwargs["http_options"]["timeout"]
    assert timeout_ms >= 10_000


@pytest.mark.django_db
@override_settings(
    GEMINI_API_KEY="gemini-key",
    GEMINI_MODEL="gemini-primary",
    GEMINI_FALLBACK_MODEL="",
    GROQ_API_KEY="",
    GROQ_MODEL="",
)
def test_gemini_is_skipped_when_budget_has_less_than_ten_seconds(run):
    clock = MagicMock()
    clock.monotonic.side_effect = [0, 25, 25]

    with (
        patch("ingestion.services.SUMMARY_WAIT_BUDGET_SECONDS", 30),
        patch("ingestion.services._call_gemini", return_value="No debe usarse") as gemini,
        patch("ingestion.services.time.monotonic", side_effect=clock.monotonic),
    ):
        summary = generate_run_summary(run)

    assert summary.startswith("[Resumen automático sin LLM]")
    gemini.assert_not_called()


@override_settings(
    GROQ_API_KEY="secret-groq-key",
    GROQ_BASE_URL="https://api.groq.com/openai/v1",
)
def test_groq_http_error_logs_status_and_first_300_body_characters(caplog):
    body = "a" * 300 + "TAIL-SHOULD-NOT-BE-LOGGED"

    with (
        patch(
            "ingestion.services.httpx.post",
            return_value=groq_error_response(429, body),
        ),
        caplog.at_level("ERROR", logger="ingestion.services"),
        pytest.raises(httpx.HTTPStatusError),
    ):
        summary_services._call_groq("prompt", "openai/gpt-oss-120b", 15)

    log_output = caplog.text
    assert "429" in log_output
    assert body[:300] in log_output
    assert "TAIL-SHOULD-NOT-BE-LOGGED" not in log_output
    assert "secret-groq-key" not in log_output


@pytest.mark.django_db
@override_settings(
    GEMINI_API_KEY="",
    GEMINI_MODEL="gemini-primary",
    GEMINI_FALLBACK_MODEL="",
    GROQ_API_KEY="groq-key",
    GROQ_MODEL="llama-test",
    GROQ_BASE_URL="https://api.groq.com/openai/v1",
)
def test_empty_groq_response_is_transient_and_retried(run):
    with (
        patch("ingestion.services.httpx.post", return_value=groq_response("")) as post,
        patch("ingestion.services.time.sleep") as sleep,
    ):
        summary = generate_run_summary(run)

    assert summary.startswith("[Resumen automático sin LLM]")
    assert post.call_count == 2
    sleep.assert_called_once_with(2)


@pytest.mark.django_db
@override_settings(
    GEMINI_API_KEY="gemini-key",
    GEMINI_MODEL="gemini-primary",
    GEMINI_FALLBACK_MODEL="gemini-secondary",
    GROQ_API_KEY="groq-key",
    GROQ_MODEL="llama-test",
)
def test_total_wait_budget_never_exceeds_sixty_seconds(run):
    class FakeClock:
        def __init__(self):
            self.now = 0.0
            self.sleeps = []

        def monotonic(self):
            return self.now

        def sleep(self, seconds):
            self.sleeps.append(seconds)
            self.now += seconds

    clock = FakeClock()
    error = genai_errors.ServerError(
        503, {"error": {"code": 503, "message": "busy", "status": "UNAVAILABLE"}}
    )
    gemini_timeouts = []

    def consume_gemini_call_budget(prompt, model, timeout):
        gemini_timeouts.append(timeout)
        clock.now += timeout
        raise error

    def consume_groq_call_budget(prompt, model, timeout):
        clock.now += timeout
        raise httpx.ReadTimeout("Groq timed out")

    with (
        patch("ingestion.services._call_gemini", side_effect=consume_gemini_call_budget),
        patch("ingestion.services._call_groq", side_effect=consume_groq_call_budget) as groq,
        patch("ingestion.services.time.monotonic", side_effect=clock.monotonic),
        patch("ingestion.services.time.sleep", side_effect=clock.sleep),
    ):
        summary = generate_run_summary(run)

    assert summary.startswith("[Resumen automático sin LLM]")
    assert sum(clock.sleeps) <= 60
    assert clock.now <= 60
    assert all(10 <= timeout <= 15 for timeout in gemini_timeouts)
    groq.assert_not_called()


@pytest.mark.django_db
@override_settings(
    GEMINI_API_KEY="gemini-key",
    GEMINI_MODEL="gemini-primary",
    GEMINI_FALLBACK_MODEL="",
    GROQ_API_KEY="",
    GROQ_MODEL="",
)
def test_success_arriving_after_deadline_is_rejected(run):
    clock = MagicMock()
    clock.monotonic.side_effect = [0, 0, 0, 61, 61]
    client = MagicMock()
    client.models.generate_content.return_value = gemini_response("Resumen tardío")

    with (
        patch("ingestion.services.genai.Client", return_value=client),
        patch("ingestion.services.time.monotonic", side_effect=clock.monotonic),
        patch("ingestion.services.time.sleep"),
    ):
        summary = generate_run_summary(run)

    assert summary.startswith("[Resumen automático sin LLM]")
    run.refresh_from_db()
    assert run.summary_source == "fallback"


@pytest.mark.django_db
@override_settings(
    GEMINI_API_KEY="gemini-key",
    GEMINI_MODEL="gemini-primary",
    GEMINI_FALLBACK_MODEL="",
    GROQ_API_KEY="",
    GROQ_MODEL="",
)
def test_blocked_provider_cannot_hold_run_past_budget(run):
    release_provider = threading.Event()

    def blocked_provider(*args, **kwargs):
        release_provider.wait(timeout=0.2)
        return "Resumen demasiado tarde"

    started = stdlib_time.perf_counter()
    try:
        with (
            patch("ingestion.services.SUMMARY_WAIT_BUDGET_SECONDS", 0.01),
            patch("ingestion.services._call_gemini", side_effect=blocked_provider),
            patch("ingestion.services.time.sleep"),
        ):
            summary = generate_run_summary(run)
    finally:
        release_provider.set()
    elapsed = stdlib_time.perf_counter() - started

    assert summary.startswith("[Resumen automático sin LLM]")
    assert elapsed < 0.08


@pytest.mark.django_db
def test_summary_source_data_migration_classifies_existing_runs(stock_source):
    fallback = IngestionRun.objects.create(
        source=stock_source,
        summary="[Resumen automático sin LLM] respaldo",
    )
    legacy_llm = IngestionRun.objects.create(source=stock_source, summary="Resumen histórico")
    empty = IngestionRun.objects.create(source=stock_source, summary="")

    migration = import_module("ingestion.migrations.0006_ingestionrun_summary_source")
    migration.populate_summary_source(apps, None)

    fallback.refresh_from_db()
    legacy_llm.refresh_from_db()
    empty.refresh_from_db()
    assert fallback.summary_source == "fallback"
    assert legacy_llm.summary_source == "gemini:legacy"
    assert empty.summary_source == ""
