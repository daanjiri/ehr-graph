"""Bundles FHIR R4 -> grafo Neo4j clínico.

La ingesta usa dos pasadas globales: primero crea todos los recursos y conceptos;
después crea referencias. Esto permite resolver referencias hacia recursos que
aparecen más tarde o en otro bundle del mismo conjunto de datos.

Uso:
    python ingest.py <directorio-fhir> [--source synthea]
"""

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

from neo4j import GraphDatabase

NEO4J_URI = "bolt://localhost:7687"
NEO4J_AUTH = ("neo4j", "password123")
EXCLUIR_PREFIJOS = ("hospitalInformation", "practitionerInformation")
SISTEMA_DESCONOCIDO = "urn:ietf:rfc:3986"
BATCH = 1000


# ---------------------------------------------------------------------------
# Utilidades puras
# ---------------------------------------------------------------------------

def norm_dt(valor):
    """Normaliza una fecha/hora FHIR a datetime UTC; entradas inválidas -> None."""
    if not valor:
        return None
    try:
        resultado = datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if resultado.tzinfo is None:
        resultado = resultado.replace(tzinfo=timezone.utc)
    return resultado.astimezone(timezone.utc)


def norm_date(valor):
    if not valor:
        return None
    try:
        return date.fromisoformat(str(valor)[:10])
    except (TypeError, ValueError):
        return None


def ref_id(ref):
    """Compatibilidad: extrae el logical id de una referencia FHIR simple."""
    valor = ref.get("reference") if isinstance(ref, dict) else ref
    if not valor or "?" in valor:
        return None
    if valor.startswith("urn:uuid:"):
        return valor[len("urn:uuid:"):]
    if "/" in valor:
        partes = [p for p in valor.rstrip("/").split("/") if p]
        if len(partes) >= 2 and partes[-2] == "_history" and len(partes) >= 4:
            return partes[-3]
        return partes[-1]
    return valor.lstrip("#") or None


def resource_key(fuente, resource_type, logical_id, parent_key=None):
    if not resource_type or not logical_id:
        return None
    if parent_key:
        return f"{parent_key}#{resource_type}/{logical_id}"
    return f"{fuente}|{resource_type}/{logical_id}"


def _sistema(valor):
    return valor or SISTEMA_DESCONOCIDO


def codings(cc, sistema_preferido=None):
    """Devuelve todos los Coding válidos, deduplicados por (system, code)."""
    if not cc:
        return []
    encontrados = []
    vistos = set()
    for item in cc.get("coding") or []:
        codigo = item.get("code")
        if not codigo:
            continue
        sistema = _sistema(item.get("system"))
        identidad = (sistema, str(codigo))
        if identidad in vistos:
            continue
        vistos.add(identidad)
        encontrados.append({
            "codigo": str(codigo),
            "nombre": item.get("display") or cc.get("text") or str(codigo),
            "sistema": sistema,
            "version": item.get("version"),
            "user_selected": item.get("userSelected"),
        })
    if not encontrados:
        return []
    indice = 0
    if sistema_preferido:
        indice = next((i for i, c in enumerate(encontrados)
                       if sistema_preferido.lower() in c["sistema"].lower()), 0)
    for i, item in enumerate(encontrados):
        item["principal"] = i == indice
    return encontrados


def coding(cc, sistema_preferido=None):
    todos = codings(cc, sistema_preferido)
    if not todos:
        return None
    principal = next((c for c in todos if c["principal"]), todos[0])
    return {k: principal[k] for k in ("codigo", "nombre", "sistema")}


def code_only(cc):
    principal = coding(cc)
    return principal["codigo"] if principal else None


def fmt_fecha(valor):
    return valor.date().isoformat() if valor else "fecha desconocida"


PLANTILLAS = {
    "Encuentro": "Encuentro clinico ({tipo}) el {fecha}.",
    "Condicion": "Diagnostico: {nombre} ({estado}), inicio {fecha}.",
    "Prescripcion": "Prescripcion de {farmaco} ({estado}), iniciada {fecha}. {dosis_texto}",
    "Procedimiento": "Procedimiento: {nombre} realizado el {fecha}.",
    "Observacion": "Lab/medicion: {nombre} = {valor} {unidad} el {fecha}.",
    "Alergia": "Alergia/intolerancia: {nombre} ({criticidad}).",
    "Inmunizacion": "Vacuna: {nombre} el {fecha}.",
}


