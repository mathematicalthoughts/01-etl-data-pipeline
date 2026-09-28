from django.core.management.base import BaseCommand

from ingestion.models import IngestionRun
from ingestion.services import _build_fallback_summary


class Command(BaseCommand):
    help = (
        "Rellena el campo summary de IngestionRun con estado SUCCESS o PARTIAL "
        "que tengan summary vacío, usando el resumen de respaldo determinístico "
        "(sin llamada a LLM). Idempotente: re-ejecutar no cambia los runs "
        "que ya tienen un resumen."
    )

    def handle(self, *args, **options):
        runs_to_update = IngestionRun.objects.filter(
            status__in=(IngestionRun.Status.SUCCESS, IngestionRun.Status.PARTIAL),
            summary="",
        )

        count = 0
        for run in runs_to_update:
            run.summary = _build_fallback_summary(run)
            run.save(update_fields=["summary"])
            count += 1

        self.stdout.write(
            self.style.SUCCESS(f"backfill_run_summaries: {count} run(s) actualizados.")
        )
