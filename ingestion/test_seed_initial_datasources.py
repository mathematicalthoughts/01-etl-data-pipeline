import importlib
import logging

import pytest
from django.apps import apps as django_apps

from ingestion.models import DataSource
from ingestion.services import INGESTABLE_SOURCE_TYPES

seed_migration = importlib.import_module(
    "ingestion.migrations.0003_seed_initial_datasources"
)


@pytest.mark.django_db
def test_seed_migration_creates_watchlist_cobre_stock_source():
    source = DataSource.objects.get(name="watchlist-cobre")

    assert source.type == DataSource.SourceType.STOCK_PRICE
    assert source.active is True
    assert source.config_json["tickers"] == [
        "FCX",
        "SCCO",
        "BHP",
        "RIO",
        "TECK",
        "GLNCY",
        "COPX",
        "ANTO.L",
    ]
    assert source.config_json["period"] == "1mo"


@pytest.mark.django_db
def test_seed_migration_creates_cobre_futuro_commodity_source():
    source = DataSource.objects.get(name="cobre-futuro-comex")

    assert source.type == DataSource.SourceType.COMMODITY
    assert source.active is True
    assert source.config_json["tickers"] == ["HG=F"]


@pytest.mark.django_db
def test_seed_migration_sources_are_both_picked_up_by_scheduled_ingestion():
    """
    watchlist-cobre (stock_price) y cobre-futuro-comex (commodity) son
    ambos tipos ingestables vía yfinance, así que run_scheduled_ingestions()
    -- que filtra por INGESTABLE_SOURCE_TYPES -- debe recoger a los dos.
    """
    scheduled = DataSource.objects.filter(
        type__in=INGESTABLE_SOURCE_TYPES, active=True
    )

    assert set(scheduled.values_list("name", flat=True)) == {
        "watchlist-cobre",
        "cobre-futuro-comex",
    }


@pytest.mark.django_db
def test_seed_migration_is_idempotent_when_rerun():
    seed_migration.seed_initial_datasources(django_apps, None)
    seed_migration.seed_initial_datasources(django_apps, None)

    assert DataSource.objects.filter(name="watchlist-cobre").count() == 1
    assert DataSource.objects.filter(name="cobre-futuro-comex").count() == 1


@pytest.mark.django_db
def test_unseed_migration_removes_both_datasources():
    seed_migration.unseed_initial_datasources(django_apps, None)

    assert not DataSource.objects.filter(
        name__in=["watchlist-cobre", "cobre-futuro-comex"]
    ).exists()


@pytest.mark.django_db
def test_seed_migration_does_not_overwrite_existing_datasource_with_different_config(caplog):
    """
    Si la DB destino ya tiene un DataSource con ese `name` (ej. creado a
    mano desde /admin con otra config), el seed no lo debe pisar: se
    mantiene la config original intacta y se loguea un warning.
    """
    DataSource.objects.filter(name="watchlist-cobre").delete()
    DataSource.objects.create(
        name="watchlist-cobre",
        type=DataSource.SourceType.STOCK_PRICE,
        config_json={"tickers": ["AAPL"], "period": "5d"},
        active=False,
    )

    with caplog.at_level(logging.WARNING):
        seed_migration.seed_initial_datasources(django_apps, None)

    source = DataSource.objects.get(name="watchlist-cobre")
    assert source.config_json == {"tickers": ["AAPL"], "period": "5d"}
    assert source.active is False
    assert "watchlist-cobre" in caplog.text
    assert "se saltó el seed" in caplog.text
