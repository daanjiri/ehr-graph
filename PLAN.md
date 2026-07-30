# PLAN.md — Knowledge Graph Clínico Multi-Paciente (GraphRAG sobre FHIR)

> **Instrucción para Claude Code**: este documento es la especificación completa del
> proyecto. Impleméntalo por fases, en orden. Cada fase tiene criterios de aceptación:
> no avances a la siguiente sin cumplirlos. Lee también CLAUDE.md (convenciones).

---

## 1. LA IDEA

Construir un "second brain" clínico: las historias clínicas electrónicas (EHR) de
muchos pacientes, en formato FHIR, se traducen a un **knowledge graph en Neo4j** que
una IA puede recorrer para responder preguntas clínicas con trazabilidad total.

Principios de diseño (no negociables):

1. **Reificación de eventos**: cada hecho clínico (diagnóstico, prescripción,
   cirugía, laboratorio) es un NODO con fechas y estado — nunca una arista directa
   tipo `(Paciente)-[TIENE]->(Diabetes)`, porque eso pierde el cuándo, quién y por qué.
2. **Dos capas**: *instancias* (los datos de cada paciente) y *conceptos*
   (terminología SNOMED/RxNorm/LOINC compartida entre TODOS los pacientes).
   La metformina de Juan y la de María apuntan al mismo nodo `:Farmaco` →
   habilita cohortes, farmacovigilancia e interacciones.
3. **Aristas causales con gobernanza**: relaciones TRATA / INDICADO_POR /
   MOTIVO_SUSPENSION_DE llevan `{confianza, fuente}` para distinguir lo que un
   médico afirmó (`explicita`) de lo que un pipeline infirió (`inferida-NLP`).
4. **Tiempo por índices, no por nodos de fecha**: propiedades datetime
   normalizadas + índices compuestos. (Decisión tomada: NO implementar nodos
   `:Dia` estilo Schifman; son aditivos y se pueden agregar después.)
5. **Retrieval en pinza (GraphRAG)**: índice vectorial para *anclar* (búsqueda
   difusa), travesía de aristas para *traer contexto*, LLM para *sintetizar*
   citando nodos. El agente usa herramientas de travesía FIJA, no text-to-Cypher
   libre (seguridad en contexto clínico).

## 2. STACK

- **Neo4j 5.26** (Docker local) — property graph + índice vectorial nativo
- **Python 3.10+**: `neo4j`, `sentence-transformers`, `anthropic`
- **Synthea** (jar de GitHub releases) — pacientes sintéticos FHIR R4, ya
  codificados con SNOMED/RxNorm/LOINC. NUNCA datos reales en este proyecto.
- **Embeddings**: `paraphrase-multilingual-MiniLM-L12-v2` (384 dims, CPU;
  multilingüe porque las preguntas serán en español y los datos Synthea en inglés)
- **LLM del agente**: configurable vía `ANTHROPIC_MODEL`; producción pública
  usa el snapshot `claude-haiku-4-5-20251001` por costo, estabilidad y tool use.
  Docs: https://docs.claude.com/en/api/overview

## 3. ESTRUCTURA DE ARCHIVOS OBJETIVO

```
ehr-graph/
├── PLAN.md                    # este documento
├── CLAUDE.md                  # convenciones del proyecto
├── docker-compose.yml         # Neo4j 5.26
├── requirements.txt
├── schema.cypher              # constraints e índices (fuente de verdad del DDL)
├── ingest.py                  # FHIR bundles → grafo (esquema v2)
├── semantica.py               # texto_descriptivo → embeddings → índice vectorial
├── agente.py                  # herramientas de travesía + loop tool-use con Claude
├── cargar_interacciones.py    # CSV → aristas INTERACTUA_CON (capa conceptos)
├── validar.py                 # queries de aceptación automatizadas
└── tests/
    └── test_ingest.py         # unit tests de utilidades (fechas, refs, codings)
```

---

## 4. MODELO DE DATOS — NODOS

### 4.1 Capa de instancias

Todo nodo de evento clínico lleva **doble label** `:Tipo:Evento` y estas
propiedades comunes obligatorias:

