from django.http import JsonResponse
from django.views.decorators.http import require_GET
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from ingestion.models import DataSource, IngestionRun, PriceRecord
from ingestion.services import IngestionError, run_ingestion

from .serializers import (
    DataSourceSerializer,
    IngestionRunSerializer,
    PriceRecordSerializer,
    QualityReportSerializer,
    TriggerSourceSerializer,
)


@require_GET
def healthz(request):
    """
    Healthcheck plano: sin auth, sin acceso a base de datos. Vista Django
    simple (no DRF) a propósito, para no depender de authentication/
    permission classes ni de nada que pueda fallar si la DB está caída.
    """
    return JsonResponse({"status": "ok"})


class DataSourceViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = DataSource.objects.all()
    serializer_class = DataSourceSerializer

    @action(detail=True, methods=["post"])
    def trigger(self, request, pk=None):
        source = self.get_object()

        body = TriggerSourceSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        period = body.validated_data.get("period")

        try:
            run = run_ingestion(source, period=period)
        except IngestionError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            IngestionRunSerializer(run).data, status=status.HTTP_201_CREATED
        )


class IngestionRunViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = IngestionRun.objects.select_related("source").all()
    serializer_class = IngestionRunSerializer

    @action(detail=True, methods=["get"], url_path="quality-report")
    def quality_report(self, request, pk=None):
        run = self.get_object()
        serializer = QualityReportSerializer(run.quality_report())
        return Response(serializer.data)


class PriceRecordViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = PriceRecord.objects.select_related("source", "ingestion_run").all()
    serializer_class = PriceRecordSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        ticker = self.request.query_params.get("ticker")
        source_id = self.request.query_params.get("source")
        if ticker:
            queryset = queryset.filter(ticker__iexact=ticker)
        if source_id:
            queryset = queryset.filter(source_id=source_id)
        return queryset
