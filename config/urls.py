"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.contrib import admin
from django.urls import include, path

from api.views import healthz
from ingestion.views import (
    dashboard,
    prices_explorer,
    run_detail,
    runs_list,
    source_detail,
    sources_list,
)

urlpatterns = [
    path("admin/", admin.site.urls),
    path("healthz/", healthz, name="healthz"),
    path("api/", include("api.urls")),
    path("", dashboard, name="dashboard"),
    path("sources/", sources_list, name="sources_list"),
    path("sources/<int:pk>/", source_detail, name="source_detail"),
    path("runs/", runs_list, name="runs_list"),
    path("runs/<int:pk>/", run_detail, name="run_detail"),
    path("prices/", prices_explorer, name="prices_explorer"),
]
