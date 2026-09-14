from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command

from ingestion.models import DataSource, IngestionRun
from ingestion.services import IngestionError


@pytest.mark.django_db
def test_run_ingestions_now_runs_synchronously_without_celery():
    """
    Llama al management command directamente: no debe pasar por .delay()
    (no hay broker/worker involucrados), y run_ingestion debe ejecutarse
    en el mismo proceso.
    """
    DataSource.objects.create(
        name="a",
        type=DataSource.SourceType.STOCK_PRICE,
        config_json={"tickers": ["AAPL"]},
        active=True,
    )

    def fake_run_ingestion(source, **kwargs):
        return IngestionRun.objects.create(source=source, status=IngestionRun.Status.SUCCESS)

    out = StringIO()
    with patch("ingestion.tasks.run_ingestion", side_effect=fake_run_ingestion) as mocked:
        call_command("run_ingestions_now", stdout=out)

    mocked.assert_called_once()
    assert IngestionRun.objects.filter(source__name="a").count() == 1
    output = out.getvalue()
    assert "OK" in output
    assert "1 fuente(s) OK" in output
    assert "0 fuente(s) fallida(s)" in output


@pytest.mark.django_db
def test_run_ingestions_now_reports_failures_without_raising():
    DataSource.objects.create(
        name="mala",
        type=DataSource.SourceType.STOCK_PRICE,
        config_json={"tickers": []},
        active=True,
    )

    def fake_run_ingestion(source, **kwargs):
        raise IngestionError("no tiene tickers configurados")

    out = StringIO()
    with patch("ingestion.tasks.run_ingestion", side_effect=fake_run_ingestion):
        call_command("run_ingestions_now", stdout=out)

    output = out.getvalue()
    assert "FAIL mala" in output
    assert "no tiene tickers configurados" in output
    assert "0 fuente(s) OK" in output
    assert "1 fuente(s) fallida(s)" in output


@pytest.mark.django_db
def test_run_ingestions_now_does_nothing_when_no_active_stock_sources():
    out = StringIO()
    with patch("ingestion.tasks.run_ingestion") as mocked:
        call_command("run_ingestions_now", stdout=out)

    mocked.assert_not_called()
    assert "0 fuente(s) OK" in out.getvalue()
    assert "0 fuente(s) fallida(s)" in out.getvalue()