def build_texto(plantilla, **campos):
    campos = {k: "" if v is None else v for k, v in campos.items()}
    return " ".join(PLANTILLAS[plantilla].format(**campos).split())


CLASE_ENCUENTRO = {
    "AMB": "ambulatorio", "EMER": "urgencias", "IMP": "hospitalizacion",
    "ACUTE": "hospitalizacion", "NONAC": "hospitalizacion", "WELLNESS": "control",
    "URGENTCARE": "atencion urgente", "OBSENC": "observacion",
    "PRENC": "preadmision", "SS": "cirugia ambulatoria", "VR": "virtual",
    "HH": "atencion domiciliaria",
}


def dosis_desde_instruccion(instrucciones):
    if not instrucciones:
        return None, None, None, None, None, None
    dosis = instrucciones[0]
    valor = unidad = None
    dose_rate = dosis.get("doseAndRate") or []
    if dose_rate and dose_rate[0].get("doseQuantity"):
        cantidad = dose_rate[0]["doseQuantity"]
        valor = cantidad.get("value")
        unidad = cantidad.get("unit") or cantidad.get("code")
    via = (coding(dosis.get("route")) or {}).get("nombre")
    repeat = (dosis.get("timing") or {}).get("repeat") or {}
    frecuencia = None
    if repeat.get("frequency") is not None and repeat.get("period") is not None:
        frecuencia = (f"{repeat['frequency']} vez/veces cada {repeat['period']} "
                      f"{repeat.get('periodUnit', '')}").strip()
    es_prn = dosis.get("asNeededBoolean")
    texto = dosis.get("text")
    if not texto:
        partes = []
        if valor is not None:
            partes.append(f"{valor} {unidad or ''}".strip())
        if frecuencia:
            partes.append(frecuencia)
        if es_prn:
            partes.append("segun necesidad (PRN)")
        texto = ", ".join(partes) or None
    return texto, valor, unidad, via, frecuencia, es_prn


def campos_valor(res):
    """Representación tipada de Observation.value[x] o component.value[x]."""
    salida = {
        "valor_numero": None, "valor_texto": None, "valor_codigo": None,
        "valor_sistema": None, "unidad": None, "unidad_sistema": None,
        "unidad_codigo": None, "comparador": None,
    }
    if "valueQuantity" in res:
        cantidad = res["valueQuantity"] or {}
        salida.update(valor_numero=cantidad.get("value"), unidad=cantidad.get("unit"),
                      unidad_sistema=cantidad.get("system"), unidad_codigo=cantidad.get("code"),
                      comparador=cantidad.get("comparator"))
    elif "valueCodeableConcept" in res:
        valor = coding(res["valueCodeableConcept"])
        if valor:
            salida.update(valor_codigo=valor["codigo"], valor_sistema=valor["sistema"],
                          valor_texto=valor["nombre"])
    elif "valueString" in res:
        salida["valor_texto"] = res["valueString"]
    elif "valueBoolean" in res:
        salida["valor_texto"] = str(res["valueBoolean"]).lower()
    elif "valueInteger" in res:
        salida["valor_numero"] = res["valueInteger"]
    return salida


def valor_observacion(res):
    """Vista compatible para texto descriptivo y pruebas existentes."""
    valor = campos_valor(res)
    if valor["valor_numero"] is not None:
        return valor["valor_numero"], valor["unidad"] or valor["unidad_codigo"]
    if valor["valor_texto"] is not None:
        return valor["valor_texto"], None
    if res.get("component"):
        partes = []
        unidad = None
        for componente in res["component"]:
            nombre = (coding(componente.get("code")) or {}).get("nombre") or "?"
            cv = campos_valor(componente)
            v = cv["valor_numero"] if cv["valor_numero"] is not None else cv["valor_texto"]
            partes.append(f"{nombre} {v if v is not None else '?'}")
            unidad = unidad or cv["unidad"] or cv["unidad_codigo"]
        return " / ".join(partes), unidad
    return None, None


def _referencia_texto(ref):
    return ref.get("reference") if isinstance(ref, dict) else ref


def _tipo_id_desde_url(valor):
    ruta = unquote(urlparse(valor).path if "://" in valor else valor)
    partes = [p for p in ruta.strip("/").split("/") if p]
    if "_history" in partes:
        i = partes.index("_history")
        partes = partes[:i]
    if len(partes) < 2:
        return None, None
    return partes[-2], partes[-1]


