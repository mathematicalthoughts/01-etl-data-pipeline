import json
from datetime import timedelta

from django.conf import settings
from django.db.models import Count, Sum
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from .models import DataSource, IngestionRun, PriceRecord

_RATE_CLASS_BY_STATUS = {
    IngestionRun.Status.SUCCESS: "ok",
    IngestionRun.Status.PARTIAL: "warn",
    IngestionRun.Status.FAILED: "danger",
}


def _annotate_run(run):
    """
    Agrega al objeto (no persistido) los valores derivados que las plantillas
    necesitan y que no son campos del modelo: duración calculada y el primer
    error en texto plano para las vistas de listado.
    """
    if run.started_at and run.finished_at:
        run.duration_seconds = (run.finished_at - run.started_at).total_seconds()
    else:
        run.duration_seconds = None

    if run.errors_json:
        first = run.errors_json[0]
        run.first_error = f"{first.get('ticker', '?')}: {first.get('error', 'error desconocido')}"
    else:
        run.first_error = None

    return run


def _sparkline_points(records, width=90, height=24):
    """
    Genera los puntos de un <polyline> a partir de una lista de PriceRecord
    en orden cronológico (más viejo primero), normalizando el close entre
    0 y `height`.
    """
    closes = [r.close for r in records]
    if len(closes) < 2:
        return ""

    lo, hi = min(closes), max(closes)
    span = hi - lo or 1
    step = width / (len(closes) - 1)

    points = []
    for i, close in enumerate(closes):
        x = round(i * step, 1)
        y = round(height - ((close - lo) / span) * height, 1)
        points.append(f"{x},{y}")
    return " ".join(points)


def dashboard(request):
    sources = DataSource.objects.all()

    cutoff_30d = timezone.now() - timedelta(days=30)
    runs_30d = IngestionRun.objects.filter(created_at__gte=cutoff_30d)
    total_runs_30d = runs_30d.count()
    success_runs_30d = runs_30d.filter(status=IngestionRun.Status.SUCCESS).count()
    success_rate_30d = (
        round(success_runs_30d / total_runs_30d * 100, 1) if total_runs_30d else None
    )
    rows_30d = runs_30d.aggregate(total=Sum("rows_ingested"))["total"] or 0
    runs_today = IngestionRun.objects.filter(created_at__date=timezone.now().date()).count()

    source_rows = []
    for source in sources:
        last_run = source.runs.order_by("-created_at").first()
        source_rows.append(
            {
                "source": source,
                "last_run": last_run,
                "success_rate": (
                    last_run.quality_report()["success_rate"] if last_run else None
                ),
            }
        )

    recent_runs = [
        _annotate_run(run)
        for run in IngestionRun.objects.select_related("source").order_by("-created_at")[:10]
    ]
    latest_summary_run = (
        IngestionRun.objects.exclude(summary="").order_by("-created_at").first()
    )

    context = {
        "active_view": "dashboard",
        "active_sources_count": sources.filter(active=True).count(),
        "total_sources_count": sources.count(),
        "success_rate_30d": success_rate_30d,
        "runs_today": runs_today,
        "rows_30d": rows_30d,
        "source_rows": source_rows,
        "recent_runs": recent_runs,
        "latest_summary_run": latest_summary_run,
    }
    return render(request, "dashboard.html", context)


def sources_list(request):
    rows = [
        {"source": source, "last_run": source.runs.order_by("-created_at").first()}
        for source in DataSource.objects.all()
    ]
    return render(request, "sources_list.html", {"active_view": "sources", "rows": rows})


def source_detail(request, pk):
    source = get_object_or_404(DataSource, pk=pk)
    runs = [_annotate_run(run) for run in source.runs.order_by("-created_at")]
    return render(
        request,
        "source_detail.html",
        {"active_view": "sources", "source": source, "runs": runs},
    )


def runs_list(request):
    selected_status = request.GET.get("status", "").strip().lower()

    queryset = IngestionRun.objects.select_related("source").order_by("-created_at")
    if selected_status in IngestionRun.Status.values:
        queryset = queryset.filter(status=selected_status)

    runs = [_annotate_run(run) for run in queryset]

    return render(
        request,
        "runs_list.html",
        {"active_view": "runs", "runs": runs, "selected_status": selected_status},
    )


def run_detail(request, pk):
    run = get_object_or_404(IngestionRun.objects.select_related("source"), pk=pk)
    _annotate_run(run)
    report = run.quality_report()

    rows_by_ticker = dict(
        run.price_records.values_list("ticker").annotate(rows=Count("id"))
    )
    errors_by_ticker = {
        err.get("ticker"): err.get("error")
        for err in (run.errors_json or [])
        if err.get("ticker")
    }
    ticker_rows = [
        {"ticker": t, "ok": True, "rows": rows_by_ticker[t], "error": None}
        for t in sorted(rows_by_ticker)
    ] + [
        {"ticker": t, "ok": False, "rows": None, "error": msg}
        for t, msg in sorted(errors_by_ticker.items())
    ]

    context = {
        "active_view": "runs",
        "run": run,
        "report": report,
        "ticker_rows": ticker_rows,
        "tickers_total_count": len(ticker_rows),
        "rate_class": _RATE_CLASS_BY_STATUS.get(run.status, ""),
        "errors_display": [
            json.dumps(err, ensure_ascii=False) for err in (run.errors_json or [])
        ],
        "gemini_model": settings.GEMINI_MODEL,
    }
    return render(request, "run_detail.html", context)


def prices_explorer(request):
    ticker = request.GET.get("ticker", "").strip()
    source_id = request.GET.get("source", "").strip()

    records = PriceRecord.objects.select_related("source").order_by("ticker", "-date")
    if ticker:
        records = records.filter(ticker__iexact=ticker)
    if source_id:
        records = records.filter(source_id=source_id)

    buckets = {}
    order = []
    for record in records:
        bucket = buckets.setdefault(record.ticker, [])
        if record.ticker not in order:
            order.append(record.ticker)
        if len(bucket) < 10:
            record.volume_display = f"{record.volume:,}"
            bucket.append(record)

    ticker_groups = []
    for t in order:
        recs = buckets[t]  # más reciente primero
        chronological = list(reversed(recs))
        closes = [r.close for r in chronological]
        ticker_groups.append(
            {
                "ticker": t,
                "source": recs[0].source,
                "records": recs,
                "last_close": recs[0].close,
                "sparkline_points": _sparkline_points(chronological),
                "trend_up": len(closes) >= 2 and closes[-1] >= closes[0],
            }
        )

    context = {
        "active_view": "prices",
        "ticker_groups": ticker_groups,
        "tickers": PriceRecord.objects.order_by("ticker").values_list("ticker", flat=True).distinct(),
        "sources": DataSource.objects.order_by("name"),
        "selected_ticker": ticker,
        "selected_source": source_id,
    }
    return render(request, "prices_explorer.html", context)
