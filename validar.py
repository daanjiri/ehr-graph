"""validar.py — criterios de aceptación automatizados V1–V10 (PLAN.md §11).

Uso:
  uv run python validar.py             # V1–V10 completo
  uv run python validar.py --fase 1    # solo V1–V7 (antes de semantica.py)
  uv run python validar.py --fase 4    # V1–V10 + query de farmacovigilancia

Sale con código != 0 si alguna verificación falla.
Imprime counts por label (útil para comparar antes/después de una re-ingesta).
"""

import sys
import time

from neo4j import GraphDatabase

NEO4J_URI = "bolt://localhost:7687"
NEO4J_AUTH = ("neo4j", "password123")

resultados = []


def check(nombre, ok, detalle=""):
    resultados.append(ok)
    estado = "OK " if ok else "FALLO"
    print(f"  [{estado}] {nombre}  {detalle}")


def uno(s, cypher, **params):
    return s.run(cypher, **params).single()[0]


def counts_por_label(s):
    print("\n=== Counts por label ===")
    filas = s.run("""
        MATCH (n) UNWIND labels(n) AS l
        RETURN l, count(*) AS n ORDER BY l
    """).data()
    for f in filas:
        print(f"  {f['l']:24s} {f['n']:>8d}")
    rels = s.run("MATCH ()-[r]->() RETURN type(r) AS t, count(*) AS n ORDER BY t").data()
    print("=== Counts por relación ===")
    for f in rels:
        print(f"  {f['t']:24s} {f['n']:>8d}")


def validar_fase1(s):
    n_pac = uno(s, "MATCH (p:Paciente) RETURN count(p)")
    check("V1  count(:Paciente) >= 10", n_pac >= 10, f"({n_pac})")

    n_ev = uno(s, "MATCH (e:Evento) RETURN count(e)")
    check("V2  count(:Evento) > 500", n_ev > 500, f"({n_ev})")

    sin_props = uno(s, """
        MATCH (e:Evento)
        WHERE e.paciente_id IS NULL OR e.fecha_registro IS NULL
        RETURN count(e)
    """)
    check("V3  todo :Evento tiene paciente_id y fecha_registro", sin_props == 0,
          f"({sin_props} sin props)")

    con_fecha = uno(s, "MATCH (e:Evento) WHERE e.fecha_efectiva IS NOT NULL RETURN count(e)")
    pct = 100 * con_fecha / n_ev if n_ev else 0
    check("V4  >95% de :Evento con fecha_efectiva", pct > 95, f"({pct:.1f}%)")

    n_farmacos = uno(s, "MATCH (f:Farmaco) RETURN count(f)")
    n_rx = uno(s, "MATCH (r:Prescripcion) RETURN count(r)")
    check("V5  count(:Farmaco) < count(:Prescripcion) [dedup]",
          0 < n_farmacos < n_rx, f"({n_farmacos} farmacos, {n_rx} rx)")

    n_trata = uno(s, "MATCH ()-[t:TRATA {fuente:'explicita'}]->() RETURN count(t)")
    check("V6  existe TRATA con fuente='explicita'", n_trata > 0, f"({n_trata})")

    pid = s.run("MATCH (e:Evento) RETURN e.paciente_id AS p LIMIT 1").single()["p"]
    q7 = """
        MATCH (e:Evento {paciente_id: $pid})
        WHERE e.fecha_efectiva IS NOT NULL
        RETURN e.id, e.fecha_efectiva ORDER BY e.fecha_efectiva LIMIT 100
    """
    list(s.run(q7, pid=pid))            # 1ª ejecución: compila + calienta page cache
    t0 = time.perf_counter()
    list(s.run(q7, pid=pid))            # medir la 2ª
    ms = (time.perf_counter() - t0) * 1000
    check("V7  timeline < 200ms (2a ejecucion)", ms < 200, f"({ms:.0f} ms)")