def resolver_ref(ref, ctx, ruta):
    """Resuelve urn, relativas, absolutas y contained; registra los fallos."""
    valor = _referencia_texto(ref)
    if not valor:
        return None
    if "?" in valor:
        ctx["unresolved"].append((ctx["current_key"], ruta, valor, "condicional"))
        return None
    if valor.startswith("#"):
        clave = ctx["contained_refs"].get(valor)
    else:
        clave = ctx["ref_to_key"].get(valor)
        if not clave and valor.startswith("urn:uuid:"):
            clave = ctx["ref_to_key"].get(valor[len("urn:uuid:"):])
        if not clave:
            tipo, logical_id = _tipo_id_desde_url(valor)
            clave = resource_key(ctx["source"], tipo, logical_id)
    if not clave or clave not in ctx["known_keys"]:
        ctx["unresolved"].append((ctx["current_key"], ruta, valor, "no encontrado"))
        return None
    return clave


def _provenance(res, ctx):
    meta = res.get("meta") or {}
    return {
        "id": ctx["current_key"], "fhir_id": res.get("id"),
        "fhir_tipo": res.get("resourceType"), "fuente_datos": ctx["source"],
        "full_url": ctx.get("current_full_url"), "version_id": meta.get("versionId"),
        "ultima_actualizacion_fhir": norm_dt(meta.get("lastUpdated")),
        "perfiles_fhir": meta.get("profile") or [],
    }


def _codigos(cc, preferido, label):
    resultado = []
    for item in codings(cc, preferido):
        item = dict(item)
        item["concepto_id"] = f"{label}|{item['sistema']}|{item['codigo']}"
        resultado.append(item)
    return resultado


def _motivos(res, ctx, path="reasonCode"):
    salida = []
    for concepto in res.get(path) or []:
        salida.extend(_codigos(concepto, "snomed", "ConceptoMotivo"))
    return salida


def _razones(res, ctx, path="reasonReference"):
    salida = []
    for i, ref in enumerate(res.get(path) or []):
        destino = resolver_ref(ref, ctx, f"{path}[{i}]")
        if destino:
            salida.append({"dest_id": destino, "fhir_path": f"{path}[{i}]"})
    return salida


# ---------------------------------------------------------------------------
# Extractores FHIR
# ---------------------------------------------------------------------------

def fila_patient(res, ctx):
    nombres = res.get("name") or []
    oficial = next((n for n in nombres if n.get("use") == "official"),
                   nombres[0] if nombres else {})
    nombre = " ".join((oficial.get("given") or []) + [oficial.get("family", "")]).strip() or None
    fallecimiento = norm_dt(res.get("deceasedDateTime"))
    return {**_provenance(res, ctx), "nombre": nombre,
            "sexo": res.get("gender", "unknown"),
            "fecha_nacimiento": norm_date(res.get("birthDate")),
            "fallecido": bool(fallecimiento or res.get("deceasedBoolean")),
            "fecha_fallecimiento": fallecimiento}


def _evento_base(res, ctx, paciente_ref, fecha, texto):
    return {**_provenance(res, ctx),
            "paciente_id": resolver_ref(paciente_ref, ctx, "subject/patient"),
            "fecha_efectiva": fecha,
            "fecha_desconocida": fecha is None,
            "texto_descriptivo": texto}


def fila_encounter(res, ctx):
    periodo = res.get("period") or {}
    clase = (res.get("class") or {}).get("code")
    tipo = CLASE_ENCUENTRO.get(clase, (res.get("class") or {}).get("display")
                               or clase or "desconocido")
    motivo = None
    if res.get("reasonCode"):
        motivo = (coding(res["reasonCode"][0]) or {}).get("nombre")
    if not motivo and res.get("type"):
        motivo = (coding(res["type"][0]) or {}).get("nombre")
    fecha = norm_dt(periodo.get("start"))
    return {**_evento_base(res, ctx, res.get("subject"), fecha,
                           build_texto("Encuentro", tipo=tipo, fecha=fmt_fecha(fecha))),
            "tipo": tipo, "fecha_inicio": fecha, "fecha_fin": norm_dt(periodo.get("end")),
            "motivo_consulta": motivo}