| Propiedad común | Tipo | Regla |
|---|---|---|
| `id` | string | id del recurso FHIR; UNIQUE global sobre :Evento |
| `fecha_efectiva` | datetime | cuándo ocurrió clínicamente, SIEMPRE UTC (ver §6) |
| `fecha_registro` | datetime | now() al ingerir (bitemporalidad ligera) |
| `paciente_id` | string | denormalizado (además de la arista) — ver §7 |
| `texto_descriptivo` | string | frase en lenguaje natural por plantilla (ver §9.1) |
| `embedding` | float[384] | lo escribe semantica.py, null al ingerir |

Nodos y sus propiedades específicas:

**`:Paciente`** (NO lleva :Evento)
- id (UNIQUE), nombre, sexo (`male|female|other|unknown`), fecha_nacimiento (date),
  fallecido (bool), fecha_fallecimiento (datetime|null)
- Demografía US Core / cohortes: mrn (identifier tipo MR; SSN/licencias NO se
  ingieren), raza, etnia, sexo_nacimiento (extensiones US Core), ciudad,
  estado_region, pais (address[0]), estado_civil

**`:Encuentro:Evento`** — el hub temporal
- tipo (display del coding: ambulatorio/urgencias/hospitalización...),
  clase_codigo (v3-ActCode crudo: AMB/EMER/IMP...),
  fecha_inicio (datetime), fecha_fin (datetime|null), motivo_consulta (string)

**`:Condicion:Evento`**
- nombre (display SNOMED), estado_clinico (`active|recurrence|remission|resolved`),
  estado_verificacion (`unconfirmed|provisional|confirmed|refuted`),
  categoria (`encounter-diagnosis|problem-list-item`|null),
  fecha_inicio (inicio clínico), fecha_resolucion (datetime|null),
  severidad (string|null), es_cronica (bool|null)

**`:Prescripcion:Evento`**
- estado (`active|stopped|completed|on-hold`), fecha_inicio, fecha_fin (null si activa),
  dosis_texto (texto libre FHIR), dosis_valor (number|null), dosis_unidad,
  via (string|null), frecuencia (string|null), motivo_suspension (string|null),
  es_PRN (bool|null)

**`:Procedimiento:Evento`**
- nombre, estado (`completed|in-progress|stopped`), fecha, duracion_min (null),
  resultado (string|null), urgente (bool|null)

**`:Observacion:Evento`**
- nombre (display LOINC), valor (number|string), unidad (string, UCUM),
  categoria (`laboratory|vital-signs|survey|social-history|procedure`|null —
  gobierna el prefijo del texto_descriptivo: un survey NO es "Lab"),
  estado (`final|preliminary|amended`...), fecha (momento de la toma),
  rango_ref_min/max (number|null), interpretacion (`normal|high|low|critical`|null)

**`:InformeDiagnostico:Evento`** — panel de laboratorio (DiagnosticReport con result[])
- nombre (display LOINC del panel), estado (status), categoria (LAB...).
  Solo se ingieren los DiagnosticReport con `result[]`; los de solo notas
  (`presentedForm`) se omiten y se cuentan en el resumen de la ingesta.

**`:Alergia:Evento`**
- tipo (`allergy|intolerance`), criticidad (`low|high|unable-to-assess`),
  reaccion (string|null), estado (`active|inactive|refuted`),
  estado_verificacion (`unconfirmed|confirmed|refuted`|null)

**`:Inmunizacion:Evento`**
- nombre, fecha, dosis_numero (int|null), lote (string|null), estado

**`:Profesional`**, **`:Institucion`** (sin :Evento)
- id, nombre, especialidad / tipo. Poblar solo si Synthea los referencia; baja prioridad.

### 4.2 Capa de conceptos (compartida, deduplicada, SIN :Evento, SIN paciente_id)

