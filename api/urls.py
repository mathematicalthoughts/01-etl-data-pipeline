from rest_framework.routers import DefaultRouter

from .views import DataSourceViewSet, IngestionRunViewSet, PriceRecordViewSet

router = DefaultRouter()
router.register("runs", IngestionRunViewSet, basename="run")
router.register("sources", DataSourceViewSet, basename="source")
router.register("prices", PriceRecordViewSet, basename="price")

urlpatterns = router.urls
