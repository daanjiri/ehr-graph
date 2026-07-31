"""Pruebas de configuración y protecciones de la demo pública."""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import anthropic
import pytest
from fastapi import HTTPException
from pydantic import ValidationError

import agente
from agente import (
    acotar_entrada,
    limpiar_pensamiento_otro_modelo,
    loop_agente_eventos,
)
from api import chat as chat_api, operacion
from api.chat import PeticionChat, chat, modelos, resolver_modelo
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


def test_catalogo_modelos_es_cerrado_y_sonnet_es_predeterminado():
    catalogo = modelos()
    assert catalogo["predeterminado"] == "claude-sonnet-5"
    assert [modelo["id"] for modelo in catalogo["modelos"]] == [
        "claude-haiku-4-5-20251001",
        "claude-sonnet-5",
        "claude-opus-5",
    ]
    assert all("admite_esfuerzo" not in modelo for modelo in catalogo["modelos"])


def test_modelo_arbitrario_es_rechazado():
    with pytest.raises(HTTPException) as error:
        resolver_modelo("claude-fable-5")
    assert error.value.status_code == 422


def test_cambiar_modelo_conserva_sesion():
    chat_api.SESIONES.clear()
    primera = PeticionChat(
        paciente_id="p1", mensaje="hola", modelo="claude-sonnet-5"
    )
    sesion_id, _ = chat_api._sesion(primera)
    segunda = PeticionChat(
        paciente_id="p1",
        mensaje="continúa",
        sesion_id=sesion_id,
        modelo="claude-opus-5",
    )
    sesion_continuada, _ = chat_api._sesion(segunda)
    assert sesion_continuada == sesion_id


def test_cambio_modelo_retira_solo_bloques_de_pensamiento():
    texto = SimpleNamespace(type="text", text="respuesta")
    herramienta = SimpleNamespace(type="tool_use", name="timeline")
    mensajes = [
        {
            "role": "assistant",
            "content": [
                SimpleNamespace(type="thinking", thinking="resumen"),
                SimpleNamespace(type="redacted_thinking"),
                texto,
                herramienta,
            ],
        },
        {"role": "user", "content": "siguiente"},
    ]

    limpiar_pensamiento_otro_modelo(mensajes)

    assert mensajes[0]["content"] == [texto, herramienta]
    assert mensajes[1]["content"] == "siguiente"


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


def test_chat_informa_modelo_efectivo_en_sse(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "solo-prueba")
    monkeypatch.setattr(chat_api.agente, "q", lambda *_args, **_kwargs: [{"nombre": "Ana"}])
    monkeypatch.setattr(
        chat_api,
        "reservar",
        lambda *_args, **_kwargs: {
            "permitido": True,
            "global_count": 1,
            "client_count": 1,
        },
    )
    monkeypatch.setattr(chat_api.agente, "driver", lambda: object())
    monkeypatch.setattr(
        chat_api.agente,
        "loop_agente_eventos",
        lambda *_args, **_kwargs: iter([{"tipo": "fin", "texto": "ok"}]),
    )
    chat_api.SESIONES.clear()
    peticion = PeticionChat(
        paciente_id="p1", mensaje="hola", modelo="claude-opus-5"
    )
    request = SimpleNamespace(headers={}, client=SimpleNamespace(host="127.0.0.1"))
    respuesta = chat(peticion, request)

    async def contenido():
        partes = []
        async for parte in respuesta.body_iterator:
            partes.append(parte.decode() if isinstance(parte, bytes) else parte)
        return "".join(partes)

    cuerpo = asyncio.run(contenido())
    assert '"modelo": "claude-opus-5"' in cuerpo


class StreamFalso:
    def __init__(self, respuesta, deltas=("ok",)):
        self.respuesta = respuesta
        self.text_stream = iter(deltas)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def get_final_message(self):
        return self.respuesta


class MensajesFalsos:
    def __init__(self, respuestas):
        self.respuestas = iter(respuestas)
        self.llamadas = []

    def stream(self, **parametros):
        self.llamadas.append(parametros)
        respuesta = next(self.respuestas)
        deltas = () if respuesta.stop_reason == "tool_use" else ("ok",)
        return StreamFalso(respuesta, deltas)


def test_sonnet_recibe_esfuerzo_medium(monkeypatch):
    respuesta = SimpleNamespace(
        stop_reason="end_turn",
        content=[SimpleNamespace(type="text", text="ok")],
    )
    mensajes_api = MensajesFalsos([respuesta])
    monkeypatch.setattr(
        anthropic,
        "Anthropic",
        lambda: SimpleNamespace(messages=mensajes_api),
    )

    historial = []
    eventos = list(loop_agente_eventos(historial, modelo="claude-sonnet-5"))

    assert eventos[-1] == {"tipo": "fin", "texto": "ok"}
    assert mensajes_api.llamadas[0]["model"] == "claude-sonnet-5"
    assert mensajes_api.llamadas[0]["output_config"] == {"effort": "medium"}
    assert historial[-1] == {"role": "assistant", "content": respuesta.content}


def test_haiku_no_recibe_parametro_esfuerzo(monkeypatch):
    respuesta = SimpleNamespace(
        stop_reason="end_turn",
        content=[SimpleNamespace(type="text", text="ok")],
    )
    mensajes_api = MensajesFalsos([respuesta])
    monkeypatch.setattr(
        anthropic,
        "Anthropic",
        lambda: SimpleNamespace(messages=mensajes_api),
    )

    list(loop_agente_eventos([], modelo="claude-haiku-4-5-20251001"))

    assert "output_config" not in mensajes_api.llamadas[0]


def test_agente_limita_rondas_de_herramientas(monkeypatch):
    respuestas = [
        SimpleNamespace(
            stop_reason="tool_use",
            content=[
                SimpleNamespace(
                    type="tool_use", name="timeline", input={}, id=f"tool-{i}"
                )
            ],
        )
        for i in range(3)
    ]
    mensajes_api = MensajesFalsos(respuestas)
    monkeypatch.setattr(
        anthropic,
        "Anthropic",
        lambda: SimpleNamespace(messages=mensajes_api),
    )
    monkeypatch.setattr(agente, "CHAT_MAX_RONDAS_HERRAMIENTAS", 2)
    monkeypatch.setattr(agente, "ejecutar_herramienta", lambda *_args: [])

    with pytest.raises(RuntimeError, match="límite de rondas"):
        list(loop_agente_eventos([], modelo="claude-sonnet-5"))


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
