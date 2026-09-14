from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _mock_gemini_client_by_default():
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

    with patch("ingestion.services.genai.Client", return_value=fake_client):
        yield fake_client
