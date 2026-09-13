from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

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


def mock_ticker_returning(history_by_ticker):
    """
    history_by_ticker: dict ticker -> DataFrame | Exception instance.
    Devuelve un callable para usar como side_effect de yf.Ticker.
    """

    def _factory(ticker):
        result = history_by_ticker[ticker]
        mock_instance = MagicMock()
        if isinstance(result, Exception):
            mock_instance.history.side_effect = result
        else:
            mock_instance.history.return_value = result
        return mock_instance

    return _factory


@pytest.fixture
def stock_source(db):
    return DataSource.objects.create(
        name="watchlist-mineria",
        type=DataSource.SourceType.STOCK_PRICE,
        config_json={"tickers": ["AAPL"], "period": "5d"},
        active=True,
    )


@pytest.mark.django_db
def test_ingest_source_success_creates_run_and_price_records(stock_source):
    history = make_history_df(
        [
            {"date": date(2026, 1, 2), "open": 10, "high": 12, "low": 9, "close": 11, "volume": 1000},
            {"date": date(2026, 1, 3), "open": 11, "high": 13, "low": 10, "close": 12, "volume": 1500},
        ]
    )

    with patch(PATCH_TARGET, side_effect=mock_ticker_returning({"AAPL": history})):
        call_command("ingest_source", "watchlist-mineria")

    run = IngestionRun.objects.get(source=stock_source)
    assert run.status == IngestionRun.Status.SUCCESS
    assert run.rows_ingested == 2
    assert run.errors_json == []
    assert run.started_at is not None
    assert run.finished_at is not None

    assert PriceRecord.objects.filter(source=stock_source, ticker="AAPL").count() == 2
    record = PriceRecord.objects.get(ticker="AAPL", date=date(2026, 1, 2))
    assert record.open == 10
    assert record.high == 12
    assert record.low == 9
    assert record.close == 11
    assert record.volume == 1000
    assert record.ingestion_run == run


@pytest.mark.django_db
def test_ingest_source_multiple_tickers(stock_source):
    stock_source.config_json = {"tickers": ["AAPL", "MSFT"], "period": "5d"}
    stock_source.save()

    history_aapl = make_history_df(
        [{"date": date(2026, 1, 2), "open": 10, "high": 12, "low": 9, "close": 11, "volume": 1000}]
    )
    history_msft = make_history_df(
        [{"date": date(2026, 1, 2), "open": 20, "high": 22, "low": 19, "close": 21, "volume": 2000}]
    )

    with patch(
        PATCH_TARGET,
        side_effect=mock_ticker_returning({"AAPL": history_aapl, "MSFT": history_msft}),
    ):
        call_command("ingest_source", "watchlist-mineria")

    run = IngestionRun.objects.get(source=stock_source)
    assert run.status == IngestionRun.Status.SUCCESS
    assert run.rows_ingested == 2
    assert PriceRecord.objects.filter(source=stock_source).count() == 2


@pytest.mark.django_db
def test_ingest_source_partial_failure_when_one_ticker_errors(stock_source):
    stock_source.config_json = {"tickers": ["AAPL", "BADTICKER"], "period": "5d"}
    stock_source.save()

    history_aapl = make_history_df(
        [{"date": date(2026, 1, 2), "open": 10, "high": 12, "low": 9, "close": 11, "volume": 1000}]
    )

    with patch(
        PATCH_TARGET,
        side_effect=mock_ticker_returning(
            {"AAPL": history_aapl, "BADTICKER": Exception("symbol not found")}
        ),
    ):
        call_command("ingest_source", "watchlist-mineria")

    run = IngestionRun.objects.get(source=stock_source)
    assert run.status == IngestionRun.Status.PARTIAL
    assert run.rows_ingested == 1
    assert len(run.errors_json) == 1
    assert run.errors_json[0]["ticker"] == "BADTICKER"
    assert "symbol not found" in run.errors_json[0]["error"]


