from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from rest_framework import status
from rest_framework.test import APIClient

from ingestion.models import DataSource, IngestionRun, PriceRecord

PATCH_TARGET = "ingestion.services.yf.Ticker"


def make_history_df(rows):
    """Construye un DataFrame con la misma forma que yfinance.Ticker().history()."""
    index = pd.DatetimeIndex([r["date"] for r in rows], name="Date")
    return pd.DataFrame(
        {
            "Open": [r["open"] for r in rows],
            "High": [r["high"] for r in rows],
            "Low": [r["low"] for r in rows],
            "Close": [r["close"] for r in rows],
            "Volume": [r["volume"] for r in rows],
        },
        index=index,
    )


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def stock_source(db):
    return DataSource.objects.create(
        name="watchlist-mineria",
        type=DataSource.SourceType.STOCK_PRICE,
        config_json={"tickers": ["AAPL"], "period": "5d"},
        active=True,
    )


# --- GET /api/runs/ ----------------------------------------------------


@pytest.mark.django_db
def test_list_runs_returns_all_runs_ordered_by_most_recent(api_client, stock_source):
    older = IngestionRun.objects.create(
        source=stock_source, status=IngestionRun.Status.SUCCESS
    )
    newer = IngestionRun.objects.create(
        source=stock_source, status=IngestionRun.Status.FAILED
    )

    response = api_client.get("/api/runs/")

    assert response.status_code == status.HTTP_200_OK
    ids = [item["id"] for item in response.data]
    assert ids == [newer.id, older.id]


@pytest.mark.django_db
def test_list_runs_includes_source_name(api_client, stock_source):
    IngestionRun.objects.create(source=stock_source, status=IngestionRun.Status.SUCCESS)

    response = api_client.get("/api/runs/")

    assert response.data[0]["source_name"] == stock_source.name


# --- GET /api/runs/{id}/quality-report/ ---------------------------------


@pytest.mark.django_db
def test_quality_report_returns_rows_errors_and_completeness(api_client, stock_source):
    run = IngestionRun.objects.create(
        source=stock_source,
        status=IngestionRun.Status.PARTIAL,
        rows_ingested=2,
        errors_json=[{"ticker": "BADTICKER", "error": "symbol not found"}],
    )
    PriceRecord.objects.create(
        source=stock_source,
        ingestion_run=run,
        ticker="AAPL",
        date=date(2026, 1, 2),
        open=10,
        high=12,
        low=9,
        close=11,
        volume=1000,
    )
    PriceRecord.objects.create(
        source=stock_source,
        ingestion_run=run,
        ticker="AAPL",
        date=date(2026, 1, 3),
        open=11,
        high=13,
        low=10,
        close=12,
        volume=1500,
    )

    response = api_client.get(f"/api/runs/{run.id}/quality-report/")

    assert response.status_code == status.HTTP_200_OK
    data = response.data
    assert data["run_id"] == run.id
    assert data["rows_ingested"] == 2
    assert data["errors_json"] == [{"ticker": "BADTICKER", "error": "symbol not found"}]
    assert data["tickers_ingested"] == ["AAPL"]
    assert data["tickers_failed"] == ["BADTICKER"]
    assert data["success_rate"] == 50.0


@pytest.mark.django_db
def test_quality_report_full_success_has_no_failed_tickers(api_client, stock_source):
    run = IngestionRun.objects.create(
        source=stock_source, status=IngestionRun.Status.SUCCESS, rows_ingested=1
    )
    PriceRecord.objects.create(
        source=stock_source,
        ingestion_run=run,
        ticker="AAPL",
        date=date(2026, 1, 2),
        open=10,
        high=12,
        low=9,
        close=11,
        volume=1000,
    )

    response = api_client.get(f"/api/runs/{run.id}/quality-report/")

    assert response.data["tickers_failed"] == []
    assert response.data["success_rate"] == 100.0


@pytest.mark.django_db
def test_quality_report_404_for_missing_run(api_client):
    response = api_client.get("/api/runs/999999/quality-report/")
    assert response.status_code == status.HTTP_404_NOT_FOUND


# --- POST /api/sources/{id}/trigger/ -------------------------------------


