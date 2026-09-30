import logging
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from datetime import timedelta

import httpx
import requests
import yfinance as yf
from django.conf import settings
from django.utils import timezone
from google import genai
from google.genai import errors as genai_errors

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

# Reintentos solo para errores transitorios de red: timeout o conexión
# rechazada/rota. Un símbolo inexistente o una respuesta vacía no son
# transitorios -- reintentar eso es ruido, no se reintentan.
TRANSIENT_NETWORK_ERRORS = (
    requests.exceptions.RequestException,
    ConnectionError,
    TimeoutError,
)
MAX_HISTORY_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = (1, 2)

# Summary provider retry constants. The deadline covers provider calls and
# backoff, so a degraded provider chain cannot hold an ingestion indefinitely.
MAX_SUMMARY_ATTEMPTS = 2
SUMMARY_BACKOFF_SECONDS = 2
SUMMARY_WAIT_BUDGET_SECONDS = 20


class _EmptySummaryError(Exception):
    """A provider returned no usable summary text."""


class _ProviderDeadlineError(Exception):
    """A provider did not finish inside the shared summary deadline."""


def _is_transient_summary_error(exc: Exception) -> bool:
    """Return whether a provider failure is safe and useful to retry."""
    if isinstance(exc, _EmptySummaryError):
        return True
    if isinstance(exc, genai_errors.ServerError):  # any 5xx
        return True
    if isinstance(exc, genai_errors.APIError) and exc.code == 429:  # rate limit
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        status_code = exc.response.status_code
        return status_code == 429 or status_code >= 500
    if isinstance(exc, httpx.TransportError):  # covers TimeoutException, ConnectError, etc.
        return True
    return False


def _call_gemini(prompt: str, model: str, timeout_seconds: float) -> str:
    client = genai.Client(
        api_key=settings.GEMINI_API_KEY,
        http_options={"timeout": max(1, int(timeout_seconds * 1000))},
    )
    response = client.models.generate_content(model=model, contents=prompt)
    return (response.text or "").strip()


