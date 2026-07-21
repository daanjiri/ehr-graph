# CLAUDE.md — Convenciones del proyecto ehr-graph

Knowledge graph clínico multi-paciente en Neo4j desde bundles FHIR de Synthea,
con capa semántica vectorial y agente GraphRAG. La especificación completa está
en **PLAN.md** — es la fuente de verdad; ante cualquier duda de diseño, gana PLAN.md.

## Reglas de oro del grafo (nunca violar)

1. Todo evento clínico es NODO con doble label `:Tipo:Evento` — nunca arista directa
   paciente→diagnóstico.
2. Todo :Evento lleva: `id`, `fecha_efectiva` (datetime UTC), `fecha_registro`,
   `paciente_id` (denormalizado a propósito, para el índice compuesto),
   `texto_descriptivo`.
3. Escrituras SIEMPRE con `MERGE` por id — la ingesta debe ser idempotente y
   re-ejecutable.
4. Fechas: normalizar a UTC en la ingesta; nunca strings, siempre `datetime()`;
   sin fecha → null + `fecha_desconocida:true`, jamás inventar.
5. Aristas causales (TRATA, INDICADO_POR, etc.) siempre con
   `{fuente, confianza}`. Desde FHIR: `'explicita', 1.0`.
6. Capa de conceptos (Farmaco, ConceptoDiagnostico, ConceptoLab...) deduplicada
   por código, compartida entre pacientes, sin :Evento ni paciente_id.
7. El agente usa herramientas de travesía fija — NO text-to-Cypher libre.
8. Solo datos sintéticos (Synthea). No conectar datos reales.

## Entorno

- Neo4j: `docker compose up -d` → bolt://localhost:7687, auth neo4j/password123
- Datos: `java -jar synthea-with-dependencies.jar -p 50` → ./output/fhir/
- Python: pip install -r requirements.txt
- Validación: `python validar.py` debe pasar V1–V10 (definidas en PLAN.md §11)
  antes de dar una fase por terminada.

## UI web (Fase 6 — monorepo: api/ + ui/ en este mismo repo)

- API: `uv run uvicorn api.main:app --host 127.0.0.1 --port 8010` (requiere
  Neo4j arriba y ANTHROPIC_API_KEY para el chat; SIEMPRE 1 worker — sesiones
  in-memory). OJO: el puerto 8000 lo ocupa otro servicio Docker por IPv6 en
  esta máquina — no volver a 8000.
- UI: `cd ui && npm install && npm run dev` → http://localhost:5173
  (proxy de Vite: /api → 127.0.0.1:8010, sin CORS).
- La API expone SOLO travesías fijas parametrizadas — la regla de oro 7
  aplica también aquí; jamás añadir un endpoint de Cypher libre. Endpoints:
  /pacientes, /pacientes/{pid}/grafo, /pacientes/{pid}/timeline,
  /pacientes/{pid}/intervalos (vista temporal), /nodos/{id}/vecinos,
  /nodos/lote, /chat (SSE).
- Vista temporal: los nodos del grafo llevan `fecha_fin` (fecha_resolucion de
  Condicion / fecha_fin de Encuentro); estado `completed` de Prescripcion es
  inactivo (hueco), junto a `stopped`/`resolved`. `es_cronica` es SIEMPRE null
  (fase NLP futura) — la estratificación crónico/episódico se hace por
  duración/estado. Gestos de la timeline: rueda = zoom, arrastre en carriles =
  pan, arrastre en la banda del eje = brush (filtra el grafo por vigencia).
- Evidencia del chat: los endpoints /nodos/lote y /vecinos filtran por
  paciente server-side; evidencia de otro paciente no se pinta en el grafo.
- Frontend: TypeScript + Tailwind 4 + tokens shadcn (tema oscuro único) +
  zustand + d3-force sobre SVG. Paleta categórica en ui/src/paleta.ts —
  validada con el método dataviz (no cambiar hues sin re-validar).
- `python agente.py` (CLI demo/pregunta única) debe seguir funcionando tras
  cualquier cambio en el loop del agente (loop_agente_eventos es la fuente).

## Estilo de código

- Python simple y legible; un handler por resourceType FHIR en ingest.py para
  que los errores queden localizados.
- Modelo de embeddings: paraphrase-multilingual-MiniLM-L12-v2 (384 dims) — no
  cambiar sin actualizar la dimensión del índice vectorial.
- LLM del agente: claude-sonnet-4-6.
- Comentarios y textos de cara al usuario en español; los datos Synthea vienen
  en inglés y está bien.

## Registro de diferencias encontradas

(Anotar aquí cualquier campo de Synthea que difiera de lo especificado en PLAN.md
y cómo se resolvió.)

1. **`-p 50` genera 53 bundles**: Synthea exporta también los pacientes fallecidos
   durante la simulación (50 vivos + 3 fallecidos). Normal, no es un bug.
2. **`Encounter.class`** es un Coding v3-ActCode (AMB/EMER/IMP/WELLNESS...) casi
   siempre sin display → se mapea con el dict fijo `CLASE_ENCUENTRO` en ingest.py.
   `motivo_consulta` sale de `reasonCode[0]` si existe, si no del display de `type[0]`.
3. **`clinicalStatus`/`verificationStatus` son CodeableConcept**, no strings →
   `code_only()` extrae `.coding[0].code`. La fecha de resolución viene como
   `abatementDateTime`.
4. **765 MedicationRequest usan `medicationReference`** (no `medicationCodeableConcept`)
   → se resuelve contra el recurso `Medication` del mismo bundle vía el mapa fullUrl.
5. **`fecha_fin` de Prescripcion no existe en Synthea** (solo `status: stopped`) →
   `medicacion_activa` y las queries de vigencia filtran PRIMERO por `estado='active'`;
   el intervalo de fechas es refinamiento secundario.
6. **Referencias condicionales** (`Practitioner?identifier=...` en participant/
   serviceProvider) no resuelven contra el mapa fullUrl → `ref_id()` devuelve None
   sin romper. Profesional/Institucion quedan sin poblar (baja prioridad, como
   permite PLAN.md §4.1).
7. **Observation con `component[]`** (presión arterial) o `valueCodeableConcept`
   (smoking status) → se aplana a string "Systolic... 120 / Diastolic... 80".
8. **`reasonReference` es array esparso** → se itera completo (no solo [0]);
   genera 1.339 aristas TRATA y 2.787 INDICADO_POR con fuente='explicita'.
9. **Búsqueda cruzada es/en**: el modelo de embeddings ancla bien términos clínicos
   ("colonoscopia"→Colonoscopy 0.94, "heart problems" 0.86) pero NO paráfrasis
   coloquiales ("examen del colon" cae en exámenes generales, la colonoscopia no
   entra ni al top 20). Mitigación: la descripción de buscar_semantico instruye al
   agente a usar el término clínico en inglés o el cognado y reformular.
10. **Tipos ignorados a propósito** (contados en cada ingesta): Claim,
    ExplanationOfBenefit (facturación), DiagnosticReport, DocumentReference
    (redundantes con Observation), CarePlan, CareTeam, SupplyDelivery, Device,
    ImagingStudy, Provenance, MedicationAdministration (stub Fase 5).
