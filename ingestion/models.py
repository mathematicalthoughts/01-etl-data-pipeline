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
