import logging

from celery import shared_task

from .models import DataSource
from .services import run_ingestion

logger = logging.getLogger(__name__)


@shared_task
def run_scheduled_ingestions():
    """
    Recorre todos los DataSource activos de tipo stock_price y corre
    run_ingestion() para cada uno. Un error en una fuente (de validación o
    inesperado) se captura y registra sin interrumpir la ingesta de las
    demás fuentes.

    Programada cada 4 horas en horario de mercado vía django-celery-beat
    (ver management command `setup_schedule`), no hardcodeada en código.
    """
    sources = DataSource.objects.filter(
        type=DataSource.SourceType.STOCK_PRICE, active=True
    )

    succeeded = []
    failed = []

    for source in sources:
        try:
            run = run_ingestion(source)
            succeeded.append(
                {"source": source.name, "run_id": run.id, "status": run.status}
            )
        except Exception as exc:
            logger.exception(
                "run_scheduled_ingestions: fallo al ingerir la fuente '%s'",
                source.name,
            )
            failed.append({"source": source.name, "error": str(exc)})

    return {"succeeded": succeeded, "failed": failed}
