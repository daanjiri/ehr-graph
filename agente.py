"""agente.py — Agente GraphRAG con patrón pinza (PLAN.md §10).

Herramientas de travesía FIJA expuestas al LLM vía tool use — NO text-to-Cypher
libre (seguridad en contexto clínico). Sin ANTHROPIC_API_KEY corre en modo demo.

Uso:
  uv run python agente.py                        # demo (sin key) o chat (con key)
  uv run python agente.py "¿qué toma X y para qué?"   # pregunta única (con key)
"""

import json
import os
import sys

import neo4j.time
from neo4j import GraphDatabase

from config import ANTHROPIC_MAX_TOKENS, ANTHROPIC_MODEL, NEO4J_AUTH, NEO4J_URI
from semantica import buscar_semantico

MODELO_LLM = ANTHROPIC_MODEL

ARISTAS_CAUSALES = "TRATA|INDICADO_POR|EVIDENCIA_DE|COMPLICACION_DE|MOTIVO_SUSPENSION_DE|REEMPLAZA_A|MONITOREA"

_driver = None


def driver():
    global _driver
    if _driver is None:
        _driver = GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)
    return _driver


def a_json(valor):
    """neo4j.time.DateTime/Date no son JSON-serializables -> ISO string."""
    if isinstance(valor, (neo4j.time.DateTime, neo4j.time.Date)):
        return valor.iso_format()
    if isinstance(valor, dict):
        return {k: a_json(v) for k, v in valor.items()}
    if isinstance(valor, list):
        return [a_json(v) for v in valor]
    return valor


def q(cypher, **params):
    with driver().session() as s:
        return [a_json(r.data()) for r in s.run(cypher, **params)]


# ---------------------------------------------------------------------------
# Herramientas de travesía fija
# ---------------------------------------------------------------------------

def t_listar_pacientes(limite=10, paciente_id=None):
    filtro = "WHERE p.id = $pid" if paciente_id else ""
    return q(f"""
        MATCH (p:Paciente)
        {filtro}
        RETURN p.id AS id, p.fhir_id AS fhir_id, p.nombre AS nombre, p.sexo AS sexo,
               toString(p.fecha_nacimiento) AS fecha_nacimiento, p.fallecido AS fallecido
        ORDER BY p.nombre LIMIT $limite
    """, pid=paciente_id, limite=int(limite))


def t_timeline(paciente_id, desde=None, hasta=None, limite=30):
    """Cronología vía el índice compuesto (paciente_id, fecha_efectiva)."""
    filtros = ["e.paciente_id = $pid", "e.fecha_efectiva IS NOT NULL"]
    if desde:
        filtros.append("e.fecha_efectiva >= datetime($desde)")
    if hasta:
        filtros.append("e.fecha_efectiva <= datetime($hasta)")
    return q(f"""
        MATCH (e:Evento)
        WHERE {' AND '.join(filtros)}
        RETURN e.id AS id, [l IN labels(e) WHERE l <> 'Evento'][0] AS tipo,
               toString(e.fecha_efectiva) AS fecha, e.texto_descriptivo AS descripcion
        ORDER BY e.fecha_efectiva
        LIMIT $limite
    """, pid=paciente_id, desde=desde, hasta=hasta, limite=int(limite))


def t_buscar_semantico(pregunta, paciente_id=None, k=5):
    return a_json(buscar_semantico(pregunta, k=int(k), paciente_id=paciente_id,
                                   driver=driver()))


