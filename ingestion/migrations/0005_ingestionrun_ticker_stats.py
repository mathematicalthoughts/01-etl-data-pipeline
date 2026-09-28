from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ingestion", "0004_ingestionrun_rows_created_rows_updated"),
    ]

    operations = [
        migrations.AddField(
            model_name="ingestionrun",
            name="ticker_stats",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