| Nodo | Clave UNIQUE | Propiedades |
|---|---|---|
| `:ConceptoDiagnostico` | codigo (SNOMED) | nombre, sistema |
| `:Farmaco` | codigo (RxNorm) | nombre_generico, sistema |
| `:ConceptoLab` | codigo (LOINC) | nombre, sistema |
| `:ConceptoProcedimiento` | codigo (SNOMED) | nombre |
| `:ConceptoVacuna` | codigo (CVX) | nombre |
| `:Sustancia` | codigo | nombre (para alergias) |

(La clave real de todos los conceptos es la compuesta `(sistema, codigo)` —
identidad de un Coding FHIR; ver schema.cypher.)

Relaciones DENTRO de la capa de conceptos (fase 6, opcional):
- `(:ConceptoDiagnostico)-[:ES_UN]->(:ConceptoDiagnostico)` — jerarquía SNOMED
- `(:Farmaco)-[:INTERACTUA_CON {severidad, descripcion}]->(:Farmaco)`
- `(:Farmaco)-[:CONTRAINDICADO_EN]->(:ConceptoDiagnostico)`

---

## 5. MODELO DE DATOS — ARISTAS

### 5.1 Estructurales (obligatorias en la ingesta)

| Arista | Desde → Hacia | Fuente FHIR |
|---|---|---|
| `DE_PACIENTE` | todo :Evento → :Paciente | `subject`/`patient` reference |
| `REGISTRADA_EN` | :Condicion → :Encuentro | `encounter` |
| `PRESCRITA_EN` | :Prescripcion → :Encuentro | `encounter` |
| `REALIZADO_EN` | :Procedimiento → :Encuentro | `encounter` |
| `TOMADA_EN` | :Observacion → :Encuentro | `encounter` |
| `APLICADA_EN` | :Inmunizacion → :Encuentro | `encounter` |
| `EMITIDO_EN` | :InformeDiagnostico → :Encuentro | `encounter` |
| `INCLUYE_RESULTADO` | :InformeDiagnostico → :Observacion | `result[]` (con `fhir_path`) |

### 5.2 Vínculo a conceptos (obligatorias)

| Arista | Desde → Hacia | Fuente FHIR |
|---|---|---|
| `CODIFICADA_COMO` | :Condicion → :ConceptoDiagnostico | `code.coding[0]` |
| `DE_FARMACO` | :Prescripcion → :Farmaco | `medicationCodeableConcept.coding[0]` |
| `MIDE` | :Observacion → :ConceptoLab | `code.coding[0]` |
| `TIPO` | :Procedimiento → :ConceptoProcedimiento | `code.coding[0]` |
| `DE_VACUNA` | :Inmunizacion → :ConceptoVacuna | `vaccineCode` (CVX) |
| `TIPO_PANEL` | :InformeDiagnostico → :ConceptoLab | `code` (LOINC del panel) |
| `A_SUSTANCIA` | :Alergia → :Sustancia | `code.coding[0]` |

### 5.3 Causales (el corazón del grafo)

Todas llevan propiedades `{fuente: 'explicita'|'inferida-NLP'|'inferida-temporal',
confianza: float 0–1}`. En la ingesta desde FHIR: siempre `explicita, 1.0`.

| Arista | Desde → Hacia | Fuente FHIR en ingesta |
|---|---|---|
| `TRATA` | :Prescripcion → :Condicion | `reasonReference` |
| `INDICADO_POR` | :Procedimiento → :Condicion | `reasonReference` |
| `EVIDENCIA_DE` | :Observacion → :Condicion | (no viene en Synthea; fase NLP) |
| `COMPLICACION_DE` | :Condicion → :Condicion\|:Procedimiento | (fase NLP) |
| `MOTIVO_SUSPENSION_DE` | :Observacion → :Prescripcion | (fase NLP) |
| `REEMPLAZA_A` | :Prescripcion → :Prescripcion | (fase NLP / heurística temporal) |
| `MONITOREA` | :Observacion → :Prescripcion | (fase NLP) |

---

## 6. REGLAS TEMPORALES (arquitectura v2)

`fecha_efectiva` se calcula en la ingesta según esta tabla (primer campo no nulo):

