from django.core.management.base import BaseCommand, CommandError

from ingestion.models import DataSource
from ingestion.services import IngestionError, run_ingestion


class Command(BaseCommand):
    help = (
        "Descarga precios OHLCV de yfinance para un DataSource de tipo "
        "stock_price y los guarda como PriceRecord, registrando un IngestionRun."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "source_name", type=str, help="Nombre exacto del DataSource a ingerir."
        )
        parser.add_argument(
            "--period",
            type=str,
            default=None,
            help=(
                "Override del 'period' de yfinance (ej. '1mo', '5d'). "
                "Si no se pasa, usa config_json['period'] o '1mo' por default."
            ),
        )

    def handle(self, *args, **options):
        source_name = options["source_name"]

        try:
            source = DataSource.objects.get(name=source_name)
        except DataSource.DoesNotExist as exc:
            raise CommandError(f"DataSource '{source_name}' no existe.") from exc

        try:
            run = run_ingestion(source, period=options["period"])
        except IngestionError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"IngestionRun #{run.id} — status={run.status}, "
                f"rows_ingested={run.rows_ingested}, errors={len(run.errors_json)}"
            )
        )
