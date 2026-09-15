import logging
from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from ingestion.models import DataSource, IngestionRun, PriceRecord
from ingestion.services import generate_run_summary, run_ingestion

PATCH_TARGET = "ingestion.services.yf.Ticker"
GEMINI_PATCH_TARGET = "ingestion.services.genai.Client"


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


def make_fake_gemini_client(response_text="Resumen generado por Gemini."):
    fake_response = MagicMock()
    fake_response.text = response_text
    fake_client = MagicMock()
    fake_client.models.generate_content.return_value = fake_response
    return fake_client


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
    """
    macro_indicator sigue rechazado: a diferencia de commodity, requeriría
    una fuente de datos distinta de yfinance.
    """
    DataSource.objects.create(
        name="watchlist-macro",
        type=DataSource.SourceType.MACRO_INDICATOR,
        config_json={"tickers": ["CPI"]},
    )
    with pytest.raises(CommandError, match="tipo"):
        call_command("ingest_source", "watchlist-macro")


@pytest.mark.django_db
def test_ingest_source_success_for_commodity_type(db):
    """
    yf.Ticker(ticker).history(period=...) sirve igual para un future de
    commodity (ej. HG=F) que para una acción: sin lógica nueva de fetching.
    """
    commodity_source = DataSource.objects.create(
        name="cobre-lme",
        type=DataSource.SourceType.COMMODITY,
        config_json={"tickers": ["HG=F"], "period": "5d"},
        active=True,
    )
    history = make_history_df(
        [{"date": date(2026, 1, 2), "open": 4.5, "high": 4.6, "low": 4.4, "close": 4.55, "volume": 500}]
    )

    with patch(PATCH_TARGET, side_effect=mock_ticker_returning({"HG=F": history})):
        call_command("ingest_source", "cobre-lme")

    run = IngestionRun.objects.get(source=commodity_source)
    assert run.status == IngestionRun.Status.SUCCESS
    assert run.rows_ingested == 1
    assert PriceRecord.objects.filter(source=commodity_source, ticker="HG=F").count() == 1


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


# --- generate_run_summary / integración con Gemini ------------------------


@pytest.mark.django_db
def test_generate_run_summary_saves_text_from_gemini(stock_source):
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
    fake_client = make_fake_gemini_client(
        "AAPL se ingirió con éxito y sin fallos, tasa de éxito del 100%."
    )

    with patch(GEMINI_PATCH_TARGET, return_value=fake_client) as mocked_cls:
        summary = generate_run_summary(run)

    assert summary == "AAPL se ingirió con éxito y sin fallos, tasa de éxito del 100%."
    run.refresh_from_db()
    assert run.summary == "AAPL se ingirió con éxito y sin fallos, tasa de éxito del 100%."
    mocked_cls.assert_called_once()
    fake_client.models.generate_content.assert_called_once()

    _, kwargs = fake_client.models.generate_content.call_args
    assert "AAPL" in kwargs["contents"]
    assert run.status in kwargs["contents"]


@pytest.mark.django_db
def test_generate_run_summary_strips_whitespace_only_text(stock_source):
    run = IngestionRun.objects.create(source=stock_source, status=IngestionRun.Status.SUCCESS)
    fake_client = make_fake_gemini_client("   \n  ")

    with patch(GEMINI_PATCH_TARGET, return_value=fake_client):
        summary = generate_run_summary(run)

    assert summary == ""
    run.refresh_from_db()
    assert run.summary == ""


@pytest.mark.django_db
def test_generate_run_summary_handles_none_text(stock_source):
    run = IngestionRun.objects.create(source=stock_source, status=IngestionRun.Status.SUCCESS)
    fake_client = make_fake_gemini_client(None)

    with patch(GEMINI_PATCH_TARGET, return_value=fake_client):
        summary = generate_run_summary(run)

    assert summary == ""
    run.refresh_from_db()
    assert run.summary == ""


@pytest.mark.django_db
def test_run_ingestion_sets_summary_from_gemini_at_the_end(stock_source):
    history = make_history_df(
        [{"date": date(2026, 1, 2), "open": 10, "high": 12, "low": 9, "close": 11, "volume": 1000}]
    )
    fake_client = make_fake_gemini_client("Se ingirió AAPL sin errores, tasa de éxito del 100%.")

    with (
        patch(PATCH_TARGET, side_effect=mock_ticker_returning({"AAPL": history})),
        patch(GEMINI_PATCH_TARGET, return_value=fake_client),
    ):
        run = run_ingestion(stock_source)

    assert run.summary == "Se ingirió AAPL sin errores, tasa de éxito del 100%."


@pytest.mark.django_db
def test_run_ingestion_survives_gemini_failure_and_logs_it(stock_source, caplog):
    history = make_history_df(
        [{"date": date(2026, 1, 2), "open": 10, "high": 12, "low": 9, "close": 11, "volume": 1000}]
    )

    with (
        patch(PATCH_TARGET, side_effect=mock_ticker_returning({"AAPL": history})),
        patch(GEMINI_PATCH_TARGET, side_effect=Exception("Gemini rate limit")),
        caplog.at_level(logging.ERROR),
    ):
        run = run_ingestion(stock_source)

    assert run.status == IngestionRun.Status.SUCCESS
    assert run.rows_ingested == 1
    assert run.summary == ""
    assert "resumen de Gemini" in caplog.text
    assert str(run.id) in caplog.text


@pytest.mark.django_db
def test_generate_run_summary_never_calls_real_gemini_network(stock_source):
    """
    Documenta la garantía: generate_run_summary siempre pasa por un cliente
    mockeado en tests (acá explícito; en el resto de la suite, por el
    autouse fixture en conftest.py), nunca golpea la API real de Gemini.
    """
    run = IngestionRun.objects.create(source=stock_source, status=IngestionRun.Status.SUCCESS)
    fake_client = make_fake_gemini_client("ok")

    with patch(GEMINI_PATCH_TARGET, return_value=fake_client) as mocked:
        generate_run_summary(run)
        assert mocked.called
