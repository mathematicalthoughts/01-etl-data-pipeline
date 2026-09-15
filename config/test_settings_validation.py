"""
Valida que config/settings.py falle con un ImproperlyConfigured legible
cuando DATABASE_URL llega vacía o mal formada (en vez del traceback críptico
de dj_database_url, "Scheme '://' is unknown", que motivó este fix).

Cada test fuerza la re-ejecución del módulo de settings (importlib.reload)
bajo un DATABASE_URL distinto vía monkeypatch, y siempre lo deja restaurado
al valor real del entorno antes de terminar -- el resto de la suite depende
de django.conf.settings (un singleton aparte, nunca tocado acá), pero dejar
el módulo crudo consistente evita sorpresas si algo más lo reimporta.
"""

import importlib

import pytest
from django.core.exceptions import ImproperlyConfigured

import config.settings as settings_module


def _reload_with(monkeypatch, value):
    monkeypatch.setenv("DATABASE_URL", value)
    return lambda: importlib.reload(settings_module)


@pytest.mark.parametrize(
    "bad_value",
    ["", "not-a-url-at-all", "://missing-scheme-before-slashes"],
    ids=["vacia", "sin-separador-de-esquema", "empieza-con-separador"],
)
def test_invalid_database_url_raises_improperly_configured(monkeypatch, bad_value):
    """
    Nota: no se prueba "DATABASE_URL ausente de os.environ" por separado --
    python-decouple cae de vuelta al .env local si la key no está en
    os.environ, así que un delenv() no simula de verdad "no seteada" en este
    entorno de dev. La validación no distingue esos dos casos de todos
    modos: ambos resuelven a DATABASE_URL_RAW == "" (el `default=""` de
    config()), que es exactamente el caso "vacia" de acá abajo.
    """
    reload_settings = _reload_with(monkeypatch, bad_value)
    try:
        with pytest.raises(ImproperlyConfigured, match="DATABASE_URL"):
            reload_settings()
    finally:
        monkeypatch.undo()
        importlib.reload(settings_module)


def test_valid_database_url_does_not_raise_and_configures_database(monkeypatch):
    reload_settings = _reload_with(
        monkeypatch, "postgresql://scott:tiger@localhost:5432/etl_dev"
    )
    try:
        reload_settings()
        assert settings_module.DATABASES["default"]["NAME"] == "etl_dev"
        assert settings_module.DATABASES["default"]["USER"] == "scott"
        assert settings_module.DATABASES["default"]["HOST"] == "localhost"
    finally:
        monkeypatch.undo()
        importlib.reload(settings_module)
