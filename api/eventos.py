"""Helpers puros de la API web (sin BD ni red) — testeables en aislamiento."""

import json
from collections import Counter


def sse(evento, datos):
    """Formatea un evento SSE: 'event: X\\ndata: {json}\\n\\n'."""
    return f"event: {evento}\ndata: {json.dumps(datos, ensure_ascii=False)}\n\n"


def extraer_nodo_ids(nombre, entrada, salida):
    """Ids de nodos citados por una herramienta del agente (evidencia visual).

    Todas las herramientas devuelven list[dict] con clave 'id'; ademas
    expandir_contexto/cadena_causal anclan un nodo via entrada['nodo_id'].
    listar_pacientes se ignora (no es evidencia de un paciente concreto).
    """
    if nombre == "listar_pacientes":
        return []
    ids = []
    if isinstance(salida, list):
        ids = [f["id"] for f in salida if isinstance(f, dict) and f.get("id")]
    if entrada.get("nodo_id"):
        ids.append(entrada["nodo_id"])
    return list(dict.fromkeys(ids))  # dedup preservando orden


def bins_mensuales(filas):
    """Agrega eventos puntuales por (mes 'YYYY-MM', tipo) -> [{mes, tipo, n}].

    `filas` son dicts {tipo, fecha} con fecha ISO (o None: se ignora).
    Salida ordenada por mes y tipo, lista para el carril de densidad de la UI.
    """
    conteo = Counter((f["fecha"][:7], f["tipo"]) for f in filas if f.get("fecha"))
    return [{"mes": mes, "tipo": tipo, "n": n}
            for (mes, tipo), n in sorted(conteo.items())]


def recortar_historial(mensajes, max_intercambios=10):
    """Poda el historial a los ultimos N intercambios completos.

    Un intercambio empieza en cada mensaje user cuyo content es texto (str);
    los mensajes user que llevan tool_results (list) pertenecen al intercambio
    en curso, asi que nunca se parte un par tool_use/tool_result.
    """
    inicios = [i for i, m in enumerate(mensajes)
               if m["role"] == "user" and isinstance(m["content"], str)]
    if len(inicios) <= max_intercambios:
        return mensajes
    return mensajes[inicios[-max_intercambios]:]
