"""Unit tests de las utilidades puras de ingest.py — sin BD ni Docker."""

import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from ingest import (URL_RAZA, URL_SEXO_NACIMIENTO, _extension_texto, _mrn,
                    build_texto, campos_valor, code_only, coding, codings,
                    dosis_desde_instruccion, fila_condition, fila_diagnostic_report,
                    fila_immunization, fila_observation, norm_date, norm_dt,
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


# --- demografía US Core del Paciente ---

def test_extension_texto_us_core_race():
    res = {"extension": [{
        "url": URL_RAZA,
        "extension": [
            {"url": "ombCategory", "valueCoding": {"code": "2106-3", "display": "White"}},
            {"url": "text", "valueString": "White"},
        ],
    }]}
    assert _extension_texto(res, URL_RAZA) == "White"


def test_extension_texto_value_code_plano():
    res = {"extension": [{"url": URL_SEXO_NACIMIENTO, "valueCode": "F"}]}
    assert _extension_texto(res, URL_SEXO_NACIMIENTO) == "F"
    assert _extension_texto(res, URL_RAZA) is None
    assert _extension_texto({}, URL_RAZA) is None


def test_mrn_por_tipo_mr_ignora_ssn():
    res = {"identifier": [
        {"value": "999-99-9999", "type": {"coding": [{"code": "SS"}]}},
        {"value": "abc-mrn-1", "type": {"coding": [{"code": "MR"}]}},
    ]}
    assert _mrn(res) == "abc-mrn-1"
    assert _mrn({}) is None


# --- categorías de Observation y Condition ---

def _ctx_evento(key, extra_keys=(), ref_to_key=None):
    claves = {"fuente|Patient/p1", key, *extra_keys}
    return {
        "source": "fuente", "current_key": key, "current_full_url": None,
        "resources_by_key": {}, "known_keys": claves,
        "ref_to_key": {"Patient/p1": "fuente|Patient/p1", **(ref_to_key or {})},
        "contained_refs": {}, "unresolved": [],
    }


def test_fila_observation_survey_no_es_lab():
    ctx = _ctx_evento("fuente|Observation/o2")
    res = {
        "resourceType": "Observation", "id": "o2", "status": "final",
        "subject": {"reference": "Patient/p1"},
        "effectiveDateTime": "2024-01-01T10:00:00Z",
        "category": [{"coding": [{"code": "survey",
                                  "system": "http://terminology.hl7.org/CodeSystem/observation-category"}]}],
        "code": {"coding": [{"system": "http://loinc.org", "code": "44249-1",
                              "display": "PHQ-9 quick depression assessment panel"}]},
        "valueQuantity": {"value": 3, "unit": "{score}"},
    }
    fila = fila_observation(res, ctx)
    assert fila["categoria"] == "survey"
    assert fila["estado"] == "final"
    assert fila["texto_descriptivo"].startswith("Cuestionario/escala:")


def test_fila_observation_sin_categoria_cae_a_lab():
    ctx = _ctx_evento("fuente|Observation/o3")
    res = {
        "resourceType": "Observation", "id": "o3", "status": "final",
        "subject": {"reference": "Patient/p1"},
        "effectiveDateTime": "2024-01-01T10:00:00Z",
        "code": {"coding": [{"system": "http://loinc.org", "code": "2093-3",
                              "display": "Total Cholesterol"}]},
        "valueQuantity": {"value": 180, "unit": "mg/dL"},
    }
    fila = fila_observation(res, ctx)
    assert fila["categoria"] is None
    assert fila["texto_descriptivo"].startswith("Lab/medicion:")


def test_fila_condition_categoria():
    ctx = _ctx_evento("fuente|Condition/c9")
    res = {
        "resourceType": "Condition", "id": "c9",
        "subject": {"reference": "Patient/p1"},
        "onsetDateTime": "2020-01-01T00:00:00Z",
        "clinicalStatus": {"coding": [{"code": "active"}]},
        "category": [{"coding": [{"code": "encounter-diagnosis",
                                  "system": "http://terminology.hl7.org/CodeSystem/condition-category"}]}],
        "code": {"coding": [{"system": "http://snomed.info/sct", "code": "44054006",
                              "display": "Diabetes mellitus type 2"}]},
    }
    assert fila_condition(res, ctx)["categoria"] == "encounter-diagnosis"


# --- Inmunización: encuentro + ConceptoVacuna ---

def test_fila_immunization_encuentro_y_concepto_vacuna():
    ctx = _ctx_evento("fuente|Immunization/i1", extra_keys={"fuente|Encounter/e1"},
                      ref_to_key={"Encounter/e1": "fuente|Encounter/e1"})
    res = {
        "resourceType": "Immunization", "id": "i1", "status": "completed",
        "patient": {"reference": "Patient/p1"},
        "encounter": {"reference": "Encounter/e1"},
        "occurrenceDateTime": "2021-11-01T09:00:00Z",
        "vaccineCode": {"coding": [{"system": "http://hl7.org/fhir/sid/cvx",
                                     "code": "140", "display": "Influenza, seasonal"}]},
    }
    fila = fila_immunization(res, ctx)
    assert fila["encuentro_id"] == "fuente|Encounter/e1"
    assert fila["codigos"][0]["concepto_id"].startswith("ConceptoVacuna|")


# --- DiagnosticReport: paneles con result[], notas se omiten ---

def test_fila_diagnostic_report_panel_con_resultados():
    ctx = _ctx_evento(
        "fuente|DiagnosticReport/dr1",
        extra_keys={"fuente|Observation/o1", "fuente|Observation/o2"},
        ref_to_key={"Observation/o1": "fuente|Observation/o1",
                    "Observation/o2": "fuente|Observation/o2"})
    res = {
        "resourceType": "DiagnosticReport", "id": "dr1", "status": "final",
        "subject": {"reference": "Patient/p1"},
        "effectiveDateTime": "2023-05-05T08:00:00Z",
        "category": [{"coding": [{"code": "LAB"}]}],
        "code": {"coding": [{"system": "http://loinc.org", "code": "57698-3",
                              "display": "Lipid panel with direct LDL"}]},
        "result": [{"reference": "Observation/o1"}, {"reference": "Observation/o2"}],
    }
    fila = fila_diagnostic_report(res, ctx)
    assert fila["nombre"] == "Lipid panel with direct LDL"
    assert fila["categoria"] == "LAB"
    assert [r["dest_id"] for r in fila["resultados"]] == [
        "fuente|Observation/o1", "fuente|Observation/o2"]
    assert fila["texto_descriptivo"].startswith("Informe diagnostico:")


def test_fila_diagnostic_report_solo_notas_se_omite():
    ctx = _ctx_evento("fuente|DiagnosticReport/dr2")
    res = {
        "resourceType": "DiagnosticReport", "id": "dr2", "status": "final",
        "subject": {"reference": "Patient/p1"},
        "effectiveDateTime": "2023-05-05T08:00:00Z",
        "code": {"coding": [{"code": "34117-2", "display": "History and physical note"}]},
        "presentedForm": [{"contentType": "text/plain", "data": "..."}],
    }
    assert fila_diagnostic_report(res, ctx) is None
