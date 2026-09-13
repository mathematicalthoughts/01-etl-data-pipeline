from django.db import models


class DataSource(models.Model):
    class SourceType(models.TextChoices):
        STOCK_PRICE = "stock_price", "Stock Price"
        COMMODITY = "commodity", "Commodity"
        MACRO_INDICATOR = "macro_indicator", "Macro Indicator"

    name = models.CharField(max_length=255, unique=True)
    type = models.CharField(max_length=32, choices=SourceType.choices)
    config_json = models.JSONField(default=dict, blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class IngestionRun(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"
        PARTIAL = "partial", "Partial Success"

    source = models.ForeignKey(
        DataSource, on_delete=models.CASCADE, related_name="runs"
    )
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING
    )
    rows_ingested = models.PositiveIntegerField(default=0)
    errors_json = models.JSONField(default=list, blank=True)
    summary = models.TextField(blank=True, default="")
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.source.name} — {self.status} ({self.created_at:%Y-%m-%d %H:%M})"

    def quality_report(self):
        """
        Resumen de completitud del run: qué tickers efectivamente quedaron con
        datos vs. cuáles fallaron, y una tasa de éxito sobre los intentados.
        """
        tickers_ingested = list(
            self.price_records.order_by("ticker")
            .values_list("ticker", flat=True)
            .distinct()
        )
        tickers_failed = sorted(
            {err.get("ticker") for err in (self.errors_json or []) if err.get("ticker")}
        )
        attempted = set(tickers_ingested) | set(tickers_failed)
        success_rate = (
            round(len(tickers_ingested) / len(attempted) * 100, 2) if attempted else 100.0
        )

        return {
            "run_id": self.id,
            "source": self.source.name,
            "status": self.status,
            "rows_ingested": self.rows_ingested,
            "errors_json": self.errors_json,
            "tickers_ingested": tickers_ingested,
            "tickers_failed": tickers_failed,
            "success_rate": success_rate,
        }


class PriceRecord(models.Model):
    source = models.ForeignKey(
        DataSource, on_delete=models.CASCADE, related_name="price_records"
    )
    ingestion_run = models.ForeignKey(
        IngestionRun,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="price_records",
    )
    ticker = models.CharField(max_length=20)
    date = models.DateField()
    open = models.FloatField()
    high = models.FloatField()
    low = models.FloatField()
    close = models.FloatField()
    volume = models.BigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["ticker", "date"]
        constraints = [
            models.UniqueConstraint(
                fields=["source", "ticker", "date"],
                name="unique_price_record_per_source_ticker_date",
            )
        ]

    def __str__(self):
        return f"{self.ticker} {self.date} ({self.source.name})"