def t_expandir_contexto(nodo_id, saltos=1, paciente_id=None):
    saltos = max(1, min(int(saltos), 3))
    filas = q(f"""
        MATCH (n:Evento {{id: $id}})
        WHERE $pid IS NULL OR n.paciente_id = $pid
        MATCH camino = (n)-[*1..{saltos}]-(m)
        WHERE $pid IS NULL OR m.paciente_id = $pid OR NOT m:Evento
        WITH DISTINCT m, [r IN relationships(camino) | type(r)] AS relaciones
        RETURN [l IN labels(m) WHERE l <> 'Evento'][0] AS tipo, relaciones,
               coalesce(m.texto_descriptivo, m.nombre, m.nombre_generico, m.id) AS descripcion,
               m.id AS id
        LIMIT 40
    """, id=nodo_id, pid=paciente_id)
    if not filas:  # el id puede ser de un Paciente
        filas = q("""
            MATCH (p:Paciente {id: $id})<-[:DE_PACIENTE]-(e:Evento)
            WHERE $pid IS NULL OR p.id = $pid
            RETURN [l IN labels(e) WHERE l <> 'Evento'][0] AS tipo,
                   ['DE_PACIENTE'] AS relaciones, e.texto_descriptivo AS descripcion,
                   e.id AS id
            ORDER BY e.fecha_efectiva DESC LIMIT 40
        """, id=nodo_id, pid=paciente_id)
    return filas


def t_cadena_causal(nodo_id, paciente_id=None):
    """Causas y efectos vía aristas causales, 1..3 saltos."""
    return q(f"""
        MATCH camino = (n:Evento {{id: $id}})-[:{ARISTAS_CAUSALES}*1..3]-(m)
        WHERE ($pid IS NULL OR n.paciente_id = $pid)
          AND ($pid IS NULL OR m.paciente_id = $pid)
        WITH DISTINCT m, camino
        RETURN [l IN labels(m) WHERE l <> 'Evento'][0] AS tipo,
               [r IN relationships(camino) | type(r) + ' (' + r.fuente + ', ' +
                toString(r.confianza) + ')'] AS cadena,
               m.texto_descriptivo AS descripcion, m.id AS id
        LIMIT 25
    """, id=nodo_id, pid=paciente_id)


def t_medicacion_activa(paciente_id):
    """Rx vigentes + qué condición trata cada una.

    Nota: Synthea no exporta fecha de fin — el criterio primario de vigencia
    es estado='active'; las fechas son informativas.
    """
    return q("""
        MATCH (rx:Prescripcion {paciente_id: $pid})
        WHERE rx.estado = 'active'
        OPTIONAL MATCH (rx)-[rf:DE_FARMACO]->(f:Farmaco)
        WHERE rf.principal = true
        OPTIONAL MATCH (rx)-[:TRATA]->(c:Condicion)
        RETURN rx.id AS id, f.nombre_generico AS farmaco,
               toString(rx.fecha_inicio) AS desde, rx.dosis_texto AS dosis,
               [x IN collect(c.nombre) WHERE x IS NOT NULL] AS trata
        ORDER BY desde
    """, pid=paciente_id)


HERRAMIENTAS = {
    "buscar_semantico": t_buscar_semantico,
    "timeline": t_timeline,
    "expandir_contexto": t_expandir_contexto,
    "cadena_causal": t_cadena_causal,
    "medicacion_activa": t_medicacion_activa,
    "listar_pacientes": t_listar_pacientes,
}

