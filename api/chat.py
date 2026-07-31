"""Chat SSE contra el agente GraphRAG, con sesiones in-memory.

Las sesiones guardan los content blocks del SDK anthropic tal cual (objetos
Pydantic, nunca pasan por JSON) -> requiere 1 solo worker de uvicorn.
"""

import logging
import os
import uuid

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

import agente
from api.limites import direccion_cliente, hash_cliente, reservar
from api.eventos import extraer_nodo_ids, recortar_historial, sse
from config import (
    ANTHROPIC_MODEL,
    CHAT_LIMITE_DIARIO_CLIENTE,
    CHAT_LIMITE_MENSUAL_GLOBAL,
    CHAT_MAX_CHARS,
    CHAT_MAX_INTERCAMBIOS,
    MODELOS_ANTHROPIC,
    MODELOS_ANTHROPIC_POR_ID,
)

router = APIRouter()
logger = logging.getLogger(__name__)

SESIONES = {}  # sesion_id -> {"paciente_id": str, "mensajes": list}


class PeticionChat(BaseModel):
    paciente_id: str
    mensaje: str = Field(min_length=1, max_length=CHAT_MAX_CHARS)
    sesion_id: str | None = None
    modelo: str | None = None


@router.get("/modelos")
def modelos():
    return {
        "predeterminado": ANTHROPIC_MODEL,
        "modelos": [
            {clave: valor for clave, valor in modelo.items()
             if clave != "admite_esfuerzo"}
            for modelo in MODELOS_ANTHROPIC
        ],
    }


def resolver_modelo(modelo: str | None) -> str:
    seleccionado = modelo or ANTHROPIC_MODEL
    if seleccionado not in MODELOS_ANTHROPIC_POR_ID:
        raise HTTPException(422, "Modelo no permitido")
    return seleccionado


def _sesion(peticion):
    """Recupera o crea la sesion; cambiar de paciente crea sesion nueva."""
    s = SESIONES.get(peticion.sesion_id)
    if s and s["paciente_id"] == peticion.paciente_id:
        return peticion.sesion_id, s
    sesion_id = str(uuid.uuid4())
    SESIONES[sesion_id] = {
        "paciente_id": peticion.paciente_id,
        "mensajes": [],
        "modelo": None,
    }
    return sesion_id, SESIONES[sesion_id]


@router.post("/chat")
def chat(peticion: PeticionChat, request: Request):
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(503, "La demo de chat no está configurada")

    modelo = resolver_modelo(peticion.modelo)

    mensaje = peticion.mensaje.strip()
    if not mensaje:
        raise HTTPException(422, "El mensaje no puede estar vacío")

    filas = agente.q("MATCH (p:Paciente {id: $pid}) RETURN p.nombre AS nombre",
                     pid=peticion.paciente_id)
    if not filas:
        raise HTTPException(404, "Paciente no encontrado")
    nombre = filas[0]["nombre"]

    try:
        cuota = reservar(
            agente.driver(),
            hash_cliente(direccion_cliente(request)),
        )
    except Exception as exc:
        logger.exception("No se pudo reservar la cuota de chat")
        raise HTTPException(503, "No se pudo validar la cuota de la demo") from exc
    if not cuota["permitido"]:
        if cuota["global_count"] >= CHAT_LIMITE_MENSUAL_GLOBAL:
            detalle = "La demo alcanzó su cupo mensual. Inténtalo el próximo mes."
        else:
            detalle = (
                f"Alcanzaste el límite de {CHAT_LIMITE_DIARIO_CLIENTE} "
                "mensajes diarios para esta demo."
            )
        raise HTTPException(429, detalle)

    sesion_id, sesion = _sesion(peticion)
    if sesion["modelo"] and sesion["modelo"] != modelo:
        agente.limpiar_pensamiento_otro_modelo(sesion["mensajes"])
    sesion["modelo"] = modelo
    sesion["mensajes"] = recortar_historial(
        sesion["mensajes"], CHAT_MAX_INTERCAMBIOS)
    mensajes = sesion["mensajes"]
    mensajes.append({"role": "user", "content": mensaje})

    extra = (f"El usuario esta viendo el grafo del paciente {nombre} "
             f"(id: {peticion.paciente_id}). Usa ese paciente_id en las "
             f"herramientas salvo que el usuario pida explicitamente otro paciente.")

    def generar():
        yield sse("inicio", {"sesion_id": sesion_id, "modelo": modelo})
        nodo_ids_turno = []
        try:
            eventos = agente.loop_agente_eventos(
                mensajes,
                system_extra=extra,
                paciente_id=peticion.paciente_id,
                modelo=modelo,
            )
            for ev in eventos:
                if ev["tipo"] == "texto":
                    yield sse("texto", {"delta": ev["delta"]})
                elif ev["tipo"] == "tool_call":
                    yield sse("tool_call", {"nombre": ev["nombre"],
                                            "entrada": ev["entrada"]})
                elif ev["tipo"] == "tool_result":
                    ids = extraer_nodo_ids(ev["nombre"], ev["entrada"], ev["salida"])
                    nodo_ids_turno += [i for i in ids if i not in nodo_ids_turno]
                    datos = {"nombre": ev["nombre"],
                             "n_resultados": len(ev["salida"]), "nodo_ids": ids}
                    if ev.get("error"):
                        datos["error"] = ev["error"]
                    yield sse("tool_result", datos)
                elif ev["tipo"] == "fin":
                    yield sse("fin", {"nodo_ids": nodo_ids_turno})
        except Exception:  # el stream no puede devolver un 500: evento error
            logger.exception("Error durante el stream del agente")
            yield sse("error", {
                "mensaje": "No pudimos completar la respuesta. Inténtalo nuevamente."
            })

    return StreamingResponse(generar(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})
