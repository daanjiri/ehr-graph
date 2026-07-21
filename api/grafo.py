"""Endpoints REST del grafo — SOLO travesias fijas parametrizadas (regla de oro 7).

La vista inicial es el "nucleo clinico" del paciente (Paciente + Condiciones +
Prescripciones + Farmacos + aristas causales); Observaciones, Procedimientos y
Encuentros entran bajo demanda via /nodos/{id}/vecinos.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from agente import q, t_listar_pacientes, t_timeline
from api.eventos import bins_mensuales

router = APIRouter()

CAMPOS_NODO = ("id", "fhir_id", "tipo", "etiqueta", "fecha", "fecha_fin",
               "descripcion", "estado")


def nodo(fila):
    return {k: fila[k] for k in CAMPOS_NODO if fila.get(k) is not None}


# ---------------------------------------------------------------------------
# Pacientes
# ---------------------------------------------------------------------------

@router.get("/pacientes")
def pacientes():
    return t_listar_pacientes(limite=100)


@router.get("/pacientes/{pid}/timeline")
def timeline(pid: str, desde: str = None, hasta: str = None, limite: int = 30):
    return t_timeline(pid, desde=desde, hasta=hasta, limite=limite)


# ---------------------------------------------------------------------------
# Grafo inicial: nucleo clinico
# ---------------------------------------------------------------------------

Q_PACIENTE = """
MATCH (p:Paciente {id: $pid})
RETURN p.id AS id, 'Paciente' AS tipo, p.nombre AS etiqueta,
       p.fhir_id AS fhir_id,
       toString(p.fecha_nacimiento) AS fecha,
       'Paciente ' + p.nombre + ' (' + p.sexo + ')' AS descripcion
"""

Q_CONDICIONES = """
MATCH (c:Condicion {paciente_id: $pid})
RETURN c.id AS id, 'Condicion' AS tipo, c.nombre AS etiqueta,
       c.fhir_id AS fhir_id,
       toString(c.fecha_efectiva) AS fecha,
       toString(c.fecha_resolucion) AS fecha_fin,
       c.texto_descriptivo AS descripcion,
       c.estado_clinico AS estado
"""

Q_PRESCRIPCIONES = """
MATCH (rx:Prescripcion {paciente_id: $pid})
OPTIONAL MATCH (rx)-[rf:DE_FARMACO]->(f:Farmaco)
WHERE rf.principal = true
RETURN rx.id AS id, 'Prescripcion' AS tipo,
       rx.fhir_id AS fhir_id,
       coalesce(f.nombre_generico, 'Prescripcion') AS etiqueta,
       toString(rx.fecha_efectiva) AS fecha, rx.texto_descriptivo AS descripcion,
       rx.estado AS estado
"""

Q_FARMACOS = """
MATCH (:Prescripcion {paciente_id: $pid})-[rf:DE_FARMACO]->(f:Farmaco)
WHERE rf.principal = true
RETURN DISTINCT f.id AS id, 'Farmaco' AS tipo, f.nombre_generico AS etiqueta,
       'Farmaco: ' + f.nombre_generico AS descripcion
"""

Q_TRATA = """
MATCH (rx:Prescripcion {paciente_id: $pid})-[r:TRATA]->(c:Condicion)
RETURN DISTINCT rx.id AS origen, c.id AS destino, 'TRATA' AS tipo
"""

Q_DE_FARMACO = """
MATCH (rx:Prescripcion {paciente_id: $pid})-[r:DE_FARMACO]->(f:Farmaco)
WHERE r.principal = true
RETURN rx.id AS origen, f.id AS destino, 'DE_FARMACO' AS tipo
"""

Q_INTERACCIONES = """
MATCH (rx1:Prescripcion {paciente_id: $pid})-[r1:DE_FARMACO]->(f1:Farmaco)
      -[i:INTERACTUA_CON]->(f2:Farmaco)<-[r2:DE_FARMACO]-(rx2:Prescripcion {paciente_id: $pid})
WHERE r1.principal = true AND r2.principal = true
RETURN DISTINCT f1.id AS origen, f2.id AS destino, 'INTERACTUA_CON' AS tipo,
       i.severidad AS severidad
