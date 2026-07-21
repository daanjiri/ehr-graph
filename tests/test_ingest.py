"""Unit tests de las utilidades puras de ingest.py — sin BD ni Docker."""

import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from ingest import (build_texto, campos_valor, code_only, coding, codings,
                    dosis_desde_instruccion, fila_observation, norm_date, norm_dt,
                    ref_id, resolver_ref, resource_key, valor_observacion)


# --- norm_dt: los 3 casos de PLAN.md §12 fase 1 ---

def test_norm_dt_none():
    assert norm_dt(None) is None
    assert norm_dt("") is None


def test_norm_dt_solo_fecha():
    d = norm_dt("2015-03-14")
    assert d == datetime(2015, 3, 14, 0, 0, 0, tzinfo=timezone.utc)


def test_norm_dt_con_timezone():
    d = norm_dt("2015-03-14T09:22:31-04:00")
    assert d == datetime(2015, 3, 14, 13, 22, 31, tzinfo=timezone.utc)
    assert d.tzinfo == timezone.utc


def test_norm_dt_zulu():
    d = norm_dt("2020-01-01T00:00:00Z")
    assert d == datetime(2020, 1, 1, tzinfo=timezone.utc)


def test_norm_dt_invalida():
    assert norm_dt("no-es-fecha") is None


def test_norm_date():
    assert norm_date("1987-06-05") == date(1987, 6, 5)
    assert norm_date(None) is None


# --- ref_id: urn:uuid, Tipo/id, condicional, None ---

def test_ref_id_urn_uuid():
    assert ref_id({"reference": "urn:uuid:abc-123"}) == "abc-123"


def test_ref_id_tipo_slash():
    assert ref_id({"reference": "Patient/xyz-9"}) == "xyz-9"


def test_ref_id_condicional_devuelve_none():
    # Referencias condicionales de Synthea (Practitioner?identifier=...) no resuelven
    ref = {"reference": "Practitioner?identifier=http://hl7.org/fhir/sid/us-npi|9999"}
    assert ref_id(ref) is None


def test_ref_id_none_y_string():
    assert ref_id(None) is None
    assert ref_id({}) is None
    assert ref_id("urn:uuid:plain-string") == "plain-string"


def test_resource_key_evitar_colisiones_entre_tipo_y_fuente():
    assert resource_key("hospital-a", "Patient", "123") == "hospital-a|Patient/123"
    assert resource_key("hospital-a", "Patient", "123") != resource_key(
        "hospital-a", "Observation", "123")
    assert resource_key("hospital-a", "Patient", "123") != resource_key(
        "hospital-b", "Patient", "123")


def _ctx_referencias():
    claves = {
        "fuente|Patient/p1", "fuente|Condition/c1",
        "fuente|Observation/o1", "fuente|Medication/m1",
        "fuente|Observation/o1#Medication/cm1",
    }
    return {
        "source": "fuente", "current_key": "fuente|Observation/o1",
        "ref_to_key": {
            "urn:uuid:patient": "fuente|Patient/p1",
            "patient": "fuente|Patient/p1",
            "Condition/c1": "fuente|Condition/c1",
            "https://fhir.example/Medication/m1": "fuente|Medication/m1",
        },
        "known_keys": claves, "contained_refs": {
            "#cm1": "fuente|Observation/o1#Medication/cm1",
        },
        "unresolved": [],
    }


def test_resolver_referencias_urn_relativa_absoluta_y_contained():
    ctx = _ctx_referencias()
    assert resolver_ref("urn:uuid:patient", ctx, "subject") == "fuente|Patient/p1"
    assert resolver_ref("Condition/c1", ctx, "reasonReference") == "fuente|Condition/c1"
    assert resolver_ref("https://fhir.example/Medication/m1", ctx, "medicationReference") == "fuente|Medication/m1"
    assert resolver_ref("#cm1", ctx, "medicationReference") == "fuente|Observation/o1#Medication/cm1"
    assert ctx["unresolved"] == []


def test_resolver_referencia_no_resuelta_se_reporta():
    ctx = _ctx_referencias()
    assert resolver_ref("Condition/no-existe", ctx, "reasonReference[0]") is None
    assert ctx["unresolved"][0][1:] == (
        "reasonReference[0]", "Condition/no-existe", "no encontrado")


# --- coding / code_only ---

def test_coding_completo():
    cc = {"coding": [{"system": "http://snomed.info/sct", "code": "44054006",
                      "display": "Diabetes mellitus type 2"}]}
    c = coding(cc)
    assert c == {"codigo": "44054006", "nombre": "Diabetes mellitus type 2",
                 "sistema": "http://snomed.info/sct"}


def test_coding_sin_display_usa_text():
    cc = {"coding": [{"code": "X1"}], "text": "Algo"}
    assert coding(cc)["nombre"] == "Algo"


def test_coding_ausente_o_vacio():
    assert coding(None) is None
    assert coding({}) is None
    assert coding({"coding": []}) is None
    assert coding({"coding": [{}]}) is None


