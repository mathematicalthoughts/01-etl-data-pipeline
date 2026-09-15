import logging

import yfinance as yf
from django.conf import settings
from django.utils import timezone
from google import genai

from .models import DataSource, IngestionRun, PriceRecord

logger = logging.getLogger(__name__)


class IngestionError(Exception):
    """Error de validación antes de poder lanzar una corrida de ingesta."""


# yf.Ticker(ticker).history(period=...) sirve igual para una acción que para
# un future de commodity (ej. HG=F) -- mismo fetch, sin lógica nueva. Un
# macro_indicator sí necesitaría una fuente de datos distinta, así que ese
# tipo se sigue rechazando.
INGESTABLE_SOURCE_TYPES = {
    DataSource.SourceType.STOCK_PRICE,
    DataSource.SourceType.COMMODITY,
}


def run_ingestion(source: DataSource, period: str | None = None) -> IngestionRun:
    """
    Descarga OHLCV de yfinance para los tickers de `source.config_json` y los
    guarda como PriceRecord, registrando el resultado en un IngestionRun.

    Usado tanto por el management command `ingest_source` como por el
    endpoint `POST /api/sources/{id}/trigger/`.
    """
    if source.type not in INGESTABLE_SOURCE_TYPES:
        allowed = ", ".join(sorted(INGESTABLE_SOURCE_TYPES))
        raise IngestionError(
            f"DataSource '{source.name}' es de tipo '{source.type}', "
            f"se esperaba uno de: {allowed}."
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

    try:
        generate_run_summary(run)
    except Exception:
        logger.exception(
            "No se pudo generar el resumen de Gemini para IngestionRun #%s", run.id
        )

    return run


def _build_summary_prompt(run: IngestionRun, report: dict) -> str:
    tickers_ingested = ", ".join(report["tickers_ingested"]) or "ninguno"
    tickers_failed = ", ".join(report["tickers_failed"]) or "ninguno"
    errors = (
        "; ".join(
            f"{e.get('ticker', '?')}: {e.get('error', 'error desconocido')}"
            for e in (run.errors_json or [])
        )
        or "sin errores"
    )

    return (
        "Sos un analista de datos. Resumí en 2 o 3 líneas, en español y en "
        "lenguaje natural, el resultado de esta corrida de ingesta de precios "
        "de mercado para un reporte de calidad de datos. Mencioná cuántos "
        "tickers se ingirieron, cuáles fallaron y por qué, y la tasa de éxito. "
        "No repitas los datos en formato de lista, redactalo como prosa.\n\n"
        f"- Fuente: {run.source.name}\n"
        f"- Estado del run: {run.status}\n"
        f"- Filas ingeridas: {run.rows_ingested}\n"
        f"- Tickers ingeridos correctamente: {tickers_ingested}\n"
        f"- Tickers que fallaron: {tickers_failed}\n"
        f"- Detalle de errores: {errors}\n"
        f"- Tasa de éxito: {report['success_rate']}%\n"
    )


def generate_run_summary(run: IngestionRun) -> str:
    """
    Genera (vía Gemini) y persiste en `run.summary` un resumen en lenguaje
    natural de 2-3 líneas de un IngestionRun: tickers ingeridos, tickers
    fallidos y por qué, y la tasa de éxito de `run.quality_report()`.
    """
    report = run.quality_report()
    prompt = _build_summary_prompt(run, report)

    client = genai.Client(api_key=settings.GEMINI_API_KEY)
    response = client.models.generate_content(
        model=settings.GEMINI_MODEL,
        contents=prompt,
    )

    summary = (response.text or "").strip()
    run.summary = summary
    run.save(update_fields=["summary"])
    return summary