@pytest.mark.django_db
def test_trigger_runs_ingestion_synchronously_and_returns_run(api_client, stock_source):
    history = make_history_df(
        [{"date": date(2026, 1, 2), "open": 10, "high": 12, "low": 9, "close": 11, "volume": 1000}]
    )
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = history

    with patch(PATCH_TARGET, return_value=mock_ticker):
        response = api_client.post(
            f"/api/sources/{stock_source.id}/trigger/", data={}, format="json"
        )

    assert response.status_code == status.HTTP_201_CREATED
    assert response.data["status"] == IngestionRun.Status.SUCCESS
    assert response.data["rows_ingested"] == 1
    assert IngestionRun.objects.filter(source=stock_source).count() == 1
    assert PriceRecord.objects.filter(source=stock_source, ticker="AAPL").count() == 1


@pytest.mark.django_db
def test_trigger_accepts_period_override_in_body(api_client, stock_source):
    history = make_history_df(
        [{"date": date(2026, 1, 2), "open": 10, "high": 12, "low": 9, "close": 11, "volume": 1000}]
    )
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = history

    with patch(PATCH_TARGET, return_value=mock_ticker):
        response = api_client.post(
            f"/api/sources/{stock_source.id}/trigger/",
            data={"period": "1y"},
            format="json",
        )

    assert response.status_code == status.HTTP_201_CREATED
    mock_ticker.history.assert_called_once_with(period="1y")


@pytest.mark.django_db
def test_trigger_returns_400_and_no_run_when_source_is_inactive(api_client):
    source = DataSource.objects.create(
        name="watchlist-inactiva",
        type=DataSource.SourceType.STOCK_PRICE,
        config_json={"tickers": ["AAPL"]},
        active=False,
    )

    response = api_client.post(f"/api/sources/{source.id}/trigger/", data={}, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "inactivo" in response.data["detail"]
    assert IngestionRun.objects.filter(source=source).count() == 0


@pytest.mark.django_db
def test_trigger_returns_400_when_source_is_wrong_type(api_client):
    source = DataSource.objects.create(
        name="cobre-lme",
        type=DataSource.SourceType.COMMODITY,
        config_json={"tickers": ["HG=F"]},
    )

    response = api_client.post(f"/api/sources/{source.id}/trigger/", data={}, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
def test_trigger_returns_400_when_no_tickers_configured(api_client):
    source = DataSource.objects.create(
        name="watchlist-vacia",
        type=DataSource.SourceType.STOCK_PRICE,
        config_json={},
        active=True,
    )

    response = api_client.post(f"/api/sources/{source.id}/trigger/", data={}, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
def test_trigger_404_for_missing_source(api_client):
    response = api_client.post("/api/sources/999999/trigger/", data={}, format="json")
    assert response.status_code == status.HTTP_404_NOT_FOUND


# --- GET /api/prices/ -----------------------------------------------------


@pytest.mark.django_db
def test_list_prices_can_filter_by_ticker(api_client, stock_source):
    PriceRecord.objects.create(
        source=stock_source,
        ticker="AAPL",
        date=date(2026, 1, 2),
        open=10,
        high=12,
        low=9,
        close=11,
        volume=1000,
    )
    PriceRecord.objects.create(
        source=stock_source,
        ticker="MSFT",
        date=date(2026, 1, 2),
        open=20,
        high=22,
        low=19,
        close=21,
        volume=2000,
    )

    response = api_client.get("/api/prices/", {"ticker": "AAPL"})

    assert response.status_code == status.HTTP_200_OK
    assert len(response.data) == 1
    assert response.data[0]["ticker"] == "AAPL"


@pytest.mark.django_db
def test_list_prices_can_filter_by_source(api_client, stock_source):
    other_source = DataSource.objects.create(
        name="watchlist-otra",
        type=DataSource.SourceType.STOCK_PRICE,
        config_json={"tickers": ["MSFT"]},
    )
    PriceRecord.objects.create(
        source=stock_source,
        ticker="AAPL",
        date=date(2026, 1, 2),
        open=10,
        high=12,
        low=9,
        close=11,
        volume=1000,
    )
    PriceRecord.objects.create(
        source=other_source,
        ticker="MSFT",
        date=date(2026, 1, 2),
        open=20,
        high=22,
        low=19,
        close=21,
        volume=2000,
    )

    response = api_client.get("/api/prices/", {"source": stock_source.id})

    assert response.status_code == status.HTTP_200_OK
    assert len(response.data) == 1
    assert response.data[0]["source"] == stock_source.id
