from unittest.mock import patch

import pytest
from django.conf import settings

from ingestion.models import DataSource, IngestionRun
from ingestion.services import IngestionError
from ingestion.tasks import run_scheduled_ingestions


@pytest.fixture(autouse=True)
def _clear_seeded_datasources(db):
    """
    La data migration 0003 siembra DataSource activos de producción
    (watchlist-cobre, cobre-futuro-comex). Estos tests ejercitan
    run_scheduled_ingestions() en aislamiento total sobre fixtures propios,
    así que arrancan de una tabla vacía en vez de heredar ese seed.
    """
    DataSource.objects.all().delete()


@pytest.mark.django_db
def test_run_scheduled_ingestions_calls_run_ingestion_for_each_active_stock_source():
    DataSource.objects.create(
        name="a",
        type=DataSource.SourceType.STOCK_PRICE,
        config_json={"tickers": ["AAPL"]},
        active=True,
    )
    DataSource.objects.create(
        name="b",
        type=DataSource.SourceType.STOCK_PRICE,
        config_json={"tickers": ["MSFT"]},
        active=True,
    )

    def fake_run_ingestion(source, **kwargs):
        return IngestionRun.objects.create(source=source, status=IngestionRun.Status.SUCCESS)

    with patch("ingestion.tasks.run_ingestion", side_effect=fake_run_ingestion) as mocked:
        result = run_scheduled_ingestions()

    called_sources = {call.args[0].name for call in mocked.call_args_list}
    assert called_sources == {"a", "b"}
    assert mocked.call_count == 2
    assert len(result["succeeded"]) == 2
    assert result["failed"] == []


@pytest.mark.django_db
def test_run_scheduled_ingestions_ignores_inactive_and_macro_indicator_sources():
    DataSource.objects.create(
        name="inactiva",
        type=DataSource.SourceType.STOCK_PRICE,
        config_json={"tickers": ["AAPL"]},
        active=False,
    )
    DataSource.objects.create(
        name="watchlist-macro",
        type=DataSource.SourceType.MACRO_INDICATOR,
        config_json={"tickers": ["CPI"]},
        active=True,
    )

    with patch("ingestion.tasks.run_ingestion") as mocked:
        result = run_scheduled_ingestions()

    mocked.assert_not_called()
    assert result == {"succeeded": [], "failed": []}


@pytest.mark.django_db
def test_run_scheduled_ingestions_includes_commodity_sources():
    """
    commodity se ingiere igual que stock_price (mismo fetch de yfinance),
    así que el scheduler también debe recogerlo.
    """
    stock = DataSource.objects.create(
        name="watchlist-cobre",
        type=DataSource.SourceType.STOCK_PRICE,
        config_json={"tickers": ["FCX"]},
        active=True,
    )
    commodity = DataSource.objects.create(
        name="cobre-futuro-comex",
        type=DataSource.SourceType.COMMODITY,
        config_json={"tickers": ["HG=F"]},
        active=True,
    )

    def fake_run_ingestion(source, **kwargs):
        return IngestionRun.objects.create(source=source, status=IngestionRun.Status.SUCCESS)

    with patch("ingestion.tasks.run_ingestion", side_effect=fake_run_ingestion) as mocked:
        result = run_scheduled_ingestions()

    called_sources = {call.args[0].name for call in mocked.call_args_list}
    assert called_sources == {stock.name, commodity.name}
    assert len(result["succeeded"]) == 2
    assert result["failed"] == []


@pytest.mark.django_db
def test_run_scheduled_ingestions_continues_after_one_source_fails():
    DataSource.objects.create(
        name="buena",
        type=DataSource.SourceType.STOCK_PRICE,
        config_json={"tickers": ["AAPL"]},
        active=True,
    )
    DataSource.objects.create(
        name="mala",
        type=DataSource.SourceType.STOCK_PRICE,
        config_json={"tickers": []},
        active=True,
    )

    def fake_run_ingestion(source, **kwargs):
        if source.name == "mala":
            raise IngestionError("no tiene tickers configurados")
        return IngestionRun.objects.create(source=source, status=IngestionRun.Status.SUCCESS)

    with patch("ingestion.tasks.run_ingestion", side_effect=fake_run_ingestion) as mocked:
        result = run_scheduled_ingestions()

    assert mocked.call_count == 2
    assert [s["source"] for s in result["succeeded"]] == ["buena"]
    assert [f["source"] for f in result["failed"]] == ["mala"]
    assert "no tiene tickers" in result["failed"][0]["error"]


@pytest.mark.django_db
def test_run_scheduled_ingestions_survives_unexpected_exception():
    DataSource.objects.create(
        name="buena",
        type=DataSource.SourceType.STOCK_PRICE,
        config_json={"tickers": ["AAPL"]},
        active=True,
    )
    DataSource.objects.create(
        name="explota",
        type=DataSource.SourceType.STOCK_PRICE,
        config_json={"tickers": ["MSFT"]},
        active=True,
    )

    def fake_run_ingestion(source, **kwargs):
        if source.name == "explota":
            raise RuntimeError("timeout de red inesperado")
        return IngestionRun.objects.create(source=source, status=IngestionRun.Status.SUCCESS)

    with patch("ingestion.tasks.run_ingestion", side_effect=fake_run_ingestion):
        result = run_scheduled_ingestions()

    assert [s["source"] for s in result["succeeded"]] == ["buena"]
    assert [f["source"] for f in result["failed"]] == ["explota"]
    assert "timeout de red inesperado" in result["failed"][0]["error"]


def test_celery_task_always_eager_is_enabled_in_tests():
    """
    Garantiza que en tests las tareas corran sincrónicamente in-process,
    sin necesitar un worker ni Redis real corriendo.
    """
    assert settings.CELERY_TASK_ALWAYS_EAGER is True


@pytest.mark.django_db
def test_run_scheduled_ingestions_delay_runs_synchronously_without_broker():
    DataSource.objects.create(
        name="a",
        type=DataSource.SourceType.STOCK_PRICE,
        config_json={"tickers": ["AAPL"]},
        active=True,
    )

    def fake_run_ingestion(source, **kwargs):
        return IngestionRun.objects.create(source=source, status=IngestionRun.Status.SUCCESS)

    with patch("ingestion.tasks.run_ingestion", side_effect=fake_run_ingestion):
        async_result = run_scheduled_ingestions.delay()

    assert async_result.successful()
    assert async_result.result["succeeded"][0]["source"] == "a"
