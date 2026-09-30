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


# --- ALLOWED_HOSTS + RENDER_EXTERNAL_HOSTNAME -------------------------------


def test_render_external_hostname_is_added_to_allowed_hosts(monkeypatch):
    monkeypatch.setenv("RENDER_EXTERNAL_HOSTNAME", "etl-pipeline-abcd.onrender.com")
    try:
        importlib.reload(settings_module)
        assert "etl-pipeline-abcd.onrender.com" in settings_module.ALLOWED_HOSTS
        assert "localhost" in settings_module.ALLOWED_HOSTS  # se suma, no reemplaza
    finally:
        monkeypatch.undo()
        importlib.reload(settings_module)


def test_no_render_external_hostname_leaves_allowed_hosts_unaffected(monkeypatch):
    monkeypatch.delenv("RENDER_EXTERNAL_HOSTNAME", raising=False)
    try:
        importlib.reload(settings_module)
        assert "" not in settings_module.ALLOWED_HOSTS
    finally:
        monkeypatch.undo()
        importlib.reload(settings_module)


def test_empty_gemini_model_uses_default(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "")
    try:
        importlib.reload(settings_module)
        assert settings_module.GEMINI_MODEL == "gemini-3.8-flash"
    finally:
        monkeypatch.undo()
        importlib.reload(settings_module)


def test_pytest_uses_plain_staticfiles_storage():
    assert settings_module.TESTING is True
    assert settings_module.STORAGES["staticfiles"]["BACKEND"] == (
        "django.contrib.staticfiles.storage.StaticFilesStorage"
    )


def test_remote_test_database_guard_rejects_neon_without_opt_in():
    from conftest import _guard_remote_test_database

    with pytest.raises(pytest.UsageError, match="ALLOW_REMOTE_TEST_DB=1"):
        _guard_remote_test_database(
            "postgresql://user:password@ep-example.neon.tech/database",
            allow_remote="",
        )


@pytest.mark.parametrize(
    ("database_url", "allow_remote"),
    [
        ("postgresql://postgres:postgres@localhost:5433/etl_test", ""),
        ("postgresql://user:password@ep-example.neon.tech/database", "1"),
        ("postgresql:///database?host=ep-example.neon.tech", "1"),
    ],
)
def test_remote_test_database_guard_allows_local_or_explicit_opt_in(
    database_url, allow_remote
):
    from conftest import _guard_remote_test_database

    _guard_remote_test_database(database_url, allow_remote)


def test_remote_test_database_guard_rejects_neon_query_host_without_opt_in():
    from conftest import _guard_remote_test_database

    with pytest.raises(pytest.UsageError, match="ALLOW_REMOTE_TEST_DB=1"):
        _guard_remote_test_database(
            "postgresql:///database?host=ep-example.neon.tech",
            allow_remote="",
        )
