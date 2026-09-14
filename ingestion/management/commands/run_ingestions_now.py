from django.core.management.base import BaseCommand

from ingestion.tasks import run_scheduled_ingestions


class Command(BaseCommand):
    help = (
        "Corre la lógica de run_scheduled_ingestions() de forma síncrona, "
        "llamando la tarea directamente (sin .delay()/.apply_async()) — no "
        "depende de un worker de Celery ni de Redis. Pensado para dispararse "
        "desde un cron externo (ej. GitHub Actions) cuando no hay un worker "
        "de Celery corriendo 24/7 en producción."
    )

    def handle(self, *args, **options):
        result = run_scheduled_ingestions()

        succeeded = result["succeeded"]
        failed = result["failed"]

        for item in succeeded:
            self.stdout.write(
                self.style.SUCCESS(
                    f"OK   {item['source']}: run #{item['run_id']} "
                    f"status={item['status']}"
                )
            )
        for item in failed:
            self.stdout.write(
                self.style.ERROR(f"FAIL {item['source']}: {item['error']}")
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"run_ingestions_now: {len(succeeded)} fuente(s) OK, "
                f"{len(failed)} fuente(s) fallida(s)."
            )
        )