def validar_fase2(s):
    s.run("CALL db.awaitIndexes()")
    con_emb = uno(s, "MATCH (e:Evento) WHERE e.embedding IS NOT NULL RETURN count(e)")
    con_txt = uno(s, "MATCH (e:Evento) WHERE e.texto_descriptivo IS NOT NULL RETURN count(e)")
    check("V8  embeddings == eventos con texto", con_emb == con_txt,
          f"({con_emb} embeddings / {con_txt} con texto)")

    from semantica import buscar_semantico
    hits = buscar_semantico("heart problems", k=5)
    ok = len(hits) > 0 and hits[0]["score"] > 0.3
    detalle = f"({len(hits)} hits, top={hits[0]['score']:.3f})" if hits else "(0 hits)"
    check("V9  buscar_semantico('heart problems') con score > 0.3", ok, detalle)


def validar_v10(s):
    # Paciente con prescripciones y fechas; X = punto medio de su historia
    fila = s.run("""
        MATCH (rx:Prescripcion)
        WHERE rx.fecha_inicio IS NOT NULL
        WITH rx.paciente_id AS pid, count(*) AS n, min(rx.fecha_inicio) AS lo,
             max(rx.fecha_inicio) AS hi
        WHERE n >= 3 ORDER BY n DESC LIMIT 1
        RETURN pid, lo + duration.between(lo, hi) / 2 AS x
    """).single()
    if not fila:
        check("V10 query de intervalo (medicacion activa en fecha X)", False,
              "(ningun paciente con >=3 rx)")
        return
    filas = s.run("""
        MATCH (rx:Prescripcion {paciente_id: $pid})
        WHERE rx.fecha_inicio <= $x AND (rx.fecha_fin IS NULL OR rx.fecha_fin >= $x)
        RETURN rx.fecha_inicio AS ini, rx.fecha_fin AS fin
    """, pid=fila["pid"], x=fila["x"]).data()
    ok = len(filas) > 0 and all(
        f["ini"] <= fila["x"] and (f["fin"] is None or f["fin"] >= fila["x"])
        for f in filas)
    check("V10 query de intervalo (medicacion activa en fecha X)", ok,
          f"({len(filas)} rx vigentes a {str(fila['x'])[:10]})")


def validar_fase4(s):
    filas = s.run("""
        MATCH (p:Paciente)<-[:DE_PACIENTE]-(rx1:Prescripcion {estado:'active'})-[:DE_FARMACO]->(f1:Farmaco)
        MATCH (p)<-[:DE_PACIENTE]-(rx2:Prescripcion {estado:'active'})-[:DE_FARMACO]->(f2:Farmaco)
        MATCH (f1)-[i:INTERACTUA_CON]->(f2)
        RETURN DISTINCT p.nombre AS paciente, f1.nombre_generico AS farmaco_a,
               f2.nombre_generico AS farmaco_b, i.severidad AS severidad,
               i.descripcion AS descripcion
    """).data()
    check("F4  pacientes con rx activas cuyos farmacos interactuan", len(filas) > 0,
          f"({len(filas)} combinaciones)")
    for f in filas[:10]:
        print(f"       {f['paciente']}: {f['farmaco_a']} + {f['farmaco_b']}"
              f" [{f['severidad']}] {f['descripcion']}")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    fase = None
    if "--fase" in sys.argv:
        fase = sys.argv[sys.argv.index("--fase") + 1]

    driver = GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)
    try:
        driver.verify_connectivity()
        with driver.session() as s:
            print("=== Validación ===")
            validar_fase1(s)
            if fase != "1":
                validar_fase2(s)
                validar_v10(s)
            if fase == "4":
                validar_fase4(s)
            counts_por_label(s)
    finally:
        driver.close()

    fallos = resultados.count(False)
    print(f"\n{len(resultados) - fallos}/{len(resultados)} verificaciones OK")
    sys.exit(1 if fallos else 0)


if __name__ == "__main__":
    main()