def fila_condition(res, ctx):
    cs = _codigos(res.get("code"), "snomed", "ConceptoDiagnostico")
    principal = next((c for c in cs if c["principal"]), {})
    estado = code_only(res.get("clinicalStatus")) or "unknown"
    fecha_inicio = norm_dt(res.get("onsetDateTime"))
    fecha = fecha_inicio or norm_dt(res.get("recordedDate"))
    return {**_evento_base(res, ctx, res.get("subject"), fecha,
                           build_texto("Condicion", nombre=principal.get("nombre"),
                                       estado=estado, fecha=fmt_fecha(fecha))),
            "nombre": principal.get("nombre"), "estado_clinico": estado,
            "estado_verificacion": code_only(res.get("verificationStatus")),
            "fecha_inicio": fecha_inicio, "fecha_resolucion": norm_dt(res.get("abatementDateTime")),
            "severidad": (coding(res.get("severity")) or {}).get("nombre"),
            "es_cronica": None, "encuentro_id": resolver_ref(res.get("encounter"), ctx, "encounter"),
            "codigos": cs}


def fila_medication_request(res, ctx):
    cc = res.get("medicationCodeableConcept")
    if not cc and res.get("medicationReference"):
        med_key = resolver_ref(res.get("medicationReference"), ctx, "medicationReference")
        cc = (ctx["resources_by_key"].get(med_key) or {}).get("code")
    cs = _codigos(cc, "rxnorm", "Farmaco")
    principal = next((c for c in cs if c["principal"]), {})
    estado = res.get("status", "unknown")
    fecha = norm_dt(res.get("authoredOn"))
    encuentro_id = resolver_ref(res.get("encounter"), ctx, "encounter")
    if fecha is None and encuentro_id:
        enc = ctx["resources_by_key"].get(encuentro_id) or {}
        fecha = norm_dt((enc.get("period") or {}).get("start"))
    dosis_texto, valor, unidad, via, frecuencia, es_prn = dosis_desde_instruccion(
        res.get("dosageInstruction"))
    return {**_evento_base(res, ctx, res.get("subject"), fecha,
                           build_texto("Prescripcion", farmaco=principal.get("nombre"),
                                       estado=estado, fecha=fmt_fecha(fecha),
                                       dosis_texto=dosis_texto or "")),
            "estado": estado, "fecha_inicio": fecha, "fecha_fin": None,
            "dosis_texto": dosis_texto, "dosis_valor": valor, "dosis_unidad": unidad,
            "via": via, "frecuencia": frecuencia, "motivo_suspension": None,
            "es_PRN": es_prn, "encuentro_id": encuentro_id, "codigos": cs,
            "razones": _razones(res, ctx), "motivos": _motivos(res, ctx)}


def fila_procedure(res, ctx):
    cs = _codigos(res.get("code"), "snomed", "ConceptoProcedimiento")
    principal = next((c for c in cs if c["principal"]), {})
    periodo = res.get("performedPeriod") or {}
    fecha = norm_dt(periodo.get("start")) or norm_dt(res.get("performedDateTime"))
    fin = norm_dt(periodo.get("end"))
    duracion = round((fin - fecha).total_seconds() / 60) if fecha and fin else None
    return {**_evento_base(res, ctx, res.get("subject"), fecha,
                           build_texto("Procedimiento", nombre=principal.get("nombre"),
                                       fecha=fmt_fecha(fecha))),
            "nombre": principal.get("nombre"), "estado": res.get("status", "unknown"),
            "fecha": fecha, "duracion_min": duracion, "resultado": None, "urgente": None,
            "encuentro_id": resolver_ref(res.get("encounter"), ctx, "encounter"),
            "codigos": cs, "razones": _razones(res, ctx), "motivos": _motivos(res, ctx)}


def fila_observation(res, ctx):
    cs = _codigos(res.get("code"), "loinc", "ConceptoLab")
    principal = next((c for c in cs if c["principal"]), {})
    fecha = norm_dt(res.get("effectiveDateTime")) or norm_dt(res.get("issued"))
    valor = campos_valor(res)
    valor_texto, unidad_texto = valor_observacion(res)
    rango = (res.get("referenceRange") or [{}])[0]
    componentes = []
    for indice, componente in enumerate(res.get("component") or []):
        ccs = _codigos(componente.get("code"), "loinc", "ConceptoLab")
        cp = next((c for c in ccs if c["principal"]), {})
        componentes.append({
            "id": f"{ctx['current_key']}#component/{indice}", "indice": indice,
            "paciente_id": None, "nombre": cp.get("nombre"), "codigos": ccs,
            **campos_valor(componente),
            "rango_ref_min": ((componente.get("referenceRange") or [{}])[0].get("low") or {}).get("value"),
            "rango_ref_max": ((componente.get("referenceRange") or [{}])[0].get("high") or {}).get("value"),
        })
    interpretacion = None
    if res.get("interpretation"):
        interpretacion = (code_only(res["interpretation"][0]) or "").lower() or None
    fila = {**_evento_base(res, ctx, res.get("subject"), fecha,
                           build_texto("Observacion", nombre=principal.get("nombre"),
                                       valor=valor_texto, unidad=unidad_texto or "",
                                       fecha=fmt_fecha(fecha))),
            "nombre": principal.get("nombre"), **valor,
            "fecha": fecha, "rango_ref_min": (rango.get("low") or {}).get("value"),
            "rango_ref_max": (rango.get("high") or {}).get("value"),
            "interpretacion": interpretacion,
            "encuentro_id": resolver_ref(res.get("encounter"), ctx, "encounter"),
            "codigos": cs, "componentes": componentes}
    for componente in fila["componentes"]:
        componente["paciente_id"] = fila["paciente_id"]
    return fila


