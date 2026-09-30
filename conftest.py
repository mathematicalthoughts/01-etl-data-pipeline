import os
from urllib.parse import parse_qs, urlparse
from unittest.mock import MagicMock, patch

import pytest
from decouple import config


def _guard_remote_test_database(database_url, allow_remote):
    """Abort before Django can connect pytest to the production Neon database."""
    parsed = urlparse(database_url)
    hosts = [parsed.hostname or "", *parse_qs(parsed.query).get("host", [])]
    if any("neon.tech" in host.lower() for host in hosts) and allow_remote != "1":
        raise pytest.UsageError(
            "Refusing to run tests against a neon.tech database. Use the local "
            "Docker database or set ALLOW_REMOTE_TEST_DB=1 explicitly."
        )


_guard_remote_test_database(
    config("DATABASE_URL", default=""),
    os.environ.get("ALLOW_REMOTE_TEST_DB", ""),
)


@pytest.fixture(autouse=True)
def _mock_llm_network_by_default(settings):
    """
    Nunca golpear la API real de Gemini en tests: por default, cualquier
    llamada a genai.Client(...) (hecha por generate_run_summary/run_ingestion)
    devuelve un mock con una respuesta "canned".

    Un test que quiera controlar el texto o el comportamiento de Gemini puede
    envolver su propio `with patch("ingestion.services.genai.Client", ...)`
    dentro del cuerpo del test: ese patch anidado toma precedencia mientras
    esté activo y luego vuelve a este default al salir del `with`.
    """
    fake_response = MagicMock()
    fake_response.text = "Resumen de prueba generado automáticamente."
    fake_client = MagicMock()
    fake_client.models.generate_content.return_value = fake_response

    settings.GEMINI_API_KEY = "test-gemini-key"
    settings.GEMINI_MODEL = "gemini-test"
    settings.GEMINI_FALLBACK_MODEL = ""
    settings.GROQ_API_KEY = ""
    settings.GROQ_MODEL = ""

    with (
        patch("ingestion.services.genai.Client", return_value=fake_client),
        patch(
            "ingestion.services.httpx.post",
            side_effect=AssertionError("Groq network must be mocked explicitly in tests"),
        ),
    ):
        yield fake_client