"""


@router.get("/pacientes/{pid}/grafo")
def grafo_paciente(pid: str):
    fila_paciente = q(Q_PACIENTE, pid=pid)
    if not fila_paciente:
        raise HTTPException(404, "Paciente no encontrado")
    condiciones = q(Q_CONDICIONES, pid=pid)
    prescripciones = q(Q_PRESCRIPCIONES, pid=pid)
    nodos = [nodo(f) for f in fila_paciente + condiciones + prescripciones
             + q(Q_FARMACOS, pid=pid)]
    aristas = q(Q_TRATA, pid=pid) + q(Q_DE_FARMACO, pid=pid) + q(Q_INTERACCIONES, pid=pid)
    # Estructura radial: Condiciones cuelgan del Paciente; Prescripciones solo si
    # no tienen TRATA (si tratan una condicion, cuelgan de ella y no del hub).
    rx_con_trata = {a["origen"] for a in aristas if a["tipo"] == "TRATA"}
    aristas += [{"origen": c["id"], "destino": pid, "tipo": "DE_PACIENTE"}
                for c in condiciones]
    aristas += [{"origen": rx["id"], "destino": pid, "tipo": "DE_PACIENTE"}
                for rx in prescripciones if rx["id"] not in rx_con_trata]
    return {"nodos": nodos, "aristas": aristas}


# ---------------------------------------------------------------------------
# Intervalos temporales (vista de linea de tiempo)
# ---------------------------------------------------------------------------

Q_INT_CONDICIONES = """
MATCH (c:Condicion {paciente_id: $pid})
RETURN c.id AS id, c.nombre AS nombre,
       toString(coalesce(c.fecha_inicio, c.fecha_efectiva)) AS fecha_inicio,
       toString(c.fecha_resolucion) AS fecha_resolucion,
       c.estado_clinico AS estado
ORDER BY coalesce(c.fecha_inicio, c.fecha_efectiva)
"""

Q_INT_PRESCRIPCIONES = """
MATCH (rx:Prescripcion {paciente_id: $pid})
OPTIONAL MATCH (rx)-[rf:DE_FARMACO]->(f:Farmaco)
WHERE rf.principal = true
RETURN rx.id AS id,
       coalesce(f.nombre_generico, left(rx.texto_descriptivo, 60)) AS farmaco,
       toString(coalesce(rx.fecha_inicio, rx.fecha_efectiva)) AS fecha_inicio,
       rx.estado AS estado
ORDER BY coalesce(rx.fecha_inicio, rx.fecha_efectiva)
"""

Q_INT_ENCUENTROS = """
MATCH (e:Encuentro {paciente_id: $pid})
RETURN e.id AS id, toString(e.fecha_inicio) AS fecha_inicio,
       toString(e.fecha_fin) AS fecha_fin, e.tipo AS tipo,
       e.motivo_consulta AS motivo
ORDER BY e.fecha_inicio
"""

# Filas crudas; el binning mensual se hace en Python (helper puro testeable).
Q_INT_PUNTUALES = """
MATCH (e:Evento {paciente_id: $pid})
WHERE (e:Observacion OR e:Procedimiento OR e:Inmunizacion OR e:Alergia)
  AND e.fecha_efectiva IS NOT NULL
RETURN [l IN labels(e) WHERE l <> 'Evento'][0] AS tipo,
       toString(e.fecha_efectiva) AS fecha