def fila_allergy(res, ctx):
    cs = _codigos(res.get("code"), "snomed", "Sustancia")
    principal = next((c for c in cs if c["principal"]), {})
    fecha = norm_dt(res.get("recordedDate"))
    reacciones = []
    for reaccion in res.get("reaction") or []:
        reacciones.extend((coding(m) or {}).get("nombre") for m in reaccion.get("manifestation") or [])
    reacciones = [r for r in reacciones if r]
    return {**_evento_base(res, ctx, res.get("patient"), fecha,
                           build_texto("Alergia", nombre=principal.get("nombre"),
                                       criticidad=res.get("criticality") or "sin criticidad")),
            "tipo": res.get("type"), "criticidad": res.get("criticality"),
            "reaccion": "; ".join(reacciones) or None,
            "estado": code_only(res.get("clinicalStatus")), "codigos": cs}


def fila_immunization(res, ctx):
    cs = _codigos(res.get("vaccineCode"), None, "ConceptoProcedimiento")
    principal = next((c for c in cs if c["principal"]), {})
    fecha = norm_dt(res.get("occurrenceDateTime"))
    protocolo = (res.get("protocolApplied") or [{}])[0]
    dosis = protocolo.get("doseNumberPositiveInt") or protocolo.get("doseNumberString")
    return {**_evento_base(res, ctx, res.get("patient"), fecha,
                           build_texto("Inmunizacion", nombre=principal.get("nombre"),
                                       fecha=fmt_fecha(fecha))),
            "nombre": principal.get("nombre"), "fecha": fecha, "dosis_numero": dosis,
            "lote": res.get("lotNumber"), "estado": res.get("status", "unknown"),
            "codigos": cs}


HANDLERS = {
    "Patient": fila_patient, "Encounter": fila_encounter, "Condition": fila_condition,
    "MedicationRequest": fila_medication_request, "Procedure": fila_procedure,
    "Observation": fila_observation, "AllergyIntolerance": fila_allergy,
    "Immunization": fila_immunization,
}
ORDEN = ["Patient", "Encounter", "Condition", "Observation", "Procedure",
         "MedicationRequest", "AllergyIntolerance", "Immunization"]


# ---------------------------------------------------------------------------
# Escritura Neo4j
# ---------------------------------------------------------------------------

Q_PACIENTE = """
UNWIND $filas AS f
MERGE (p:Paciente {id: f.id})
ON CREATE SET p.fecha_ingesta = datetime()
SET p.fecha_actualizacion_ingesta = datetime(), p.fhir_id = f.fhir_id,
    p.fhir_tipo = f.fhir_tipo, p.fuente_datos = f.fuente_datos,
    p.full_url = f.full_url, p.version_id = f.version_id,
    p.ultima_actualizacion_fhir = f.ultima_actualizacion_fhir,
    p.perfiles_fhir = f.perfiles_fhir, p.nombre = f.nombre, p.sexo = f.sexo,
    p.fecha_nacimiento = f.fecha_nacimiento, p.fallecido = f.fallecido,
    p.fecha_fallecimiento = f.fecha_fallecimiento
"""


