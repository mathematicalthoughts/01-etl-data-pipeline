import logging

from django.db import migrations

logger = logging.getLogger(__name__)

# Nombres deliberadamente distintos de los fixtures usados en tests
# ("watchlist-mineria", "cobre-lme") para no chocar con el unique=True de
# DataSource.name: pytest-django construye la base de tests corriendo todas
# las migraciones (no usamos --no-migrations), así que estos registros ya
# existen en cada test y un fixture con el mismo nombre rompería con
# IntegrityError.
WATCHLIST_COBRE_TICKERS = [
    "FCX",
    "SCCO",
    "BHP",
    "RIO",
    "TECK",
    "GLNCY",
    "COPX",
    "ANTO.L",
]

SEED_DATASOURCES = {
    "watchlist-cobre": {
        "type": "stock_price",
        "config_json": {"tickers": WATCHLIST_COBRE_TICKERS, "period": "1mo"},
        "active": True,
    },
    "cobre-futuro-comex": {
        "type": "commodity",
        "config_json": {"tickers": ["HG=F"], "period": "1mo"},
        "active": True,
    },
}


def seed_initial_datasources(apps, schema_editor):
    """
    Crea los DataSource de SEED_DATASOURCES solo si no existen todavía. Si
    la DB destino ya tiene un DataSource con ese `name` (ej. creado a mano
    desde /admin con otra config), no lo pisa: lo deja intacto y lo loguea.
    """
    DataSource = apps.get_model("ingestion", "DataSource")

    for name, defaults in SEED_DATASOURCES.items():
        if DataSource.objects.filter(name=name).exists():
            logger.warning(
                "seed_initial_datasources: se saltó el seed de '%s' porque "
                "ya existe un DataSource con ese nombre.",
                name,
            )
            continue
        DataSource.objects.create(name=name, **defaults)


def unseed_initial_datasources(apps, schema_editor):
    DataSource = apps.get_model("ingestion", "DataSource")
    DataSource.objects.filter(
        name__in=["watchlist-cobre", "cobre-futuro-comex"]
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("ingestion", "0002_pricerecord"),
    ]

    operations = [
        migrations.RunPython(seed_initial_datasources, unseed_initial_datasources),
    ]
