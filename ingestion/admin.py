from django.contrib import admin

from .models import DataSource, IngestionRun


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