| Nodo | fecha_efectiva = | fallback |
|---|---|---|
| Encuentro | `period.start` | — |
| Condicion | `onsetDateTime` | `recordedDate` |
| Prescripcion | `authoredOn` | fecha del encuentro |
| Procedimiento | `performedPeriod.start` | `performedDateTime` |
| Observacion | `effectiveDateTime` | `issued` |
| InformeDiagnostico | `effectiveDateTime` | `issued` |
| Inmunizacion | `occurrenceDateTime` | — |
| Alergia | `recordedDate` | — |

Reglas estrictas:
- Tipo `datetime()` de Neo4j, nunca string. Fechas sin hora → completar T00:00:00.
- Normalizar TODO a UTC en la ingesta. Convertir a local solo al mostrar.
- Sin ninguna fecha → `fecha_efectiva = null` + flag `fecha_desconocida: true`. NUNCA inventar.
- "Medicación activa en fecha X" es una query de INTERVALO, no de punto:
  `fecha_inicio <= X AND (fecha_fin IS NULL OR fecha_fin >= X)`.

## 7. DDL — schema.cypher (fuente de verdad)

```cypher
// Constraints
CREATE CONSTRAINT paciente_id IF NOT EXISTS FOR (p:Paciente) REQUIRE p.id IS UNIQUE;
CREATE CONSTRAINT evento_id   IF NOT EXISTS FOR (e:Evento)   REQUIRE e.id IS UNIQUE;
CREATE CONSTRAINT snomed  IF NOT EXISTS FOR (c:ConceptoDiagnostico)   REQUIRE c.codigo IS UNIQUE;
CREATE CONSTRAINT rxnorm  IF NOT EXISTS FOR (f:Farmaco)              REQUIRE f.codigo IS UNIQUE;
CREATE CONSTRAINT loinc   IF NOT EXISTS FOR (l:ConceptoLab)           REQUIRE l.codigo IS UNIQUE;
CREATE CONSTRAINT cproc   IF NOT EXISTS FOR (c:ConceptoProcedimiento) REQUIRE c.codigo IS UNIQUE;

// Índices temporales — el compuesto es el MÁS importante del sistema:
// hace que "timeline de paciente X" sea lookup puro de índice sin travesía.
// Por eso paciente_id se denormaliza como propiedad (duplicación intencional).
CREATE INDEX evento_fecha     IF NOT EXISTS FOR (e:Evento) ON (e.fecha_efectiva);
CREATE INDEX evento_pac_fecha IF NOT EXISTS FOR (e:Evento) ON (e.paciente_id, e.fecha_efectiva);

// Índices de estado
CREATE INDEX rx_estado   IF NOT EXISTS FOR (r:Prescripcion) ON (r.estado);
CREATE INDEX cond_estado IF NOT EXISTS FOR (c:Condicion)    ON (c.estado_clinico);

// Índice vectorial (lo crea semantica.py, aquí como referencia)
// CREATE VECTOR INDEX evento_embedding IF NOT EXISTS FOR (e:Evento) ON e.embedding
// OPTIONS {indexConfig: {`vector.dimensions`: 384, `vector.similarity_function`: 'cosine'}};
```

## 8. ESPECIFICACIÓN DE ingest.py

- Entrada: directorio con bundles JSON de Synthea (excluir archivos
  `hospitalInformation*.json` y `practitionerInformation*.json`).
- Los bundles de Synthea usan `fullUrl: "urn:uuid:..."` y las referencias internas
  son `{"reference": "urn:uuid:..."}`. Construir mapa fullUrl→id ANTES de procesar.
- Un handler por resourceType (Patient, Encounter, Condition, MedicationRequest,
  Procedure, Observation, AllergyIntolerance, Immunization), separados para que
  los errores queden localizados por tipo.
- **Todo con MERGE por id** — idempotente y re-ejecutable (base del sync incremental).
- Capa de conceptos: `MERGE` del concepto por código + `ON CREATE SET` nombre/sistema.
- `reasonReference` → aristas TRATA / INDICADO_POR con `{fuente:'explicita', confianza:1.0}`.
- Al final: imprimir conteo de nodos ingeridos por tipo.
- Performance: si con 50 pacientes tarda >5 min, batchear con UNWIND por tipo.

