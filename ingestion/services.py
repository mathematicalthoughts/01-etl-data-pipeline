import yfinance as yf
from django.utils import timezone

from .models import DataSource, IngestionRun, PriceRecord


class IngestionError(Exception):
    """Error de validación antes de poder lanzar una corrida de ingesta."""


def run_ingestion(source: DataSource, period: str | None = None) -> IngestionRun:
    """
    Descarga OHLCV de yfinance para los tickers de `source.config_json` y los
    guarda como PriceRecord, registrando el resultado en un IngestionRun.

    Usado tanto por el management command `ingest_source` como por el
    endpoint `POST /api/sources/{id}/trigger/`.
    """
    if source.type != DataSource.SourceType.STOCK_PRICE:
        raise IngestionError(
            f"DataSource '{source.name}' es de tipo '{source.type}', "
            f"se esperaba '{DataSource.SourceType.STOCK_PRICE}'."
        )

    if not source.active:
        raise IngestionError(f"DataSource '{source.name}' está inactivo.")

    tickers = source.config_json.get("tickers") or []
    if not tickers:
        raise IngestionError(
            f"DataSource '{source.name}' no tiene 'tickers' definidos en config_json."
        )

    resolved_period = period or source.config_json.get("period", "1mo")

    run = IngestionRun.objects.create(
        source=source,
        status=IngestionRun.Status.RUNNING,
        started_at=timezone.now(),
    )

    rows_ingested = 0
    errors = []

    for ticker in tickers:
        try:
            history = yf.Ticker(ticker).history(period=resolved_period)
        except Exception as exc:
            errors.append({"ticker": ticker, "error": str(exc)})
            continue

        if history is None or history.empty:
            errors.append(
                {"ticker": ticker, "error": "No se recibieron datos (respuesta vacía)."}
            )
            continue

        for index, row in history.iterrows():
            try:
                PriceRecord.objects.update_or_create(
                    source=source,
                    ticker=ticker,
                    date=index.date(),
                    defaults={
                        "ingestion_run": run,
                        "open": row["Open"],
                        "high": row["High"],
                        "low": row["Low"],
                        "close": row["Close"],
                        "volume": int(row["Volume"]),
                    },
                )
                rows_ingested += 1
            except Exception as exc:
                errors.append(
                    {"ticker": ticker, "date": str(index.date()), "error": str(exc)}
                )

    run.finished_at = timezone.now()
    run.rows_ingested = rows_ingested
    run.errors_json = errors

    if errors and rows_ingested == 0:
        run.status = IngestionRun.Status.FAILED
    elif errors:
        run.status = IngestionRun.Status.PARTIAL
    else:
        run.status = IngestionRun.Status.SUCCESS

    run.save()
    return run
