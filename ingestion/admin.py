from django.contrib import admin

from .models import DataSource, IngestionRun, PriceRecord


@admin.register(DataSource)
class DataSourceAdmin(admin.ModelAdmin):
    list_display = ("name", "type", "active", "updated_at")
    list_filter = ("type", "active")
    search_fields = ("name",)


@admin.register(IngestionRun)
class IngestionRunAdmin(admin.ModelAdmin):
    list_display = ("source", "status", "rows_ingested", "started_at", "finished_at")
    list_filter = ("status", "source")
    date_hierarchy = "created_at"
    readonly_fields = ("created_at",)


@admin.register(PriceRecord)
class PriceRecordAdmin(admin.ModelAdmin):
    list_display = ("ticker", "date", "close", "volume", "source")
    list_filter = ("source", "ticker")
    date_hierarchy = "date"
    search_fields = ("ticker",)