### 9.1 Plantillas de texto_descriptivo (en español, datos en inglés OK)

| Nodo | Plantilla |
|---|---|
| Encuentro | `"Encuentro clinico ({tipo}) el {fecha}."` |
| Condicion | `"Diagnostico: {nombre} ({estado}), inicio {fecha}."` |
| Prescripcion | `"Prescripcion de {farmaco} ({estado}), iniciada {fecha}. {dosis_texto}"` |
| Procedimiento | `"Procedimiento: {nombre} realizado el {fecha}."` |
| Observacion | `"Lab/medicion: {nombre} = {valor} {unidad} el {fecha}."` |

## 9. ESPECIFICACIÓN DE semantica.py

1. `CREATE VECTOR INDEX evento_embedding` (384 dims, cosine).
2. Loop batcheado (256): busca `:Evento` con `embedding IS NULL AND
   texto_descriptivo IS NOT NULL`, embebe, escribe con
   `db.create.setNodeVectorProperty(e, 'embedding', $vec)`. Idempotente:
   correr después de cada ingesta solo procesa lo nuevo.
3. `buscar_semantico(pregunta, k=5, paciente_id=None)`: embebe la pregunta,
   `CALL db.index.vector.queryNodes('evento_embedding', k, $vec)`. Si hay
   paciente_id: pedir k*10 y post-filtrar por `node.paciente_id`.
4. CLI: sin args indexa; con arg hace búsqueda de prueba e imprime scores.

## 10. ESPECIFICACIÓN DE agente.py (patrón pinza)

Herramientas expuestas al LLM vía tool use (travesías fijas, NO Cypher libre):

| Herramienta | Firma | Qué hace |
|---|---|---|
| `buscar_semantico` | (pregunta, paciente_id?, k=5) | anclaje difuso por vector |
| `timeline` | (paciente_id, desde?, hasta?, limite=30) | cronología vía índice compuesto |
| `expandir_contexto` | (nodo_id, saltos=1, max 3) | vecinos con tipo de relación |
| `cadena_causal` | (nodo_id) | causas y efectos vía aristas causales, 1..3 saltos |
| `medicacion_activa` | (paciente_id) | rx vigentes + qué condición trata cada una |
| `listar_pacientes` | (limite=10) | ids y nombres disponibles |

System prompt del agente (usar tal cual la esencia): responder SOLO con datos del
grafo; estrategia anclar→expandir→sintetizar; citar fechas y valores exactos; si
el grafo no contiene la respuesta, decirlo; nunca inventar datos clínicos;
aclarar que son datos sintéticos.

Loop: `client.messages.create(model=ANTHROPIC_MODEL, tools=TOOLS, ...)`;
mientras `stop_reason == "tool_use"`, ejecutar herramientas y devolver
tool_result; sin `ANTHROPIC_API_KEY`, modo demo: listar pacientes + timeline +
medicación activa del primero.

## 11. ESPECIFICACIÓN DE validar.py (criterios de aceptación automatizados)

Debe correr estas verificaciones y salir con código ≠0 si alguna falla:

```
V1  count(:Paciente) >= 10
V2  count(:Evento) > 500  (con 50 pacientes Synthea)
V3  Todo :Evento tiene paciente_id y fecha_registro
V4  >95% de :Evento tiene fecha_efectiva no nula
V5  count(:Farmaco) < count(:Prescripcion)  → prueba que la capa de
    conceptos deduplica entre pacientes
V6  Existe al menos una arista TRATA con fuente='explicita'
V7  Timeline: MATCH (e:Evento {paciente_id:$pid}) ... ORDER BY fecha_efectiva
    devuelve resultados para un paciente cualquiera en < 200ms
V8  (tras semantica.py) count(:Evento donde embedding IS NOT NULL) == count con texto
V9  buscar_semantico("heart problems") devuelve >0 resultados con score > 0.3
V10 Query de intervalo: medicación activa a mitad de la historia de un
    paciente devuelve solo rx con fecha_inicio <= X y (fin null o >= X)
V11 >95% de :Observacion tiene categoria (laboratory/vital-signs/survey/...)
V12 >95% de :Inmunizacion tiene arista APLICADA_EN a su Encuentro
V13 count(:ConceptoVacuna) > 0 y ninguna :Inmunizacion apunta a
    :ConceptoProcedimiento (las vacunas dejaron de colarse ahí)
V14 count(:InformeDiagnostico) > 0 y todos tienen >=1 INCLUYE_RESULTADO
V15 >90% de :Paciente tiene mrn y raza (demografía US Core ingerida)
```

