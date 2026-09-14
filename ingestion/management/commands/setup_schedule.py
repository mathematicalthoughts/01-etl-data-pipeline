from django.core.management.base import BaseCommand
from django_celery_beat.models import CrontabSchedule, PeriodicTask

TASK_NAME = "run_scheduled_ingestions"
TASK_PATH = "ingestion.tasks.run_scheduled_ingestions"


class Command(BaseCommand):
    help = (
        "Crea (o actualiza) el PeriodicTask de django-celery-beat que corre "
        "run_scheduled_ingestions cada 4 horas en horario de mercado "
        "(9, 13 y 17hs America/New_York, lunes a viernes). Idempotente: "
        "correrlo de nuevo no duplica el schedule."
    )

    def handle(self, *args, **options):
        schedule, _ = CrontabSchedule.objects.get_or_create(
            minute="0",
            hour="9,13,17",
            day_of_week="1-5",
            day_of_month="*",
            month_of_year="*",
            timezone="America/New_York",
        )

        task, created = PeriodicTask.objects.update_or_create(
            name=TASK_NAME,
            defaults={
                "task": TASK_PATH,
                "crontab": schedule,
                "interval": None,
                "enabled": True,
            },
        )

        verb = "creado" if created else "actualizado"
        self.stdout.write(
            self.style.SUCCESS(
                f"PeriodicTask '{TASK_NAME}' {verb} — {TASK_PATH} corre a las "
                f"9, 13 y 17hs (America/New_York), lunes a viernes."
            )
        )
