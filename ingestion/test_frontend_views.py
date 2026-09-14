from datetime import date, timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from ingestion.models import DataSource, IngestionRun, PriceRecord


@pytest.fixture
def stock_source(db):
    return DataSource.objects.create(
        name="watchlist-mineria",
        type=DataSource.SourceType.STOCK_PRICE,
        config_json={"tickers": ["FCX", "SCCO"], "period": "1mo"},
        active=True,
    )


@pytest.fixture
def inactive_source(db):
    return DataSource.objects.create(
        name="watchlist-tech",
        type=DataSource.SourceType.STOCK_PRICE,
        config_json={"tickers": ["AAPL"]},
        active=False,
    )


@pytest.fixture
def partial_run(stock_source):
    run = IngestionRun.objects.create(
        source=stock_source,
        status=IngestionRun.Status.PARTIAL,
        rows_ingested=1,
        errors_json=[{"ticker": "SCCO", "error": "symbol not found"}],
        summary="Se ingirió FCX correctamente; SCCO falló por símbolo no encontrado.",
        started_at=timezone.now() - timedelta(seconds=2),
        finished_at=timezone.now(),
    )
    PriceRecord.objects.create(
        source=stock_source,
        ingestion_run=run,
        ticker="FCX",
        date=date(2026, 1, 2),
        open=10,
        high=12,
        low=9,
        close=11,
        volume=1000,
    )
    return run


# --- dashboard ---------------------------------------------------------


@pytest.mark.django_db
def test_dashboard_returns_200_with_no_data(client):
    response = client.get(reverse("dashboard"))
    assert response.status_code == 200


@pytest.mark.django_db
def test_dashboard_shows_source_and_recent_run(client, stock_source, partial_run):
    response = client.get(reverse("dashboard"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "watchlist-mineria" in content
    assert "PARTIAL" in content
    assert "symbol not found" not in content  # el detalle de error no va en el dashboard


@pytest.mark.django_db
def test_dashboard_shows_latest_gemini_summary(client, partial_run):
    response = client.get(reverse("dashboard"))
    assert "falló por símbolo no encontrado" in response.content.decode()


# --- sources list --------------------------------------------------------


@pytest.mark.django_db
def test_sources_list_returns_200_with_no_data(client):
    response = client.get(reverse("sources_list"))
    assert response.status_code == 200


@pytest.mark.django_db
def test_sources_list_shows_active_and_inactive_sources(client, stock_source, inactive_source):
    response = client.get(reverse("sources_list"))

    content = response.content.decode()
    assert response.status_code == 200
    assert "watchlist-mineria" in content
    assert "watchlist-tech" in content
    assert "FCX" in content


# --- source detail ---------------------------------------------------------


@pytest.mark.django_db
def test_source_detail_returns_200_and_shows_config(client, stock_source, partial_run):
    response = client.get(reverse("source_detail", args=[stock_source.pk]))

    content = response.content.decode()
    assert response.status_code == 200
    assert "config_json" in content
    assert "FCX" in content
    assert f"#{partial_run.pk}" in content


@pytest.mark.django_db
def test_source_detail_404_for_missing_source(client):
    response = client.get(reverse("source_detail", args=[999]))
    assert response.status_code == 404


# --- runs list -------------------------------------------------------------


@pytest.mark.django_db
def test_runs_list_returns_200_with_no_data(client):
    response = client.get(reverse("runs_list"))
    assert response.status_code == 200


@pytest.mark.django_db
def test_runs_list_shows_run_and_first_error(client, partial_run):
    response = client.get(reverse("runs_list"))

    content = response.content.decode()
    assert response.status_code == 200
    assert f"#{partial_run.pk}" in content
    assert "SCCO: symbol not found" in content


@pytest.mark.django_db
def test_runs_list_filters_by_status(client, stock_source, partial_run):
    success_run = IngestionRun.objects.create(
        source=stock_source, status=IngestionRun.Status.SUCCESS, rows_ingested=5
    )

    response = client.get(reverse("runs_list"), {"status": "success"})
    content = response.content.decode()

    assert f"#{success_run.pk}" in content
    assert f"#{partial_run.pk}" not in content
