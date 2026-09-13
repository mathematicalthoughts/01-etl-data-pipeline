from rest_framework import serializers

from ingestion.models import DataSource, IngestionRun, PriceRecord


class DataSourceSerializer(serializers.ModelSerializer):
    class Meta:
        model = DataSource
        fields = [
            "id",
            "name",
            "type",
            "config_json",
            "active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class IngestionRunSerializer(serializers.ModelSerializer):
    source_name = serializers.CharField(source="source.name", read_only=True)

    class Meta:
        model = IngestionRun
        fields = [
            "id",
            "source",
            "source_name",
            "status",
            "rows_ingested",
            "errors_json",
            "summary",
            "started_at",
            "finished_at",
            "created_at",
        ]
        read_only_fields = fields


class PriceRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = PriceRecord
        fields = [
            "id",
            "source",
            "ingestion_run",
            "ticker",
            "date",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "created_at",
        ]
        read_only_fields = fields


class QualityReportSerializer(serializers.Serializer):
    run_id = serializers.IntegerField()
    source = serializers.CharField()
    status = serializers.CharField()
    rows_ingested = serializers.IntegerField()
    errors_json = serializers.JSONField()
    tickers_ingested = serializers.ListField(child=serializers.CharField())
    tickers_failed = serializers.ListField(child=serializers.CharField())
    success_rate = serializers.FloatField()


class TriggerSourceSerializer(serializers.Serializer):
    """Body opcional de POST /api/sources/{id}/trigger/ para overridear el period."""

    period = serializers.CharField(required=False, allow_blank=False)