---

## 12. FASES DE IMPLEMENTACIÓN (en orden, con aceptación)

**Fase 0 — Infraestructura**
- docker-compose.yml (neo4j:5.26, puertos 7474/7687, AUTH neo4j/password123,
  heap 2G, volumen ./neo4j_data), requirements.txt, descargar Synthea jar,
  generar 50 pacientes (`java -jar synthea-with-dependencies.jar -p 50`).
- ✓ Aceptación: Neo4j responde en :7474; existen ~50 bundles en ./output/fhir.

**Fase 1 — Esquema e ingesta**
- schema.cypher + ingest.py completo según §8, aplicando §4–§7.
- Unit tests de utilidades: norm_dt (los 3 casos: solo fecha, con TZ, None),
  resolución de referencias urn:uuid y Tipo/id, extracción de codings.
- ✓ Aceptación: V1–V7 de validar.py en verde. Re-ejecutar ingest.py NO duplica
  nodos (mismo count antes y después).

**Fase 2 — Capa semántica**
- semantica.py según §9.
- ✓ Aceptación: V8–V9 en verde; búsqueda "colonoscopy" y "examen del colon"
  encuentran los mismos nodos top.

**Fase 3 — Agente**
- agente.py según §10.
- ✓ Aceptación: en modo demo imprime timeline coherente; con API key responde
  "¿qué medicamentos toma X y para qué?" citando fechas del grafo, y responde
  "no está en el grafo" ante una pregunta sin datos (probar con algo inventado).

**Fase 4 — Farmacovigilancia**
- cargar_interacciones.py: CSV `farmaco_a,farmaco_b,severidad,descripcion` →
  aristas INTERACTUA_CON entre :Farmaco (match por nombre_generico lowercase).
  Crear un CSV de ejemplo con 5 interacciones conocidas presentes en datos
  Synthea (p. ej. warfarin/aspirin, simvastatin/clarithromycin).
- ✓ Aceptación: la query multi-paciente (pacientes con 2 rx activas cuyos
  fármacos interactúan) corre y devuelve el formato pedido en §5 de este plan.

**Fase 5 — (Futuro, NO implementar aún, dejar stubs/TODOs)**
- Jerarquía ES_UN de SNOMED; pipeline NLP para aristas causales faltantes
  (con fuente='inferida-NLP', confianza<1, revisión humana); sync incremental
  `_lastUpdated` desde servidor FHIR real; pseudonimización de :Paciente.

**Fase 6 — UI web (grafo interactivo + chat vinculado)** — monorepo, en este repo
- Backend `api/` (FastAPI + uvicorn, 1 worker): endpoints de travesía FIJA
  parametrizada (regla de oro 7 aplica también a la API):
  - `GET /api/pacientes`, `GET /api/pacientes/{pid}/timeline` (delegan en las
    herramientas del agente).
  - `GET /api/pacientes/{pid}/grafo` — vista inicial "núcleo clínico":
    Paciente + Condiciones + Prescripciones + Fármacos + aristas TRATA /
    DE_FARMACO / INTERACTUA_CON (~60-100 nodos). Observaciones (~317/paciente),
    Procedimientos y Encuentros SOLO bajo demanda.
  - `GET /api/nodos/{id}/vecinos?pid=` — expansión 1 salto, LIMIT 40, filtrada
    al paciente (o conceptos compartidos). Expandir el Paciente trae Encuentros.
  - `POST /api/nodos/lote` — materializa evidencia citada por el chat, filtrada
    server-side al paciente (evidencia de otro paciente jamás se pinta).
  - `POST /api/chat` — SSE (`inicio`/`tool_call`/`tool_result` con nodo_ids/
    `texto`/`fin`/`error`); sesiones in-memory con historial multi-turno
    (recorte a 10 intercambios sin partir pares tool_use/tool_result); scope
    de paciente por turno (system_extra + relleno de paciente_id).