def test_codings_conserva_sistemas_y_marca_preferido():
    cc = {"text": "Glucosa", "coding": [
        {"system": "http://snomed.info/sct", "code": "123", "display": "Glucose"},
        {"system": "http://loinc.org", "code": "123", "display": "Glucose lab"},
    ]}
    resultado = codings(cc, "loinc")
    assert len(resultado) == 2
    assert [c["sistema"] for c in resultado] == ["http://snomed.info/sct", "http://loinc.org"]
    assert [c["principal"] for c in resultado] == [False, True]


def test_code_only_codeable_concept():
    # clinicalStatus es CodeableConcept, no string
    cs = {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                      "code": "active"}]}
    assert code_only(cs) == "active"
    assert code_only(None) is None


# --- plantillas ---

def test_build_texto_encuentro_con_campo_tipo():
    # Regresión: la plantilla de Encuentro usa un campo llamado "tipo" que no
    # debe colisionar con el primer parámetro de build_texto
    t = build_texto("Encuentro", tipo="ambulatorio", fecha="2021-03-01")
    assert t == "Encuentro clinico (ambulatorio) el 2021-03-01."


def test_build_texto_condicion():
    t = build_texto("Condicion", nombre="Hypertension", estado="active", fecha="2019-05-01")
    assert t == "Diagnostico: Hypertension (active), inicio 2019-05-01."


def test_build_texto_prescripcion_sin_dosis():
    t = build_texto("Prescripcion", farmaco="Metformin", estado="active",
                    fecha="2020-02-02", dosis_texto="")
    assert t == "Prescripcion de Metformin (active), iniciada 2020-02-02."


# --- dosis y valores de observación ---

def test_dosis_desde_instruccion_componentes():
    di = [{"doseAndRate": [{"doseQuantity": {"value": 5, "unit": "mg"}}],
           "timing": {"repeat": {"frequency": 1, "period": 1, "periodUnit": "d"}},
           "asNeededBoolean": False}]
    texto, valor, unidad, via, frecuencia, es_prn = dosis_desde_instruccion(di)
    assert valor == 5 and unidad == "mg"
    assert "5 mg" in texto
    assert es_prn is False


def test_dosis_vacia():
    assert dosis_desde_instruccion(None) == (None, None, None, None, None, None)
    assert dosis_desde_instruccion([]) == (None, None, None, None, None, None)


def test_valor_observacion_quantity():
    res = {"valueQuantity": {"value": 6.2, "unit": "%"}}
    assert valor_observacion(res) == (6.2, "%")


def test_valor_observacion_componentes_presion():
    res = {"component": [
        {"code": {"coding": [{"code": "8480-6", "display": "Systolic Blood Pressure"}]},
         "valueQuantity": {"value": 120, "unit": "mm[Hg]"}},
        {"code": {"coding": [{"code": "8462-4", "display": "Diastolic Blood Pressure"}]},
         "valueQuantity": {"value": 80, "unit": "mm[Hg]"}},
    ]}
    valor, unidad = valor_observacion(res)
    assert "Systolic Blood Pressure 120" in valor and "Diastolic Blood Pressure 80" in valor
    assert unidad == "mm[Hg]"


def test_valor_observacion_codeable_concept():
    res = {"valueCodeableConcept": {"coding": [{"code": "8517006", "display": "Ex-smoker"}]}}
    assert valor_observacion(res) == ("Ex-smoker", None)


def test_campos_valor_quantity_con_ucum():
    resultado = campos_valor({"valueQuantity": {
        "value": 120, "unit": "mmHg", "system": "http://unitsofmeasure.org",
        "code": "mm[Hg]", "comparator": ">",
    }})
    assert resultado["valor_numero"] == 120
    assert resultado["unidad_sistema"] == "http://unitsofmeasure.org"
    assert resultado["unidad_codigo"] == "mm[Hg]"
    assert resultado["comparador"] == ">"


def test_fila_observation_preserva_componentes_tipados():
    paciente = "fuente|Patient/p1"
    key = "fuente|Observation/o1"
    ctx = {
        **_ctx_referencias(), "current_key": key, "current_full_url": "Observation/o1",
        "resources_by_key": {}, "known_keys": {paciente, key},
        "ref_to_key": {"Patient/p1": paciente}, "contained_refs": [], "unresolved": [],
    }
    res = {
        "resourceType": "Observation", "id": "o1", "status": "final",
        "subject": {"reference": "Patient/p1"},
        "effectiveDateTime": "2024-01-01T10:00:00Z",
        "code": {"coding": [{"system": "http://loinc.org", "code": "85354-9",
                              "display": "Blood pressure panel"}]},
        "component": [{
            "code": {"coding": [{"system": "http://loinc.org", "code": "8480-6",
                                  "display": "Systolic Blood Pressure"}]},
            "valueQuantity": {"value": 120, "system": "http://unitsofmeasure.org",
                              "code": "mm[Hg]", "unit": "mmHg"},
        }],
    }
    fila = fila_observation(res, ctx)
    assert fila["id"] == key and fila["fhir_id"] == "o1"
    assert fila["componentes"][0]["valor_numero"] == 120
    assert fila["componentes"][0]["codigos"][0]["codigo"] == "8480-6"
