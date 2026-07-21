"""Unit tests de los helpers puros de api/eventos.py — sin BD ni red."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from api.eventos import bins_mensuales, extraer_nodo_ids, recortar_historial, sse


# --- sse ---

def test_sse_formato():
    s = sse("texto", {"delta": "hola"})
    assert s == 'event: texto\ndata: {"delta": "hola"}\n\n'


def test_sse_sin_escapar_unicode():
    s = sse("texto", {"delta": "presión"})
    assert "presión" in s  # ensure_ascii=False


def test_sse_data_parseable():
    s = sse("fin", {"nodo_ids": ["a", "b"]})
    linea_data = [l for l in s.split("\n") if l.startswith("data: ")][0]
    assert json.loads(linea_data[6:]) == {"nodo_ids": ["a", "b"]}


# --- extraer_nodo_ids ---

def test_extraer_ids_de_salida():
    salida = [{"id": "n1", "texto": "x"}, {"id": "n2"}]
    assert extraer_nodo_ids("buscar_semantico", {"pregunta": "q"}, salida) == ["n1", "n2"]


def test_extraer_incluye_nodo_id_de_entrada():
    salida = [{"id": "n2"}]
    ids = extraer_nodo_ids("expandir_contexto", {"nodo_id": "n1"}, salida)
    assert ids == ["n2", "n1"]


def test_extraer_dedup_preserva_orden():
    salida = [{"id": "a"}, {"id": "b"}, {"id": "a"}]
    assert extraer_nodo_ids("timeline", {"paciente_id": "p"}, salida) == ["a", "b"]


def test_extraer_salida_vacia_o_rara():
    assert extraer_nodo_ids("cadena_causal", {"nodo_id": "n1"}, []) == ["n1"]
    assert extraer_nodo_ids("timeline", {}, "no es lista") == []
    assert extraer_nodo_ids("timeline", {}, [{"sin_id": 1}, "str"]) == []


def test_extraer_ignora_listar_pacientes():
    salida = [{"id": "paciente-1"}]
    assert extraer_nodo_ids("listar_pacientes", {}, salida) == []


# --- bins_mensuales ---

def test_bins_agrupa_por_mes_y_tipo():
    filas = [
        {"tipo": "Observacion", "fecha": "2021-03-14T09:00:00Z"},
        {"tipo": "Observacion", "fecha": "2021-03-20T10:00:00Z"},
        {"tipo": "Procedimiento", "fecha": "2021-03-14T09:00:00Z"},
        {"tipo": "Observacion", "fecha": "2021-04-01T00:00:00Z"},
    ]
    assert bins_mensuales(filas) == [
        {"mes": "2021-03", "tipo": "Observacion", "n": 2},
        {"mes": "2021-03", "tipo": "Procedimiento", "n": 1},
        {"mes": "2021-04", "tipo": "Observacion", "n": 1},
    ]


def test_bins_ignora_sin_fecha():
    filas = [{"tipo": "Observacion", "fecha": None}, {"tipo": "Alergia"}]
    assert bins_mensuales(filas) == []


def test_bins_orden_por_mes():
    filas = [
        {"tipo": "Observacion", "fecha": "2022-01-01T00:00:00Z"},
        {"tipo": "Observacion", "fecha": "2019-12-31T23:59:59Z"},
    ]
    meses = [b["mes"] for b in bins_mensuales(filas)]
    assert meses == ["2019-12", "2022-01"]


def test_bins_vacio():
    assert bins_mensuales([]) == []


# --- recortar_historial ---

def _intercambio(n, con_tools=False):
    """Un intercambio: user texto -> [assistant tool_use -> user tool_results] -> assistant."""
    msgs = [{"role": "user", "content": f"pregunta {n}"}]
    if con_tools:
        msgs.append({"role": "assistant", "content": [{"type": "tool_use", "id": f"t{n}"}]})
        msgs.append({"role": "user", "content": [{"type": "tool_result", "tool_use_id": f"t{n}"}]})
    msgs.append({"role": "assistant", "content": f"respuesta {n}"})
    return msgs


def test_recortar_historial_corto_intacto():
    mensajes = _intercambio(1) + _intercambio(2)
    assert recortar_historial(mensajes, max_intercambios=10) is mensajes


def test_recortar_conserva_ultimos_n():
    mensajes = []
    for i in range(5):
        mensajes += _intercambio(i)
    recortado = recortar_historial(mensajes, max_intercambios=2)
    assert recortado[0] == {"role": "user", "content": "pregunta 3"}
    assert len(recortado) == 4


def test_recortar_no_parte_pares_tool():
    mensajes = _intercambio(1, con_tools=True) + _intercambio(2, con_tools=True)
    recortado = recortar_historial(mensajes, max_intercambios=1)
    # Empieza en el user de TEXTO del intercambio 2, no en su user de tool_results
    assert recortado[0] == {"role": "user", "content": "pregunta 2"}
    # El par tool_use/tool_result del intercambio 2 queda completo
    tipos = [m["content"][0]["type"] for m in recortado
             if isinstance(m["content"], list)]
    assert tipos == ["tool_use", "tool_result"]
