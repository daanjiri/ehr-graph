"""Pruebas de configuración y protecciones de la demo pública."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from agente import acotar_entrada
from api import operacion
from api.chat import PeticionChat, chat
from api.limites import direccion_cliente, hash_cliente, reservar


class ResultadoFalso:
    def __init__(self, fila):
        self.fila = fila

    def single(self, strict=False):
        assert strict is True
        return self.fila


class SesionFalsa:
    def __init__(self, fila):
        self.fila = fila
        self.parametros = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def run(self, _query, **parametros):
        self.parametros = parametros
        return ResultadoFalso(self.fila)


class DriverFalso:
    def __init__(self, fila):
        self.sesion = SesionFalsa(fila)

    def session(self):
        return self.sesion


def test_peticion_chat_limita_longitud():
    with pytest.raises(ValidationError):
        PeticionChat(paciente_id="p1", mensaje="x" * 501)


def test_hash_cliente_no_expone_direccion():
    digest = hash_cliente("203.0.113.20")
    assert digest == hash_cliente("203.0.113.20")
    assert "203.0.113.20" not in digest
    assert len(digest) == 64


def test_direccion_cliente_prefiere_primer_forwarded():
    request = SimpleNamespace(
        headers={"x-forwarded-for": "203.0.113.20, 10.0.0.2"},
        client=SimpleNamespace(host="127.0.0.1"),
    )
    assert direccion_cliente(request) == "203.0.113.20"


def test_reservar_construye_periodos_sin_ip():
    driver = DriverFalso({
        "permitido": True,
        "global_count": 4,
        "client_count": 1,
    })
    resultado = reservar(
        driver,
        "hash-seguro",
        datetime(2026, 7, 30, tzinfo=timezone.utc),
    )
    assert resultado["permitido"] is True
    assert driver.sesion.parametros["global_key"] == "global:2026-07"
    assert driver.sesion.parametros["client_key"] == "cliente:2026-07-30:hash-seguro"


def test_health_no_depende_de_servicios_externos():
    assert operacion.health() == {"status": "ok"}


def test_ready_devuelve_503_si_neo4j_falla(monkeypatch):
    def falla(_query):
        raise RuntimeError("offline")

    monkeypatch.setattr(operacion, "q", falla)
    with pytest.raises(HTTPException) as error:
        operacion.ready()
    assert error.value.status_code == 503


def test_keepalive_rechaza_token_incorrecto(monkeypatch):
    monkeypatch.setattr(operacion, "KEEPALIVE_TOKEN", "correcto")
    with pytest.raises(HTTPException) as error:
        operacion.keepalive("Bearer incorrecto")
    assert error.value.status_code == 401


def test_chat_sin_api_key_devuelve_503(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    peticion = PeticionChat(paciente_id="p1", mensaje="hola")
    request = SimpleNamespace(headers={}, client=SimpleNamespace(host="127.0.0.1"))
    with pytest.raises(HTTPException) as error:
        chat(peticion, request)
    assert error.value.status_code == 503


@pytest.mark.parametrize(
    "herramienta",
    [
        "buscar_semantico",
        "timeline",
        "expandir_contexto",
        "cadena_causal",
        "medicacion_activa",
        "listar_pacientes",
    ],
)
def test_scope_del_chat_sobrescribe_paciente_del_modelo(herramienta):
    entrada = acotar_entrada(
        herramienta,
        {"paciente_id": "paciente-ajeno"},
        "paciente-seleccionado",
    )
    assert entrada["paciente_id"] == "paciente-seleccionado"