TOOLS = [
    {
        "name": "buscar_semantico",
        "description": "Busqueda difusa por similitud semantica sobre los eventos clinicos "
                       "del grafo. Usala para ANCLAR: encontrar nodos relevantes a la "
                       "pregunta aunque use otras palabras. Los textos del grafo estan "
                       "mayormente en ingles: busca con el termino clinico en ingles o el "
                       "cognado espanol (p.ej. 'colonoscopy'/'colonoscopia', no 'examen "
                       "del colon'); si no hay resultados, reformula y reintenta.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pregunta": {"type": "string", "description": "Texto a buscar"},
                "paciente_id": {"type": "string", "description": "Limitar a un paciente (opcional)"},
                "k": {"type": "integer", "description": "Resultados (default 5)"},
            },
            "required": ["pregunta"],
        },
    },
    {
        "name": "timeline",
        "description": "Cronologia de eventos clinicos de un paciente ordenada por fecha. "
                       "Rapida (usa indice compuesto). Filtros de fecha opcionales ISO.",
        "input_schema": {
            "type": "object",
            "properties": {
                "paciente_id": {"type": "string"},
                "desde": {"type": "string", "description": "ISO datetime (opcional)"},
                "hasta": {"type": "string", "description": "ISO datetime (opcional)"},
                "limite": {"type": "integer", "description": "default 30"},
            },
            "required": ["paciente_id"],
        },
    },
    {
        "name": "expandir_contexto",
        "description": "Vecinos de un nodo con el tipo de relacion (1 a 3 saltos). "
                       "Usala para TRAER CONTEXTO alrededor de un nodo anclado.",
        "input_schema": {
            "type": "object",
            "properties": {
                "nodo_id": {"type": "string"},
                "saltos": {"type": "integer", "description": "1-3, default 1"},
            },
            "required": ["nodo_id"],
        },
    },
    {
        "name": "cadena_causal",
        "description": "Causas y efectos de un evento via aristas causales "
                       "(TRATA, INDICADO_POR...), 1 a 3 saltos, con fuente y confianza.",
        "input_schema": {
            "type": "object",
            "properties": {"nodo_id": {"type": "string"}},
            "required": ["nodo_id"],
        },
    },
    {
        "name": "medicacion_activa",
        "description": "Prescripciones vigentes de un paciente y que condicion trata cada una.",
        "input_schema": {
            "type": "object",
            "properties": {"paciente_id": {"type": "string"}},
            "required": ["paciente_id"],
        },
    },
    {
        "name": "listar_pacientes",
        "description": "Ids y nombres de los pacientes disponibles en el grafo.",
        "input_schema": {
            "type": "object",
            "properties": {"limite": {"type": "integer", "description": "default 10"}},
        },
    },
]

SYSTEM = """Eres un asistente clinico que responde SOLO con datos del knowledge graph.

Estrategia (patron pinza): 1) ANCLA con buscar_semantico o listar_pacientes;
2) EXPANDE con timeline, expandir_contexto, cadena_causal o medicacion_activa;
3) SINTETIZA citando fechas y valores EXACTOS del grafo (con el id del nodo
cuando aporte trazabilidad).

Reglas estrictas:
- Nunca inventes datos clinicos. Si el grafo no contiene la respuesta, dilo
  explicitamente ("no esta en el grafo").
- Cita fechas y valores tal cual estan en el grafo.
- Responde en espanol aunque los datos vengan en ingles.
- Aclara cuando sea relevante que son datos sinteticos (Synthea), no reales.
"""


def ejecutar_herramienta(nombre, entrada):
    print(f"  [tool] {nombre}({json.dumps(entrada, ensure_ascii=False)})", file=sys.stderr)
    return HERRAMIENTAS[nombre](**entrada)


# En la UI el paciente lo fija el servidor, nunca el modelo. Todas las
# herramientas reciben ese scope aunque el campo no aparezca en su schema.
HERRAMIENTAS_PACIENTE = set(HERRAMIENTAS)


def acotar_entrada(nombre, entrada, paciente_id=None):
    """Impone el paciente de la sesión sobre cualquier valor propuesto por el LLM."""
    entrada = dict(entrada)
    if paciente_id and nombre in HERRAMIENTAS_PACIENTE:
        entrada["paciente_id"] = paciente_id
    return entrada


