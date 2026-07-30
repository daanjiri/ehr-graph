"""cargar_interacciones.py — CSV -> aristas INTERACTUA_CON entre :Farmaco (Fase 4).

Uso: uv run python cargar_interacciones.py interacciones.csv

El display RxNorm de Synthea incluye la dosis ("Warfarin 5 MG Oral Tablet"),
así que el match es CONTAINS lowercase, no igualdad exacta.
Capa de conceptos: las aristas viven entre :Farmaco, compartidas entre pacientes.
"""

import csv
import sys

from neo4j import GraphDatabase

from config import NEO4J_AUTH, NEO4J_URI


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) < 2:
        print("Uso: python cargar_interacciones.py <csv>")
        sys.exit(1)

    with open(sys.argv[1], encoding="utf-8") as fh:
        filas = list(csv.DictReader(fh))

    driver = GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)
    creadas = 0
    try:
        with driver.session() as s:
            for fila in filas:
                res = s.run("""
                    MATCH (a:Farmaco) WHERE toLower(a.nombre_generico) CONTAINS toLower($fa)
                    MATCH (b:Farmaco) WHERE toLower(b.nombre_generico) CONTAINS toLower($fb)
                    MERGE (a)-[r:INTERACTUA_CON]->(b)
                    SET r.severidad = $sev, r.descripcion = $desc
                    RETURN a.nombre_generico AS a, b.nombre_generico AS b
                """, fa=fila["farmaco_a"], fb=fila["farmaco_b"],
                    sev=fila["severidad"], desc=fila["descripcion"]).data()
                if res:
                    creadas += len(res)
                    for r in res:
                        print(f"  OK  {r['a']}  <->  {r['b']}  [{fila['severidad']}]")
                else:
                    print(f"  --  sin match en el grafo: {fila['farmaco_a']} / "
                          f"{fila['farmaco_b']} (ninguno de los dos, o falta uno)")
    finally:
        driver.close()
    print(f"\n{creadas} aristas INTERACTUA_CON creadas/actualizadas "
          f"de {len(filas)} filas del CSV.")


if __name__ == "__main__":
    main()