"""


@router.get("/pacientes/{pid}/intervalos")
def intervalos(pid: str):
    """Datos de la timeline: barras (condiciones/prescripciones), encuentros
    y densidad mensual de eventos puntuales. Nota: Synthea no exporta fin de
    prescripcion (limitacion #5) -> completed se representa puntual en la UI."""
    if not q(Q_PACIENTE, pid=pid):
        raise HTTPException(404, "Paciente no encontrado")
    return {
        "condiciones": q(Q_INT_CONDICIONES, pid=pid),
        "prescripciones": q(Q_INT_PRESCRIPCIONES, pid=pid),
        "encuentros": q(Q_INT_ENCUENTROS, pid=pid),
        "bins": bins_mensuales(q(Q_INT_PUNTUALES, pid=pid)),
    }


# ---------------------------------------------------------------------------
# Expansion de vecinos (click en un nodo)
# ---------------------------------------------------------------------------

_CAMPOS_VECINO = """
       coalesce(m.nombre, m.nombre_generico, left(m.texto_descriptivo, 60), m.id) AS etiqueta,
       toString(m.fecha_efectiva) AS fecha,
       toString(coalesce(m.fecha_resolucion, m.fecha_fin)) AS fecha_fin,
       coalesce(m.texto_descriptivo, m.nombre, m.nombre_generico) AS descripcion,
       coalesce(m.estado, m.estado_clinico) AS estado,
       m.fhir_id AS fhir_id,
       type(r) AS rel, startNode(r) = n AS saliente
"""

Q_VECINOS_EVENTO = f"""
MATCH (n:Evento {{id: $id}})-[r]-(m)
WHERE m.paciente_id = $pid OR (m.paciente_id IS NULL AND NOT m:Paciente)
   OR (m:Paciente AND m.id = $pid)
RETURN m.id AS id,
       coalesce([l IN labels(m) WHERE l <> 'Evento'][0], labels(m)[0]) AS tipo,
       {_CAMPOS_VECINO}
ORDER BY coalesce(toString(m.fecha_efectiva), '0000') DESC
LIMIT 40
"""

# Expandir el Paciente trae sus Encuentros (hubs temporales), no los 586 eventos.
Q_VECINOS_PACIENTE = """
MATCH (n:Paciente {id: $id})<-[r:DE_PACIENTE]-(m:Encuentro)
RETURN m.id AS id, 'Encuentro' AS tipo,
       m.fhir_id AS fhir_id,
       left(m.texto_descriptivo, 60) AS etiqueta,
       toString(m.fecha_efectiva) AS fecha,
       toString(m.fecha_fin) AS fecha_fin, m.texto_descriptivo AS descripcion,
       m.tipo AS estado, type(r) AS rel, false AS saliente
ORDER BY m.fecha_efectiva DESC
LIMIT 40
"""

Q_VECINOS_CONCEPTO = f"""
MATCH (n {{id: $id}})-[r]-(m)
WHERE m.paciente_id = $pid OR (m.paciente_id IS NULL AND NOT m:Paciente)
RETURN m.id AS id,
       coalesce([l IN labels(m) WHERE l <> 'Evento'][0], labels(m)[0]) AS tipo,
       {_CAMPOS_VECINO}
ORDER BY coalesce(toString(m.fecha_efectiva), '0000') DESC
LIMIT 40
"""


def _filas_a_grafo(nodo_id, filas):
    """Convierte filas vecino en {nodos, aristas} orientando cada arista."""
    nodos, aristas, vistos = [], [], set()
    for f in filas:
        if f["id"] not in vistos:
            vistos.add(f["id"])
            nodos.append(nodo(f))
        origen, destino = ((nodo_id, f["id"]) if f["saliente"]
                           else (f["id"], nodo_id))
        arista = {"origen": origen, "destino": destino, "tipo": f["rel"]}
        if arista not in aristas:
            aristas.append(arista)
    return {"nodos": nodos, "aristas": aristas}


@router.get("/nodos/{nodo_id}/vecinos")
def vecinos(nodo_id: str, pid: str):
    filas = q(Q_VECINOS_EVENTO, id=nodo_id, pid=pid)
    if not filas:
        filas = q(Q_VECINOS_PACIENTE, id=nodo_id)
    if not filas:
        filas = q(Q_VECINOS_CONCEPTO, id=nodo_id, pid=pid)
    return _filas_a_grafo(nodo_id, filas)


# ---------------------------------------------------------------------------
# Lote: materializar nodos de evidencia citados por el chat
# ---------------------------------------------------------------------------

Q_LOTE_EVENTOS = """
MATCH (n:Evento) WHERE n.id IN $ids AND n.paciente_id = $pid
RETURN n.id AS id, [l IN labels(n) WHERE l <> 'Evento'][0] AS tipo,
       n.fhir_id AS fhir_id,
       coalesce(n.nombre, n.nombre_generico, left(n.texto_descriptivo, 60), n.id) AS etiqueta,
       toString(n.fecha_efectiva) AS fecha,
       toString(coalesce(n.fecha_resolucion, n.fecha_fin)) AS fecha_fin,
       n.texto_descriptivo AS descripcion,
       coalesce(n.estado, n.estado_clinico) AS estado
"""

Q_LOTE_CONCEPTOS = """
MATCH (n) WHERE n.id IN $ids AND n.paciente_id IS NULL AND NOT n:Paciente
RETURN n.id AS id, labels(n)[0] AS tipo,
       coalesce(n.nombre, n.nombre_generico) AS etiqueta,
       coalesce(n.nombre, n.nombre_generico) AS descripcion
"""

Q_LOTE_ARISTAS = """
MATCH (a)-[r]->(b)
WHERE a.id IN $ids AND b.id IN $ids
RETURN DISTINCT a.id AS origen, b.id AS destino, type(r) AS tipo
"""


class PeticionLote(BaseModel):
    ids: list[str]
    pid: str


@router.post("/nodos/lote")
def lote(peticion: PeticionLote):
    if not peticion.ids:
        return {"nodos": [], "aristas": []}
    eventos = q(Q_LOTE_EVENTOS, ids=peticion.ids, pid=peticion.pid)
    conceptos = q(Q_LOTE_CONCEPTOS, ids=peticion.ids)
    aristas = q(Q_LOTE_ARISTAS, ids=peticion.ids)
    # Todo evento del lote queda conectado al hub del paciente (la UI dedupe).
    aristas += [{"origen": f["id"], "destino": peticion.pid, "tipo": "DE_PACIENTE"}
                for f in eventos]
    return {"nodos": [nodo(f) for f in eventos + conceptos], "aristas": aristas}