- `agente.py`: `loop_agente_eventos(mensajes, system_extra, paciente_id)` —
  generador de eventos con streaming; `loop_agente` queda como wrapper (CLI y
  demo intactos).
- Frontend `ui/` (Vite + React + TS + Tailwind 4 + tokens shadcn + zustand):
  grafo d3-force sobre SVG (zoom/pan/drag, click = expandir, tooltip, leyenda
  con toggles, paleta categórica dark validada con codificación secundaria:
  conceptos = rombos, hueco = resuelto/stopped, INTERACTUA_CON = rojo estado);
  chat con streaming y trazas de tools; la evidencia de cada tool_result se
  resalta/materializa en el grafo (nodos ausentes vía /nodos/lote).
- ✓ Aceptación: grafo inicial legible (<150 nodos); click expande sin recolocar
  el layout; pregunta de medicación muestra trazas en vivo y resalta las
  Prescripciones/Condiciones citadas; segunda pregunta demuestra memoria;
  pregunta sin datos responde "no está en el grafo"; `pytest` y V1-V10 siguen
  en verde; `python agente.py` (demo y pregunta única) sin cambios.

**Fase 6b — Vista temporal (timeline por capas de duración + scrubber compartido)**
- `GET /api/pacientes/{pid}/intervalos`: 4 queries fijas ensambladas en Python
  (condiciones/prescripciones/encuentros + eventos puntuales crudos); binning
  mensual en helper puro `bins_mensuales` (api/eventos.py, testeado).
- `fecha_fin` viaja ahora en los nodos del grafo (`fecha_resolucion` de
  Condicion / `fecha_fin` de Encuentro, normalizadas) para calcular vigencia
  en el cliente.
- Panel inferior plegable y redimensionable: capas por duración clínica (metáfora HNSW,
  crónico arriba → puntual abajo): Condiciones = barras inicio→resolución/hoy
  con lane-packing (hueco = resuelta); Prescripciones = barras activas→hoy /
  ticks puntuales para completed (honesto con la limitación #5: Synthea no
  exporta fin de prescripción); Encuentros = puntos clicables (expanden en el
  grafo); densidad mensual apilada de Observación/Procedimiento/Inmunización/
  Alergia. Los carriles conservan una altura mínima con scroll vertical y el
  eje/brush permanece fijo. Gestos: rueda = zoom horizontal, arrastre en el eje = brush.
- Scrubber compartido: `rangoTiempo` en el store (throttle rAF) +
  `vigenteEn(nodo, rango)` puro (ui/src/tiempo.ts); el grafo atenúa lo no
  vigente SOLO con clase CSS `.fuera-de-tiempo` (sin re-join). Prioridades:
  fuera-de-tiempo (0.08) > atenuado (0.15); la evidencia resaltada nunca
  desaparece (0.45 si además está fuera del rango).
- La evidencia del chat se resalta en AMBAS vistas (mismo Set `resaltados`);
  los puntuales agregados se marcan con triángulos sobre el carril de densidad.
- ✓ Aceptación: el rango del brush atenúa nodos del grafo en vivo y una
  condición resuelta desaparece al elegir un rango posterior a su
  fecha_resolucion; limpiar el chip restaura; evidencia con halo en grafo y
  timeline; pytest, V1-V10 y `python agente.py` (demo) en verde.

## 13. FUERA DE ALCANCE / ADVERTENCIAS

- NUNCA conectar datos reales de pacientes sin resolver pseudonimización y
  control de acceso (Fase 5).
- No usar text-to-Cypher libre en el agente.
- No implementar nodos de fecha :Dia (decisión de diseño ya tomada).
- Si un campo de Synthea difiere de lo especificado, ajustar el handler
  correspondiente y anotar la diferencia en CLAUDE.md.
