from datetime import timedelta
from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.utils import timezone

from ingestion.models import DataSource, IngestionRun
from ingestion.services import IngestionError


@pytest.fixture(autouse=True)
def _clear_seeded_datasources(db):
    """
    La data migration 0003 siembra DataSource activos de producción
    (watchlist-cobre, cobre-futuro-comex). Estos tests ejercitan el
    management command en aislamiento total sobre fixtures propios, así que
    arrancan de una tabla vacía en vez de heredar ese seed.
    """
    DataSource.objects.all().delete()


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


@pytest.mark.django_db
def test_run_ingestions_now_reaps_stale_running_runs_before_scheduling():
    """
    Un run que quedó colgado en RUNNING (proceso anterior muerto a mitad de
    camino) debe auto-sanearse a FAILED antes de programar ingestas nuevas.
    """
    source = DataSource.objects.create(
        name="watchlist-vieja",
        type=DataSource.SourceType.STOCK_PRICE,
        config_json={"tickers": []},
        active=False,
    )
    stale_run = IngestionRun.objects.create(
        source=source,
        status=IngestionRun.Status.RUNNING,
        started_at=timezone.now() - timedelta(minutes=30),
    )

    out = StringIO()
    call_command("run_ingestions_now", stdout=out)

    stale_run.refresh_from_db()
    assert stale_run.status == IngestionRun.Status.FAILED
    assert stale_run.finished_at is not None
    assert "colgado" in out.getvalue()