def q_nodo_evento(label, props):
    sets = ", ".join(f"n.{prop} = f.{prop}" for prop in props)
    return f"""
UNWIND $filas AS f
MERGE (n:{label}:Evento {{id: f.id}})
ON CREATE SET n.fecha_ingesta = datetime(), n.fecha_registro = datetime(), n.embedding = null
SET n.fecha_actualizacion_ingesta = datetime(), n.fhir_id = f.fhir_id,
    n.fhir_tipo = f.fhir_tipo, n.fuente_datos = f.fuente_datos,
    n.full_url = f.full_url, n.version_id = f.version_id,
    n.ultima_actualizacion_fhir = f.ultima_actualizacion_fhir,
    n.perfiles_fhir = f.perfiles_fhir, n.paciente_id = f.paciente_id,
    n.fecha_efectiva = f.fecha_efectiva, n.fecha_desconocida = f.fecha_desconocida,
    n.texto_descriptivo = f.texto_descriptivo, {sets}
WITH n, f
MATCH (p:Paciente {{id: f.paciente_id}})
MERGE (n)-[:DE_PACIENTE]->(p)
"""


def q_encuentro(rel):
    return f"""
UNWIND $filas AS f
MATCH (n:Evento {{id: f.id}}), (e:Encuentro {{id: f.encuentro_id}})
WHERE n.paciente_id = e.paciente_id
MERGE (n)-[:{rel}]->(e)
"""


def q_concepto(label, rel, prop_nombre="nombre"):
    return f"""
UNWIND $filas AS f
MATCH (n {{id: f.nodo_id}})
MERGE (c:{label} {{sistema: f.sistema, codigo: f.codigo}})
SET c.id = f.concepto_id, c.{prop_nombre} = f.nombre, c.version = f.version
MERGE (n)-[r:{rel}]->(c)
SET r.principal = f.principal, r.user_selected = f.user_selected
"""


Q_COMPONENTES = """
UNWIND $filas AS f
MATCH (o:Observacion {id: f.observacion_id})
MERGE (c:ComponenteObservacion {id: f.id})
SET c.indice = f.indice, c.paciente_id = f.paciente_id, c.nombre = f.nombre,
    c.valor_numero = f.valor_numero, c.valor_texto = f.valor_texto,
    c.valor_codigo = f.valor_codigo, c.valor_sistema = f.valor_sistema,
    c.unidad = f.unidad, c.unidad_sistema = f.unidad_sistema,
    c.unidad_codigo = f.unidad_codigo, c.comparador = f.comparador,
    c.rango_ref_min = f.rango_ref_min, c.rango_ref_max = f.rango_ref_max
MERGE (o)-[:TIENE_COMPONENTE]->(c)
"""


Q_RAZON = """
UNWIND $filas AS f
MATCH (n:Evento {id: f.id}), (dest:Evento {id: f.dest_id})
WHERE n.paciente_id = dest.paciente_id
MERGE (n)-[r:TIENE_RAZON]->(dest)
SET r.fuente = 'explicita', r.confianza = 1.0, r.fhir_path = f.fhir_path
"""


def q_causal(rel):
    return f"""
UNWIND $filas AS f
MATCH (n:Evento {{id: f.id}}), (dest:Condicion {{id: f.dest_id}})
WHERE n.paciente_id = dest.paciente_id
MERGE (n)-[r:{rel}]->(dest)
SET r.fuente = 'explicita', r.confianza = 1.0, r.fhir_path = f.fhir_path
"""


ESCRITURA = {
    "Patient": {"nodo": Q_PACIENTE},
    "Encounter": {"nodo": q_nodo_evento("Encuentro", ["tipo", "fecha_inicio", "fecha_fin", "motivo_consulta"])},
    "Condition": {"nodo": q_nodo_evento("Condicion", ["nombre", "estado_clinico", "estado_verificacion", "fecha_inicio", "fecha_resolucion", "severidad", "es_cronica"]), "encuentro": q_encuentro("REGISTRADA_EN"), "concepto": (q_concepto("ConceptoDiagnostico", "CODIFICADA_COMO"), "CODIFICADA_COMO")},
    "MedicationRequest": {"nodo": q_nodo_evento("Prescripcion", ["estado", "fecha_inicio", "fecha_fin", "dosis_texto", "dosis_valor", "dosis_unidad", "via", "frecuencia", "motivo_suspension", "es_PRN"]), "encuentro": q_encuentro("PRESCRITA_EN"), "concepto": (q_concepto("Farmaco", "DE_FARMACO", "nombre_generico"), "DE_FARMACO"), "causal": q_causal("TRATA")},
    "Procedure": {"nodo": q_nodo_evento("Procedimiento", ["nombre", "estado", "fecha", "duracion_min", "resultado", "urgente"]), "encuentro": q_encuentro("REALIZADO_EN"), "concepto": (q_concepto("ConceptoProcedimiento", "TIPO"), "TIPO"), "causal": q_causal("INDICADO_POR")},
    "Observation": {"nodo": q_nodo_evento("Observacion", ["nombre", "valor_numero", "valor_texto", "valor_codigo", "valor_sistema", "unidad", "unidad_sistema", "unidad_codigo", "comparador", "fecha", "rango_ref_min", "rango_ref_max", "interpretacion"]), "encuentro": q_encuentro("TOMADA_EN"), "concepto": (q_concepto("ConceptoLab", "MIDE"), "MIDE")},
    "AllergyIntolerance": {"nodo": q_nodo_evento("Alergia", ["tipo", "criticidad", "reaccion", "estado"]), "concepto": (q_concepto("Sustancia", "A_SUSTANCIA"), "A_SUSTANCIA")},
    "Immunization": {"nodo": q_nodo_evento("Inmunizacion", ["nombre", "fecha", "dosis_numero", "lote", "estado"]), "concepto": (q_concepto("ConceptoProcedimiento", "TIPO"), "TIPO")},
}