@pytest.mark.django_db
def test_ingest_source_failed_when_all_tickers_error(stock_source):
    with patch(
        PATCH_TARGET,
        side_effect=mock_ticker_returning({"AAPL": Exception("network down")}),
    ):
        call_command("ingest_source", "watchlist-mineria")

    run = IngestionRun.objects.get(source=stock_source)
    assert run.status == IngestionRun.Status.FAILED
    assert run.rows_ingested == 0
    assert len(run.errors_json) == 1


@pytest.mark.django_db
def test_ingest_source_failed_when_history_is_empty(stock_source):
    empty_history = pd.DataFrame()

    with patch(PATCH_TARGET, side_effect=mock_ticker_returning({"AAPL": empty_history})):
        call_command("ingest_source", "watchlist-mineria")

    run = IngestionRun.objects.get(source=stock_source)
    assert run.status == IngestionRun.Status.FAILED
    assert run.rows_ingested == 0
    assert "vacía" in run.errors_json[0]["error"] or "vacia" in run.errors_json[0]["error"]


@pytest.mark.django_db
def test_ingest_source_upsert_does_not_duplicate_records(stock_source):
    history = make_history_df(
        [{"date": date(2026, 1, 2), "open": 10, "high": 12, "low": 9, "close": 11, "volume": 1000}]
    )

    with patch(PATCH_TARGET, side_effect=mock_ticker_returning({"AAPL": history})):
        call_command("ingest_source", "watchlist-mineria")

    updated_history = make_history_df(
        [{"date": date(2026, 1, 2), "open": 10, "high": 12, "low": 9, "close": 15, "volume": 9999}]
    )
    with patch(PATCH_TARGET, side_effect=mock_ticker_returning({"AAPL": updated_history})):
        call_command("ingest_source", "watchlist-mineria")

    assert PriceRecord.objects.filter(source=stock_source, ticker="AAPL").count() == 1
    record = PriceRecord.objects.get(ticker="AAPL", date=date(2026, 1, 2))
    assert record.close == 15
    assert record.volume == 9999
    assert IngestionRun.objects.filter(source=stock_source).count() == 2


@pytest.mark.django_db
def test_ingest_source_raises_when_data_source_missing():
    with pytest.raises(CommandError, match="no existe"):
        call_command("ingest_source", "no-existe")


@pytest.mark.django_db
def test_ingest_source_raises_when_wrong_type(db):
    DataSource.objects.create(
        name="cobre-lme",
        type=DataSource.SourceType.COMMODITY,
        config_json={"tickers": ["HG=F"]},
    )
    with pytest.raises(CommandError, match="tipo"):
        call_command("ingest_source", "cobre-lme")


@pytest.mark.django_db
def test_ingest_source_raises_when_inactive(db):
    DataSource.objects.create(
        name="watchlist-inactiva",
        type=DataSource.SourceType.STOCK_PRICE,
        config_json={"tickers": ["AAPL"]},
        active=False,
    )
    with pytest.raises(CommandError, match="inactivo"):
        call_command("ingest_source", "watchlist-inactiva")


@pytest.mark.django_db
def test_ingest_source_raises_when_no_tickers_configured(db):
    DataSource.objects.create(
        name="watchlist-vacia",
        type=DataSource.SourceType.STOCK_PRICE,
        config_json={},
        active=True,
    )
    with pytest.raises(CommandError, match="tickers"):
        call_command("ingest_source", "watchlist-vacia")


@pytest.mark.django_db
def test_ingest_source_never_calls_real_yfinance_network(stock_source):
    """
    Si yf.Ticker no está mockeado, cualquier intento de red real fallaría este
    test por timeout/DNS en CI. Este test documenta la garantía: siempre se
    mockea la llamada, nunca se golpea la API real de yfinance.
    """
    history = make_history_df(
        [{"date": date(2026, 1, 2), "open": 10, "high": 12, "low": 9, "close": 11, "volume": 1000}]
    )
    with patch(PATCH_TARGET, side_effect=mock_ticker_returning({"AAPL": history})) as mocked:
        call_command("ingest_source", "watchlist-mineria")
        assert mocked.called
