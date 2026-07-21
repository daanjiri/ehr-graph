"""Chat SSE contra el agente GraphRAG, con sesiones in-memory.

Las sesiones guardan los content blocks del SDK anthropic tal cual (objetos
Pydantic, nunca pasan por JSON) -> requiere 1 solo worker de uvicorn.
"""

import uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import agente
from api.eventos import extraer_nodo_ids, recortar_historial, sse

router = APIRouter()

SESIONES = {}  # sesion_id -> {"paciente_id": str, "mensajes": list}
MAX_INTERCAMBIOS = 10


class PeticionChat(BaseModel):
    paciente_id: str
    mensaje: str
    sesion_id: str | None = None


def _sesion(peticion):
    """Recupera o crea la sesion; cambiar de paciente crea sesion nueva."""
    s = SESIONES.get(peticion.sesion_id)
    if s and s["paciente_id"] == peticion.paciente_id:
        return peticion.sesion_id, s
    sesion_id = str(uuid.uuid4())
    SESIONES[sesion_id] = {"paciente_id": peticion.paciente_id, "mensajes": []}
    return sesion_id, SESIONES[sesion_id]


@router.post("/chat")
def chat(peticion: PeticionChat):
    filas = agente.q("MATCH (p:Paciente {id: $pid}) RETURN p.nombre AS nombre",
                     pid=peticion.paciente_id)
    if not filas:
        raise HTTPException(404, "Paciente no encontrado")
    nombre = filas[0]["nombre"]

    sesion_id, sesion = _sesion(peticion)
    sesion["mensajes"] = recortar_historial(sesion["mensajes"], MAX_INTERCAMBIOS)
    mensajes = sesion["mensajes"]
    mensajes.append({"role": "user", "content": peticion.mensaje})

    extra = (f"El usuario esta viendo el grafo del paciente {nombre} "
             f"(id: {peticion.paciente_id}). Usa ese paciente_id en las "
             f"herramientas salvo que el usuario pida explicitamente otro paciente.")

    def generar():
        yield sse("inicio", {"sesion_id": sesion_id})
        nodo_ids_turno = []
        try:
            eventos = agente.loop_agente_eventos(
                mensajes, system_extra=extra, paciente_id=peticion.paciente_id)
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
        except Exception as e:  # el stream no puede devolver un 500: evento error
            yield sse("error", {"mensaje": str(e)})

    return StreamingResponse(generar(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})
