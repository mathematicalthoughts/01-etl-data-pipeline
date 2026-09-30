from django.db import migrations, models
from django.db.models import Q


def populate_summary_source(apps, schema_editor):
    IngestionRun = apps.get_model("ingestion", "IngestionRun")
    fallback_prefixes = Q(summary__startswith="[Resumen automático sin LLM]") | Q(
        summary__startswith="[Resumen automatico sin LLM]"
    )
    IngestionRun.objects.filter(fallback_prefixes).update(summary_source="fallback")
    IngestionRun.objects.filter(summary_source="").exclude(summary="").update(
        summary_source="gemini:legacy"
    )


class Migration(migrations.Migration):
    dependencies = [
        ("ingestion", "0005_ingestionrun_ticker_stats"),
    ]

    operations = [
        migrations.AddField(
            model_name="ingestionrun",
            name="summary_source",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.RunPython(populate_summary_source, migrations.RunPython.noop),
    ]