def _call_groq(prompt: str, model: str, timeout_seconds: float) -> str:
    response = httpx.post(
        f"{settings.GROQ_BASE_URL.rstrip('/')}/chat/completions",
        headers={
            "Authorization": f"Bearer {settings.GROQ_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    try:
        return (response.json()["choices"][0]["message"]["content"] or "").strip()
    except (KeyError, IndexError, TypeError):
        return ""


def _call_before_deadline(call_provider, remaining: float):
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="run-summary")
    future = executor.submit(call_provider, remaining)
    try:
        return future.result(timeout=remaining)
    except FutureTimeoutError as exc:
        future.cancel()
        raise _ProviderDeadlineError("presupuesto de espera agotado") from exc
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def _try_summary_provider(run, source: str, call_provider, deadline: float):
    for attempt in range(1, MAX_SUMMARY_ATTEMPTS + 1):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        try:
            summary = _call_before_deadline(call_provider, remaining)
            if deadline - time.monotonic() <= 0:
                raise _ProviderDeadlineError("respuesta recibida fuera del presupuesto")
            if not summary:
                raise _EmptySummaryError("respuesta vacía")
            return summary
        except Exception as exc:
            if not _is_transient_summary_error(exc):
                logger.error(
                    "resumen %s: error no transitorio para IngestionRun #%s: %s",
                    source,
                    run.id,
                    exc,
                )
                return None
            if attempt == MAX_SUMMARY_ATTEMPTS:
                logger.error(
                    "resumen %s: reintentos agotados para IngestionRun #%s: %s",
                    source,
                    run.id,
                    exc,
                )
                return None
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            delay = min(SUMMARY_BACKOFF_SECONDS, remaining)
            logger.warning(
                "resumen %s: error transitorio para IngestionRun #%s "
                "(intento %d/%d): %s — reintentando en %.1fs.",
                source,
                run.id,
                attempt,
                MAX_SUMMARY_ATTEMPTS,
                exc,
                delay,
            )
            time.sleep(delay)
    return None


def _save_summary(run: IngestionRun, summary: str, source: str) -> str:
    run.summary = summary
    run.summary_source = source
    run.save(update_fields=["summary", "summary_source"])
    return summary


def _build_fallback_summary(run: IngestionRun) -> str:
    """Builds a deterministic fallback summary (no LLM) from run.quality_report()."""
    report = run.quality_report()
    source = report["source"]
    status = report["status"]
    rows_ingested = report["rows_ingested"]
    if report.get("legacy"):
        return (
            f"[Resumen automático sin LLM] Fuente: {source}, estado: {status}, "
            f"{rows_ingested} filas procesadas. "
            f"Detalle por instrumento no disponible (corrida anterior al registro por ticker)."
        )
    tickers_ingested_str = ", ".join(report["tickers_ingested"]) or "ninguno"
    tickers_failed_str = ", ".join(report["tickers_failed"]) or "ninguno"
    success_rate = report["success_rate"]
    return (
        f"[Resumen automático sin LLM] Fuente: {source}, estado: {status}, "
        f"{rows_ingested} filas ingeridas. "
        f"Tickers OK: {tickers_ingested_str}. "
        f"Tickers fallidos: {tickers_failed_str}. "
        f"Tasa de éxito: {success_rate}%."
    )


def _fetch_ticker_history(ticker: str, period: str):
    """
    Llama a yf.Ticker(ticker).history(period=...) con hasta
    MAX_HISTORY_ATTEMPTS intentos y backoff corto (1s, 2s) SOLO si la
    excepción es un error transitorio de red. Cualquier otra excepción se
    propaga de inmediato, sin reintentar.
    """
    for attempt in range(1, MAX_HISTORY_ATTEMPTS + 1):
        try:
            return yf.Ticker(ticker).history(period=period)
        except TRANSIENT_NETWORK_ERRORS:
            if attempt == MAX_HISTORY_ATTEMPTS:
                raise
            time.sleep(RETRY_BACKOFF_SECONDS[attempt - 1])


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
    rows_created_count = 0
    rows_updated_count = 0
    errors = []
    ticker_stats: dict = {}

    for ticker in tickers:
        ticker_stats[ticker] = {"created": 0, "updated": 0, "errors": 0}

        try:
            history = _fetch_ticker_history(ticker, resolved_period)
        except Exception as exc:
            errors.append({"ticker": ticker, "error": str(exc)})
            ticker_stats[ticker]["errors"] += 1
            continue

        if history is None or history.empty:
            errors.append(
                {"ticker": ticker, "error": "No se recibieron datos (respuesta vacía)."}
            )
            ticker_stats[ticker]["errors"] += 1
            continue

        for index, row in history.iterrows():
            try:
                _, created_flag = PriceRecord.objects.update_or_create(
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
                if created_flag:
                    rows_created_count += 1
                    ticker_stats[ticker]["created"] += 1
                else:
                    rows_updated_count += 1
                    ticker_stats[ticker]["updated"] += 1
                rows_ingested += 1
            except Exception as exc:
                errors.append(
                    {"ticker": ticker, "date": str(index.date()), "error": str(exc)}
                )
                ticker_stats[ticker]["errors"] += 1

    run.finished_at = timezone.now()
    run.rows_ingested = rows_ingested
    run.rows_created = rows_created_count
    run.rows_updated = rows_updated_count
    run.ticker_stats = ticker_stats
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


def reap_stale_running_runs(stale_after_minutes: int = 15) -> int:
    """
    Marca como FAILED cualquier IngestionRun que quedó en RUNNING por más de
    `stale_after_minutes` -- señal de que el proceso que lo estaba corriendo
    murió a mitad de camino (crash, kill por timeout) y nunca llegó a
    actualizar su propio estado. Pensado para llamarse al inicio de cada
    corrida real (`run_ingestions_now`), antes de programar ingestas nuevas.

    Devuelve la cantidad de runs marcados como FAILED.
    """
    cutoff = timezone.now() - timedelta(minutes=stale_after_minutes)
    stale_runs = IngestionRun.objects.filter(
        status=IngestionRun.Status.RUNNING, started_at__lt=cutoff
    )

    count = 0
    for run in stale_runs:
        run.status = IngestionRun.Status.FAILED
        run.finished_at = timezone.now()
        run.errors_json = [
            {
                "error": (
                    f"Run marcado FAILED automáticamente: excedió "
                    f"{stale_after_minutes}min en estado RUNNING, probable "
                    f"crash del proceso anterior."
                )
            }
        ]
        run.save(update_fields=["status", "finished_at", "errors_json"])
        count += 1

    return count


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
        "Eres un analista de datos. Resume en 2 o 3 líneas, en español y en "
        "lenguaje natural, el resultado de esta corrida de ingesta de precios "
        "de mercado para un reporte de calidad de datos. Menciona cuántos "
        "tickers se ingirieron, cuáles fallaron y por qué, y la tasa de éxito. "
        "No repitas los datos en formato de lista, redáctalo como prosa.\n\n"
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
    Evalúa proveedores configurados en orden y persiste texto + procedencia.
    Cada proveedor tiene hasta dos intentos para errores transitorios, todos
    compartiendo un presupuesto monotónico máximo de 20 segundos.
    """
    report = run.quality_report()
    prompt = _build_summary_prompt(run, report)

    deadline = time.monotonic() + SUMMARY_WAIT_BUDGET_SECONDS
    providers = []
    if settings.GEMINI_API_KEY:
        providers.append(
            (
                f"gemini:{settings.GEMINI_MODEL}",
                lambda timeout: _call_gemini(prompt, settings.GEMINI_MODEL, timeout),
            )
        )
        if settings.GEMINI_FALLBACK_MODEL:
            providers.append(
                (
                    f"gemini:{settings.GEMINI_FALLBACK_MODEL}",
                    lambda timeout: _call_gemini(
                        prompt, settings.GEMINI_FALLBACK_MODEL, timeout
                    ),
                )
            )
    if settings.GROQ_API_KEY and settings.GROQ_MODEL:
        providers.append(
            (
                f"groq:{settings.GROQ_MODEL}",
                lambda timeout: _call_groq(prompt, settings.GROQ_MODEL, timeout),
            )
        )

    for source, provider in providers:
        if deadline - time.monotonic() <= 0:
            break
        summary = _try_summary_provider(run, source, provider, deadline)
        if summary:
            return _save_summary(run, summary, source)

    return _save_summary(run, _build_fallback_summary(run), "fallback")
