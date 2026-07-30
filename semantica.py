"""semantica.py — texto_descriptivo -> embeddings -> índice vectorial (PLAN.md §9).

Uso:
  uv run python semantica.py                    # crea índice + indexa lo pendiente
  uv run python semantica.py "heart problems"   # búsqueda de prueba con scores

Idempotente: solo procesa :Evento con embedding IS NULL y texto_descriptivo
no nulo — correr después de cada ingesta solo procesa lo nuevo.
"""

import sys

from neo4j import GraphDatabase

from config import NEO4J_AUTH, NEO4J_URI

# No cambiar sin actualizar la dimensión del índice vectorial (CLAUDE.md)
MODELO = "paraphrase-multilingual-MiniLM-L12-v2"
DIMENSIONES = 384
BATCH = 256

_modelo = None


def modelo():
    """Carga perezosa: importar este módulo no debe descargar el modelo."""
    global _modelo
    if _modelo is None:
        from sentence_transformers import SentenceTransformer
        _modelo = SentenceTransformer(MODELO)
    return _modelo


def crear_indice(driver):
    with driver.session() as s:
        s.run(f"""
            CREATE VECTOR INDEX evento_embedding IF NOT EXISTS
            FOR (e:Evento) ON e.embedding
            OPTIONS {{indexConfig: {{
                `vector.dimensions`: {DIMENSIONES},
                `vector.similarity_function`: 'cosine'
            }}}}
        """)
        s.run("CALL db.awaitIndexes()")  # el índice vectorial es asíncrono


def indexar(driver):
    """Loop batcheado: embebe eventos pendientes y escribe con setNodeVectorProperty."""
    total = 0
    with driver.session() as s:
        while True:
            pendientes = s.run("""
                MATCH (e:Evento)
                WHERE e.embedding IS NULL AND e.texto_descriptivo IS NOT NULL
                RETURN e.id AS id, e.texto_descriptivo AS texto
                LIMIT $batch
            """, batch=BATCH).data()
            if not pendientes:
                break
            vectores = modelo().encode([p["texto"] for p in pendientes],
                                       show_progress_bar=False)
            filas = [{"id": p["id"], "vec": v.tolist()}
                     for p, v in zip(pendientes, vectores)]
            s.run("""
                UNWIND $filas AS f
                MATCH (e:Evento {id: f.id})
                CALL db.create.setNodeVectorProperty(e, 'embedding', f.vec)
            """, filas=filas)
            total += len(filas)
            print(f"  indexados {total}...")
    return total


def buscar_semantico(pregunta, k=5, paciente_id=None, driver=None):
    """Anclaje difuso por vector. Con paciente_id: pide k*10 y post-filtra."""
    propio = driver is None
    if propio:
        driver = GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)
    try:
        vec = modelo().encode(pregunta).tolist()
        k_query = k * 10 if paciente_id else k
        with driver.session() as s:
            s.run("CALL db.awaitIndexes()")
            filas = s.run("""
                CALL db.index.vector.queryNodes('evento_embedding', $k, $vec)
                YIELD node, score
                RETURN node.id AS id, labels(node) AS labels,
                       node.texto_descriptivo AS texto,
                       node.paciente_id AS paciente_id,
                       toString(node.fecha_efectiva) AS fecha, score
            """, k=k_query, vec=vec).data()
        if paciente_id:
            filas = [f for f in filas if f["paciente_id"] == paciente_id][:k]
        return filas
    finally:
        if propio:
            driver.close()


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    driver = GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)
    try:
        driver.verify_connectivity()
        if len(sys.argv) > 1:
            pregunta = " ".join(sys.argv[1:])
            print(f'Busqueda: "{pregunta}"\n')
            for f in buscar_semantico(pregunta, driver=driver):
                etiquetas = [l for l in f["labels"] if l != "Evento"]
                print(f"  {f['score']:.3f}  [{'/'.join(etiquetas)}] {f['texto']}"
                      f"  (paciente {f['paciente_id'][:8]}...)")
        else:
            crear_indice(driver)
            n = indexar(driver)
            print(f"Indexado completo: {n} eventos nuevos con embedding.")
    finally:
        driver.close()


if __name__ == "__main__":
    main()
