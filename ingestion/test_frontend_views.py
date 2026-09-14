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