def _chunks(filas, tam=BATCH):
    for i in range(0, len(filas), tam):
        yield filas[i:i + tam]


def _run_batches(tx, query, filas):
    for lote in _chunks(filas):
        tx.run(query, filas=lote).consume()


def escribir_nodos(tx, filas_por_tipo):
    for tipo in ORDEN:
        filas = filas_por_tipo.get(tipo, [])
        if filas:
            _run_batches(tx, ESCRITURA[tipo]["nodo"], filas)


def _filas_codigos(filas):
    return [{**codigo, "nodo_id": fila["id"]}
            for fila in filas for codigo in fila.get("codigos", [])]


def escribir_relaciones(tx, filas_por_tipo):
    for tipo in ORDEN:
        filas = filas_por_tipo.get(tipo, [])
        if not filas or tipo == "Patient":
            continue
        config = ESCRITURA[tipo]
        if config.get("encuentro"):
            con_encuentro = [f for f in filas if f.get("encuentro_id")]
            if con_encuentro:
                _run_batches(tx, config["encuentro"], con_encuentro)
        if config.get("concepto"):
            codigos_filas = _filas_codigos(filas)
            if codigos_filas:
                _run_batches(tx, config["concepto"][0], codigos_filas)
        razones = [{"id": f["id"], **razon} for f in filas for razon in f.get("razones", [])]
        if razones:
            _run_batches(tx, Q_RAZON, razones)
            if config.get("causal"):
                _run_batches(tx, config["causal"], razones)
        motivos = [{**motivo, "nodo_id": f["id"]}
                   for f in filas for motivo in f.get("motivos", [])]
        if motivos:
            _run_batches(tx, q_concepto("ConceptoMotivo", "TIENE_MOTIVO_CODIFICADO"), motivos)

    observaciones = filas_por_tipo.get("Observation", [])
    componentes = [{**c, "observacion_id": f["id"]}
                   for f in observaciones for c in f.get("componentes", [])]
    if componentes:
        _run_batches(tx, Q_COMPONENTES, componentes)
        codigos_componentes = [{**codigo, "nodo_id": c["id"]}
                               for c in componentes for codigo in c.get("codigos", [])]
        if codigos_componentes:
            _run_batches(tx, q_concepto("ConceptoLab", "MIDE"), codigos_componentes)


def aplicar_schema(driver):
    texto = Path(__file__).with_name("schema.cypher").read_text(encoding="utf-8")
    sin_comentarios = "\n".join(linea for linea in texto.splitlines()
                                  if not linea.strip().startswith("//"))
    with driver.session() as sesion:
        for sentencia in sin_comentarios.split(";"):
            if sentencia.strip():
                sesion.run(sentencia).consume()


# ---------------------------------------------------------------------------
# Preparación global en dos pasadas
# ---------------------------------------------------------------------------

def _version_orden(res):
    meta = res.get("meta") or {}
    return meta.get("lastUpdated") or "", meta.get("versionId") or ""


