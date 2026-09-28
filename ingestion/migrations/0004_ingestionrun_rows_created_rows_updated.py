from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ingestion", "0003_seed_initial_datasources"),
    ]

    operations = [
        migrations.AddField(
            model_name="ingestionrun",
            name="rows_created",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="ingestionrun",
            name="rows_updated",
            field=models.PositiveIntegerField(default=0),
        ),
    ]