def loop_agente_eventos(mensajes, system_extra=None, paciente_id=None):
    """Loop tool-use manual como generador: muta `mensajes` in place y emite eventos.

    Eventos: {"tipo": "texto", "delta": str}                       texto en streaming
             {"tipo": "tool_call", "nombre", "entrada"}            antes de ejecutar
             {"tipo": "tool_result", "nombre", "entrada", "salida" [, "error"]}
             {"tipo": "fin", "texto": str}                         texto del mensaje final
    """
    import anthropic
    client = anthropic.Anthropic()
    system = SYSTEM if not system_extra else SYSTEM + "\n" + system_extra
    while True:
        with client.messages.stream(
            model=MODELO_LLM, max_tokens=ANTHROPIC_MAX_TOKENS, system=system,
            tools=TOOLS, messages=mensajes,
        ) as stream:
            for delta in stream.text_stream:
                yield {"tipo": "texto", "delta": delta}
            respuesta = stream.get_final_message()
        if respuesta.stop_reason != "tool_use":
            yield {"tipo": "fin", "texto": "".join(
                b.text for b in respuesta.content if b.type == "text")}
            return
        # Append del contenido COMPLETO del assistant, luego TODOS los tool_result
        # del turno en UN solo mensaje user (puede haber tool calls en paralelo).
        mensajes.append({"role": "assistant", "content": respuesta.content})
        resultados = []
        for bloque in respuesta.content:
            if bloque.type != "tool_use":
                continue
            entrada = acotar_entrada(bloque.name, bloque.input, paciente_id)
            yield {"tipo": "tool_call", "nombre": bloque.name, "entrada": entrada}
            try:
                salida = ejecutar_herramienta(bloque.name, entrada)
                resultados.append({"type": "tool_result", "tool_use_id": bloque.id,
                                   "content": json.dumps(salida, ensure_ascii=False)})
                yield {"tipo": "tool_result", "nombre": bloque.name,
                       "entrada": entrada, "salida": salida}
            except Exception as e:
                resultados.append({"type": "tool_result", "tool_use_id": bloque.id,
                                   "content": f"Error ejecutando {bloque.name}: {e}",
                                   "is_error": True})
                yield {"tipo": "tool_result", "nombre": bloque.name,
                       "entrada": entrada, "salida": [], "error": str(e)}
        mensajes.append({"role": "user", "content": resultados})


def loop_agente(pregunta):
    """CLI: una pregunta sin historial; devuelve solo el texto final."""
    mensajes = [{"role": "user", "content": pregunta}]
    for evento in loop_agente_eventos(mensajes):
        if evento["tipo"] == "fin":
            return evento["texto"]
    return ""


def modo_demo():
    """Sin API key: demostracion determinista de las herramientas."""
    print("=== MODO DEMO (sin ANTHROPIC_API_KEY) — datos sinteticos Synthea ===\n")
    pacientes = t_listar_pacientes(5)
    print("Pacientes disponibles:")
    for p in pacientes:
        print(f"  {p['id'][:8]}...  {p['nombre']}  ({p['sexo']}, nac. {p['fecha_nacimiento']})")
    if not pacientes:
        print("  (grafo vacio — corre primero ingest.py)")
        return
    primero = pacientes[0]
    print(f"\nTimeline de {primero['nombre']} (primeros 15 eventos):")
    for e in t_timeline(primero["id"], limite=15):
        print(f"  {e['fecha'][:10]}  [{e['tipo']}] {e['descripcion']}")
    print(f"\nMedicacion activa de {primero['nombre']}:")
    activa = t_medicacion_activa(primero["id"])
    if not activa:
        print("  (sin prescripciones activas)")
    for rx in activa:
        trata = f" — trata: {', '.join(rx['trata'])}" if rx["trata"] else ""
        print(f"  {rx['farmaco']}  desde {str(rx['desde'])[:10]}{trata}")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        modo_demo()
        return
    if len(sys.argv) > 1:
        print(loop_agente(" ".join(sys.argv[1:])))
        return
    print("Agente GraphRAG (datos sinteticos). Escribe tu pregunta (vacio para salir).")
    while True:
        try:
            pregunta = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not pregunta:
            break
        print(loop_agente(pregunta))


if __name__ == "__main__":
    main()