def cargar_recursos(directorio, fuente):
    archivos = sorted(p for p in directorio.glob("*.json")
                      if not p.name.startswith(EXCLUIR_PREFIJOS))
    wrappers = {}
    ref_to_key = {}
    resources_by_key = {}
    duplicados = 0
    for archivo in archivos:
        with archivo.open(encoding="utf-8") as fh:
            bundle = json.load(fh)
        for entry in bundle.get("entry", []):
            res = entry.get("resource") or {}
            tipo, logical_id = res.get("resourceType"), res.get("id")
            key = resource_key(fuente, tipo, logical_id)
            if not key:
                continue
            wrapper = {"resource": res, "fullUrl": entry.get("fullUrl"),
                       "archivo": archivo.name, "key": key}
            anterior = wrappers.get(key)
            if anterior:
                duplicados += 1
                if _version_orden(anterior["resource"]) > _version_orden(res):
                    continue
            wrappers[key] = wrapper
            resources_by_key[key] = res
            for referencia in (entry.get("fullUrl"), f"{tipo}/{logical_id}"):
                if referencia:
                    ref_to_key[referencia] = key
            full_url = entry.get("fullUrl") or ""
            if full_url.startswith("urn:uuid:"):
                ref_to_key[full_url[len("urn:uuid:"):]] = key
            for contained in res.get("contained") or []:
                ckey = resource_key(fuente, contained.get("resourceType"), contained.get("id"), key)
                if ckey:
                    resources_by_key[ckey] = contained
    return archivos, list(wrappers.values()), ref_to_key, resources_by_key, duplicados


def extraer_filas(wrappers, fuente, ref_to_key, resources_by_key):
    known_keys = set(resources_by_key)
    filas_por_tipo = defaultdict(list)
    no_manejados, errores, unresolved = Counter(), [], []
    for wrapper in wrappers:
        res = wrapper["resource"]
        tipo = res.get("resourceType")
        handler = HANDLERS.get(tipo)
        if not handler:
            no_manejados[tipo] += 1
            continue
        contained_refs = {}
        for contained in res.get("contained") or []:
            if contained.get("id"):
                contained_refs[f"#{contained['id']}"] = resource_key(
                    fuente, contained.get("resourceType"), contained["id"], wrapper["key"])
        ctx = {"source": fuente, "ref_to_key": ref_to_key,
               "resources_by_key": resources_by_key, "known_keys": known_keys,
               "unresolved": unresolved, "current_key": wrapper["key"],
               "current_full_url": wrapper["fullUrl"], "contained_refs": contained_refs}
        try:
            fila = handler(res, ctx)
        except Exception as exc:
            errores.append((wrapper["archivo"], tipo, res.get("id"), repr(exc)))
            continue
        if fila and fila.get("id") and (tipo == "Patient" or fila.get("paciente_id")):
            filas_por_tipo[tipo].append(fila)
        else:
            errores.append((wrapper["archivo"], tipo, res.get("id"),
                            "sin id o referencia de paciente resoluble"))
    return filas_por_tipo, no_manejados, errores, unresolved


def main(argv=None):
    parser = argparse.ArgumentParser(description="Ingesta FHIR R4 robusta a Neo4j")
    parser.add_argument("directorio", type=Path)
    parser.add_argument("--source", default="synthea",
                        help="identificador estable de la fuente/dataset")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    archivos, wrappers, refs, resources, duplicados = cargar_recursos(
        args.directorio, args.source)
    if not archivos:
        parser.error(f"no hay bundles JSON en {args.directorio}")
    filas, ignorados, errores, unresolved = extraer_filas(
        wrappers, args.source, refs, resources)

    driver = GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)
    try:
        driver.verify_connectivity()
        aplicar_schema(driver)
        with driver.session() as sesion:
            sesion.execute_write(escribir_nodos, filas)
            sesion.execute_write(escribir_relaciones, filas)
    finally:
        driver.close()

    print(f"Procesados {len(archivos)} bundles de fuente '{args.source}'.")
    print("\n=== Recursos ingeridos ===")
    for tipo in ORDEN:
        print(f"  {tipo:22s} {len(filas.get(tipo, [])):>7d}")
    print(f"\nVersiones/duplicados reemplazados: {duplicados}")
    print(f"Referencias no resueltas: {len(unresolved)}")
    for origen, ruta, valor, causa in unresolved[:20]:
        print(f"  {origen} {ruta}: {valor} ({causa})")
    print("\n=== resourceTypes no manejados ===")
    for tipo, cantidad in ignorados.most_common():
        print(f"  {str(tipo):22s} {cantidad:>7d}")
    if errores:
        print(f"\n=== Errores ({len(errores)}) ===")
        for archivo, tipo, rid, error in errores[:20]:
            print(f"  {archivo} {tipo} {rid}: {error}")
        raise SystemExit(1)
    print("\nSin errores de extracción.")


if __name__ == "__main__":
    main()
