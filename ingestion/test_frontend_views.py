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
        summary_source="gemini:gemini-3.8-flash",
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
def test_dashboard_labels_latest_llm_summary_with_provider_and_model(client, partial_run):
    response = client.get(reverse("dashboard"))
    content = response.content.decode()
    assert "falló por símbolo no encontrado" in content
    assert "Resumen IA - gemini/gemini-3.8-flash" in content


@pytest.mark.django_db
def test_dashboard_labels_fallback_summary_without_ai(client, partial_run):
    partial_run.summary_source = "fallback"
    partial_run.save(update_fields=["summary_source"])

    response = client.get(reverse("dashboard"))

    assert "Resumen automatico (sin IA)" in response.content.decode()


@pytest.mark.django_db
def test_dashboard_shows_ai_summary_percentage_for_last_30_days(client, stock_source):
    for source in ["gemini:primary", "groq:llama", "fallback", ""]:
        IngestionRun.objects.create(
            source=stock_source,
            status=IngestionRun.Status.SUCCESS,
            summary="resumen" if source else "",
            summary_source=source,
        )
    old_run = IngestionRun.objects.create(
        source=stock_source,
        status=IngestionRun.Status.SUCCESS,
        summary="resumen antiguo",
        summary_source="gemini:legacy",
    )
    IngestionRun.objects.filter(pk=old_run.pk).update(
        created_at=timezone.now() - timedelta(days=31)
    )

    response = client.get(reverse("dashboard"))

    assert response.context["ai_summary_rate_30d"] == 50.0
    content = response.content.decode()
    assert "Resumenes IA (30D)" in content
    assert "50.0%" in content


@pytest.mark.django_db
def test_all_frontend_pages_use_copper_market_data_pipeline_brand(
    client, stock_source, partial_run
):
    urls = [
        reverse("dashboard"),
        reverse("sources_list"),
        reverse("source_detail", args=[stock_source.pk]),
        reverse("runs_list"),
        reverse("run_detail", args=[partial_run.pk]),
        reverse("prices_explorer"),
    ]

    for url in urls:
        content = client.get(url).content.decode()
        assert "Copper Market Data Pipeline</title>" in content
        assert "ETL PIPELINE" not in content
        assert "ETL Pipeline" not in content
        assert "Market &amp; Commodities" not in content


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


# --- run detail --------------------------------------------------------


@pytest.mark.django_db
def test_run_detail_returns_200_with_ticker_breakdown(client, partial_run):
    response = client.get(reverse("run_detail", args=[partial_run.pk]))

    content = response.content.decode()
    assert response.status_code == 200
    assert "FCX" in content
    assert "SCCO" in content
    assert "symbol not found" in content
    assert "falló por símbolo no encontrado" in content  # run.summary


@pytest.mark.django_db
def test_run_detail_404_for_missing_run(client):
    response = client.get(reverse("run_detail", args=[999]))
    assert response.status_code == 404


# --- prices explorer -------------------------------------------------------


@pytest.mark.django_db
def test_runs_list_shows_dash_for_legacy_run(client, stock_source):
    """Legacy run (rows_ingested>0 pero rows_created==rows_updated==0) muestra '—'."""
    IngestionRun.objects.create(
        source=stock_source,
        status=IngestionRun.Status.SUCCESS,
        rows_ingested=168,
        rows_created=0,
        rows_updated=0,
    )

    response = client.get(reverse("runs_list"))
    content = response.content.decode()

    assert response.status_code == 200
    assert "—" in content


@pytest.mark.django_db
def test_runs_list_shows_numbers_for_new_run(client, stock_source):
    """Run nuevo con rows_created/updated definidos muestra los números reales."""
    IngestionRun.objects.create(
        source=stock_source,
        status=IngestionRun.Status.SUCCESS,
        rows_ingested=5,
        rows_created=3,
        rows_updated=2,
    )

    response = client.get(reverse("runs_list"))
    content = response.content.decode()

    assert response.status_code == 200
    assert "3 / 2" in content


@pytest.mark.django_db
def test_run_detail_shows_dash_for_legacy_run(client, stock_source):
    """run_detail muestra '—' en Nuevas y Actualizadas para runs legacy."""
    run = IngestionRun.objects.create(
        source=stock_source,
        status=IngestionRun.Status.SUCCESS,
        rows_ingested=168,
        rows_created=0,
        rows_updated=0,
    )

    response = client.get(reverse("run_detail", args=[run.pk]))
    content = response.content.decode()

    assert response.status_code == 200
    # Both KPI cards should show "—" (the dash may appear multiple times)
    assert content.count("—") >= 2


@pytest.mark.django_db
def test_run_detail_shows_numbers_for_new_run(client, stock_source):
    """run_detail muestra números reales de Nuevas/Actualizadas para runs nuevos."""
    run = IngestionRun.objects.create(
        source=stock_source,
        status=IngestionRun.Status.SUCCESS,
        rows_ingested=5,
        rows_created=3,
        rows_updated=2,
    )

    response = client.get(reverse("run_detail", args=[run.pk]))
    content = response.content.decode()

    assert response.status_code == 200
    # The KPI values appear individually in separate divs
    assert ">3<" in content
    assert ">2<" in content


# --- prices explorer -------------------------------------------------------


@pytest.mark.django_db
def test_prices_explorer_returns_200_with_no_data(client):
    response = client.get(reverse("prices_explorer"))
    assert response.status_code == 200


@pytest.mark.django_db
def test_prices_explorer_groups_by_ticker(client, stock_source, partial_run):
    PriceRecord.objects.create(
        source=stock_source,
        ingestion_run=partial_run,
        ticker="FCX",
        date=date(2026, 1, 3),
        open=11,
        high=13,
        low=10,
        close=12.5,
        volume=2000,
    )

    response = client.get(reverse("prices_explorer"))
    content = response.content.decode()

    assert response.status_code == 200
    assert "FCX" in content
    assert "2,000" in content  # volume_display con separador de miles


@pytest.mark.django_db
def test_prices_explorer_filters_by_ticker(client, stock_source):
    PriceRecord.objects.create(
        source=stock_source, ticker="FCX", date=date(2026, 1, 2),
        open=1, high=1, low=1, close=1, volume=1,
    )
    PriceRecord.objects.create(
        source=stock_source, ticker="SCCO", date=date(2026, 1, 2),
        open=1, high=1, low=1, close=1, volume=1,
    )

    response = client.get(reverse("prices_explorer"), {"ticker": "FCX"})
    content = response.content.decode()

    # el <select> de filtro lista todos los tickers disponibles a propósito;
    # lo que nos importa filtrar es qué grupo de precios se muestra.
    assert '<span class="gh-ticker">FCX</span>' in content
    assert '<span class="gh-ticker">SCCO</span>' not in content


@pytest.mark.django_db
def test_prices_explorer_filters_by_source(client, stock_source, inactive_source):
    PriceRecord.objects.create(
        source=stock_source, ticker="FCX", date=date(2026, 1, 2),
        open=1, high=1, low=1, close=1, volume=1,
    )
    PriceRecord.objects.create(
        source=inactive_source, ticker="AAPL", date=date(2026, 1, 2),
        open=1, high=1, low=1, close=1, volume=1,
    )

    response = client.get(reverse("prices_explorer"), {"source": stock_source.pk})
    content = response.content.decode()

    assert '<span class="gh-ticker">FCX</span>' in content
    assert '<span class="gh-ticker">AAPL</span>' not in content
