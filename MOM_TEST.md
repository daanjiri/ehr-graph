# MOM_TEST.md — ¿Hay oportunidad aquí? Clientes y qué preguntarles

> Aplicación de *The Mom Test* (Rob Fitzpatrick) a **ehr-graph**.
> Regla del método: **no se valida una idea, se validan hechos sobre la vida de
> otra gente**. Si sales de una conversación sintiéndote bien, probablemente no
> aprendiste nada.

---

## 0. Qué tenemos realmente (para no mentirnos)

Antes de hablar de clientes, el inventario honesto de activos:

| Activo | Estado real | Valor defendible |
|---|---|---|
| Ingesta FHIR R4 → grafo, idempotente | Funciona, 53 pacientes, 31k eventos | Medio: hay librerías y servidores FHIR que ya lo hacen |
| Reificación de eventos + bitemporalidad ligera | Funciona | **Alto**: casi nadie modela el *cuándo se supo* vs *cuándo pasó* |
| Capa de conceptos deduplicada (SNOMED/RxNorm/LOINC) | Funciona (1.854 Rx → nº de fármacos menor) | Medio: OMOP hace lo mismo desde 2010 |
| Aristas causales con `{fuente, confianza}` | Funciona sólo para lo explícito (1.339 TRATA, 2.787 INDICADO_POR) | **Alto**: la gobernanza de procedencia es lo que exige un auditor |
| Retrieval en pinza (vector + travesía fija) | Funciona | Medio-alto: la *travesía fija* (no text-to-Cypher) es un argumento de seguridad real |
| UI grafo + timeline + chat con evidencia resaltada | Funciona | **Alto** como superficie de *explicación*; es lo que se demuestra en 90 segundos |
| Datos | **Synthea, sintéticos y limpios** | **Cero**. Este es el agujero. |

**Segmento 0 (el que probablemente aplica hoy):** si esto es un proyecto de
portafolio, el "cliente" es un *hiring manager* o un cliente de consultoría, y
la "venta" es un puesto o un contrato. Es una lectura legítima y de mayor
retorno esperado que montar una empresa. El Mom Test también sirve ahí: no
preguntes "¿te parece impresionante mi proyecto?", pregunta "¿qué construyó tu
equipo el último trimestre y qué se atascó?".

El resto de este documento asume la lectura ambiciosa: **¿hay producto?**

---

## 1. Las tres hipótesis que este proyecto da por ciertas

El Mom Test dice que hay que ir a buscar el hecho que te *mata*, no el que te
anima. Estas son las tres creencias implícitas del PLAN.md, ordenadas de más a
menos peligrosa:

**H1 — El cuello de botella es *consultar* la historia, no *conseguirla*.**
Synthea entrega FHIR R4 limpio y codificado. En la realidad, la información
clínica llega en CCDA, HL7v2, PDF escaneado, fax y portales sin API. Si en las
entrevistas el dolor que sale es "no consigo los datos" y no "no encuentro nada
dentro de los datos", **el 80% del producto es un pipeline de ingesta sucio y el
grafo es el 20% bonito**. Esta es la hipótesis con más probabilidad de ser falsa.

**H2 — Alguien necesita trazabilidad a nivel de nodo/arista y pagará por ella.**
Puede que baste con "cita la página 47 del PDF". La pregunta empírica: ¿existe
un momento en su trabajo donde alguien *externo* les exige justificar una
conclusión sacada del expediente? (auditoría, denegación apelada, peritaje,
comité). Si no existe ese momento, la trazabilidad es una virtud sin comprador.

**H3 — El grafo aporta algo que RAG sobre texto + una tabla SQL no aportan.**
Este es *el* riesgo del proyecto. Hay que encontrar la pregunta que sólo el
grafo contesta bien: multi-salto temporal ("¿qué fármaco se suspendió tras qué
laboratorio y qué lo reemplazó?"), vigencia por intervalos, cohortes cruzadas,
interacciones entre fármacos de pacientes distintos. Si en 15 entrevistas nadie
hace preguntas de más de un salto, **el grafo es sobreingeniería** y el mismo
valor se entrega con Postgres + pgvector.

Competencia que ya existe y hay que respetar: OMOP/OHDSI + ATLAS (gratis, es el
estándar de facto en investigación), servidores FHIR (HAPI, Medplum, Aidbox,
Firely), Epic Cosmos, y una capa de vendors de "IA sobre el expediente"
(Navina, Regard, Abridge y compañía). Ninguna entrevista debe empezar sin haber
preguntado *qué usan hoy*.

---

## 2. Segmentos candidatos, ordenados por "alcanzable × presupuesto × dolor"

El Mom Test insiste: **segmentar hasta que el "quién" sea tan específico que
sepas a quién escribir esta tarde**. "Hospitales" no es un segmento.

### A. Revisión médico-legal / peritaje / IME / discapacidad ⭐ mejor puerta de entrada
**Quién exactamente:** el paralegal o la enfermera revisora de un despacho de
daños personales o mala praxis; el perito de una aseguradora; una empresa de
*medical record review* (10–200 personas).
**Dolor:** expedientes de 2.000–15.000 páginas en PDF, cronología a mano en
Word/Excel, y la cronología **tiene que citar página** porque va a juicio.
**Por qué encaja:** pagan por caso (no por licencia SaaS), el dolor es agudo y
medible en horas, no hay integración con Epic que negociar, y la trazabilidad no
es un extra: es el entregable. La cronología con evidencia enlazada es
literalmente su producto final.
**Contra:** los datos llegan en PDF → H1 muerde fuerte. Pero aquí eso es el
negocio, no un obstáculo.
**Dónde encontrarlos:** LinkedIn ("legal nurse consultant", "medical record
review", "IME coordinator"), AALNC, grupos de paralegales.

### B. Riesgo/codificación HCC y auditoría (value-based care) ⭐⭐ mayor presupuesto
**Quién exactamente:** director de risk adjustment en un MSO/grupo médico
capitado, o auditor de codificación en una aseguradora Medicare Advantage.
**Dolor:** revisar expedientes para sustentar códigos, y sobrevivir auditorías
RADV donde hay que **enseñar la evidencia exacta** que soporta cada diagnóstico.
**Por qué encaja:** presupuesto grande y ROI aritmético; la procedencia
`{fuente, confianza}` es exactamente el artefacto de auditoría.
**Contra:** mercado con incumbentes fuertes y ciclos de venta largos; entrar sin
red de contactos en el sector es duro.
**Dónde:** AAPC, ACDIS, títulos "risk adjustment", "HCC coding", "CDI".

### C. Cribado y factibilidad de ensayos clínicos
**Quién:** coordinador de estudios de un *site*, o el equipo de feasibility de
una CRO.
**Dolor:** criterios de elegibilidad que son puro razonamiento longitudinal
("HbA1c >7 en dos determinaciones separadas ≥90 días, sin metformina en los
últimos 6 meses"). Se hace leyendo charts a mano.
**Por qué encaja:** son *exactamente* preguntas multi-salto temporales → prueba
directa de H3. Y el sector paga.
**Contra:** OMOP + ATLAS ya es el camino trillado; hay que saber por qué no les
sirve.
**Dónde:** SCRS, ACRP, foros OHDSI, LinkedIn "clinical research coordinator".

### D. Empresas healthtech que ya tienen FHIR (vender el pico y la pala)
**Quién:** CTO o ingeniero de datos de una startup de 10–80 personas que ya
consume FHIR (gestión de cuidados, prior auth, scribes).
**Dolor:** ya normalizaron FHIR una vez y sufrieron; ahora quieren retrieval con
citas y no quieren mantenerlo.
**Por qué encaja:** son alcanzables (te contestan un DM), hablan tu idioma, y
evalúan en semanas, no trimestres.
**Contra:** presupuesto pequeño y tendencia a construirlo en casa.
**Dónde:** Zulip de HL7 FHIR, r/healthIT, Slack de Medplum, HLTH/ViVE.

### E. Revisión de necesidad médica / prior authorization (UM)
Mismo patrón que B (hay que justificar una decisión con evidencia), pero más
regulado y más lento. Segunda ronda, no la primera.

### F. Investigación académica en informática biomédica
Dolor real, **presupuesto cero** y OMOP como incumbente gratuito. Buena fuente
de aprendizaje, mal primer cliente.

### G. Médicos individuales
No compran software, no tienen presupuesto y no eligen herramientas. Salta.

**Recomendación:** empezar por **A** (acceso fácil, dolor agudo, la trazabilidad
es el producto) y **D** (te contestan y validan H3 rápido). Guardar **B** para
cuando tengas una historia de un cliente A o D real.

---

## 3. Las reglas antes de abrir la boca

Los tres pecados capitales, en versión ehr-graph:

1. **Cumplidos.** "Qué chulo el grafo" no es un dato. Es ruido educado.
2. **Palabrería** — futuro, condicional y genérico: *"yo usaría eso"*,
   *"normalmente hacemos..."*, *"seguro que ayudaría"*. Reconducir siempre al
   último caso concreto.
3. **Ideas.** Cuando te propongan features, no las apuntes como roadmap: apunta
   la **motivación** detrás ("¿por qué lo necesitas? ¿cómo lo resuelves hoy?").

Reglas operativas:
- **Nunca menciones "grafo de conocimiento", "Neo4j", "GraphRAG" ni "IA"** en
  los primeros 15 minutos. Que hablen de su semana, no de tu arquitectura.
- Habla tú menos del 20% del tiempo.
- Todo en pasado y en concreto: *la última vez*, no *normalmente*.
- Después de cada respuesta positiva, busca el coste: horas, dinero, quién se
  enfadó.
- Cierra siempre pidiendo un **compromiso** (§6), no un "te aviso".

### Preguntas prohibidas (lo que NO hay que preguntar nunca)

| ❌ Prohibida | Por qué falla | ✅ Versión Mom Test |
|---|---|---|
| "¿Te sería útil un grafo clínico con IA?" | Hipotética + pide opinión sobre tu idea | "Cuéntame la última vez que tuviste que reconstruir la historia completa de un paciente." |
| "¿Pagarías 500 €/mes por esto?" | Nadie sabe qué pagaría; todos dicen que sí por amabilidad | "¿Qué herramientas de este tipo habéis comprado en el último año y cuánto costaron?" |
| "¿Es importante la trazabilidad?" | Respuesta obligada: sí | "¿Alguna vez os han pedido justificar de dónde salió una conclusión del expediente? ¿Qué pasó?" |
| "¿Cuánto tiempo perdéis buscando datos?" | Invita a inventar un número redondo | "El caso de la semana pasada: ¿a qué hora empezaste y a qué hora lo entregaste?" |
| "¿Usarías una vista temporal de la historia?" | Feature en abstracto | "Enséñame cómo miras hoy la evolución de un paciente en el tiempo." (compartir pantalla) |
| "¿Qué te parece la demo?" | Pide cumplido | "¿Qué caso tuyo de la semana pasada NO podría resolver esto?" |

---

## 4. El guion base (20–25 minutos, cualquier segmento)

**Apertura sin pitch** (no digas que estás construyendo algo):
> "Estoy estudiando cómo la gente trabaja con historias clínicas largas. No
> vengo a vender nada — no tengo nada que vender. ¿Te puedo robar 20 minutos
> para que me cuentes cómo fue tu última semana?"

**Bloque 1 — El último caso real (8 min).** Este bloque es el 80% del valor.
1. "Cuéntame el último caso en el que tuviste que revisar la historia completa
   de un paciente. ¿Qué paciente, qué te pedían?"
2. "Llévame paso a paso: ¿qué abriste primero? ¿y después?"
3. "¿Cuántas ventanas/herramientas tenías abiertas a la vez?"
4. "¿A qué hora empezaste y cuándo lo diste por terminado?"
5. "¿Qué fue lo más lento de todo eso?"
6. "¿En qué formato te llegó la información? ¿Me enseñas un ejemplo real
   anonimizado?" ← **esta pregunta mata o salva H1**
7. "¿Cuántos casos así te entraron el mes pasado?"

**Bloque 2 — La forma de las preguntas (5 min).** Aquí se pone a prueba H3.
8. "De lo que buscabas en ese expediente, ¿qué era un dato suelto ('¿qué HbA1c
   tenía?') y qué era una relación ('¿por qué le cambiaron el fármaco?')?"
9. "¿Alguna vez necesitaste saber qué estaba tomando el paciente **en una fecha
   concreta del pasado**? ¿Cómo lo averiguaste?"
10. "¿Has tenido que responder algo que exigiera enlazar varias cosas —
    'suspendieron X *porque* salió Y y lo reemplazaron por Z'? Cuéntame ese caso."
11. "¿Has tenido que comparar varios pacientes entre sí? ¿Para qué?"

**Bloque 3 — Consecuencias y coste (4 min).** Sin dolor con factura, no hay venta.
12. "¿Alguna vez se te escapó algo relevante del expediente? ¿Qué pasó después?"
13. "¿Quién más en la organización sufre esto?"
14. "Si sumas el tiempo del equipo, ¿cuánto os cuesta esto al mes?"

**Bloque 4 — Alternativas ya intentadas (4 min).** Si no han intentado nada, no
duele lo suficiente.
15. "¿Qué habéis probado ya para arreglarlo?"
16. "¿Por qué no funcionó / por qué lo dejasteis?"
17. "¿Qué usáis hoy — Epic, OMOP, un Excel, becarios?"
18. "¿Qué herramienta nueva fue la última que compró el equipo? ¿Quién la firmó
    y cuánto tardó?" ← revela el proceso de compra sin preguntar por dinero

**Cierre — compromiso (2 min).** Ver §6. Nunca cierres con "te mando algo".

---

## 5. Preguntas específicas por segmento

**A · Médico-legal / peritaje**
- "Cuando entregas una cronología, ¿qué formato exige el abogado? ¿Enséñamela."
- "¿Cómo citas la fuente de cada línea de la cronología hoy?"
- "¿Alguna vez la parte contraria impugnó tu cronología? ¿Qué falló?"
- "¿Cobras por caso o por hora? ¿Cuánto salió el último?"
- "¿Cuánto de las 2.000 páginas del último caso resultó ser irrelevante?"

**B · Riesgo / HCC / auditoría**
- "Cuéntame la última auditoría. ¿Qué os pidieron exactamente y cómo lo montasteis?"
- "¿Qué pasó la última vez que un código no se pudo sustentar?"
- "¿Cómo decidís qué expedientes revisar primero?"
- "¿Cuántos charts revisó tu equipo el trimestre pasado y con cuánta gente?"

**C · Ensayos clínicos**
- "Enséñame los criterios de elegibilidad del último protocolo que cribaste."
- "De esos criterios, ¿cuáles no se pueden sacar de una query y hay que leer a mano?"
- "¿Cuántos pacientes revisasteis para reclutar al último?"
- "¿Habéis usado ATLAS/OMOP? ¿Qué os hizo abandonarlo o mantenerlo?" ← crítica

**D · Healthtech con FHIR**
- "¿Cómo tenéis guardado el FHIR hoy? ¿Quién lo montó y cuánto tardó?"
- "¿Qué preguntas de vuestro producto siguen sin poder responderse con eso?"
- "Cuando vuestro LLM cita una fuente, ¿de dónde sale la cita? ¿Alguien se ha
  quejado de que se la inventó?"
- "¿Qué parte de esto construiríais vosotros pase lo que pase?" ← si la respuesta
  es "toda", no son clientes

---

## 6. Compromisos que pedir (escalera, de menor a mayor)

Una reunión que acaba en "muy interesante, mantenme al tanto" es una reunión
**fallida**. Las tres monedas son **tiempo, reputación y dinero**:

1. **Tiempo:** "¿Me dedicas 45 minutos compartiendo pantalla mientras haces el
   próximo caso real?"
2. **Datos:** "¿Me pasas 5 expedientes anonimizados y las 10 preguntas que de
   verdad tienes que contestar sobre ellos?" ← **el compromiso más valioso de
   todos**; convierte tu demo Synthea en una prueba real y falsa H1 de golpe.
3. **Reputación:** "¿Me presentas a la persona que aprueba compras de este tipo?"
4. **Dinero:** piloto pagado sobre 20 expedientes reales, o carta de intención.

Si dicen que sí a (2) y luego no mandan nada en una semana: eso *también* es un
dato, y es un "no".

---

## 7. Señales: cómo leer lo que oigas

| Señal buena (hecho) | Señal falsa (ruido) |
|---|---|
| "Te enseño el Excel que uso para esto" | "Suena muy útil" |
| "El mes pasado dedicamos 60 horas a esto" | "Perdemos bastante tiempo" |
| "Ya compramos X y no funcionó porque…" | "Deberíamos automatizar esto algún día" |
| Te presenta a un compañero sin pedírselo | "Te presento a alguien" (y no lo hace) |
| Te manda datos anonimizados en 48 h | "Mándame la demo cuando la tengas" |
| Se enfada contando el problema | Asiente educadamente |

---

## 8. Criterios de muerte (decididos ANTES de entrevistar)

Escribirlos antes evita reinterpretar los resultados a conveniencia.

Tras **15 entrevistas** repartidas en 2 segmentos, se abandona la lectura de
producto si se cumple alguna:

- **K1 (H3):** menos de 5 de 15 recuerdan una pregunta real de más de un salto o
  con lógica temporal. → El grafo es sobreingeniería; el proyecto se queda como
  pieza de portafolio y aprendizaje, que ya es un resultado legítimo.
- **K2 (H1):** más de 12 de 15 reciben los datos en PDF/fax sin FHIR ni CCDA. →
  El negocio es extracción documental, no grafos. Pivotar o parar.
- **K3 (H2):** nadie describe un momento concreto en el que tuvo que justificar
  ante un tercero una conclusión sacada del expediente. → La trazabilidad no
  tiene comprador.
- **K4:** ninguno de los 15 sube un solo escalón de la §6. → No hay dolor.

Y el criterio de continuar: **3 personas del mismo segmento describen el mismo
caso concreto, con el mismo formato de entrada, y al menos 1 entrega datos
reales.** Eso ya es un beachhead y toca construir para ellos, no para "hospitales".

---

## 9. Plan de 2 semanas

| Días | Acción |
|---|---|
| 1 | Elegir 2 segmentos (recomendado: A y D). Escribir K1–K4 y firmarlos. |
| 1–2 | Lista de 40 nombres concretos con nombre y apellido (LinkedIn, Zulip FHIR, AALNC). |
| 2–10 | 15 conversaciones. Sin demo, sin pitch, sin mencionar Neo4j. Notas textuales, verbatim, el mismo día. |
| 6 | Revisión a mitad: ¿alguna pregunta del guion no está sirviendo? Reescribirla. |
| 11–12 | Codificar las notas contra H1/H2/H3 y K1–K4. Contar, no impresionarse. |
| 13–14 | Decisión: beachhead con datos reales de alguien, o cierre honesto como proyecto de portafolio (§0). |

---

## 10. Veredicto provisional (antes de hablar con nadie)

**Sí hay una oportunidad plausible, pero no es la que sugiere el PLAN.md.** El
plan está escrito como si el valor estuviera en el *modelo de datos*; el valor
comercializable está en la **cronología defendible con evidencia enlazada** para
alguien a quien un tercero le exige justificarse. El grafo es el *cómo*, no el
*qué*.

Los dos riesgos que hay que ir a buscar deliberadamente son: (a) que el dolor
real esté aguas arriba, en conseguir y limpiar los datos, no en consultarlos; y
(b) que ninguna pregunta real necesite más de un salto, en cuyo caso Postgres +
pgvector entrega el mismo valor con una décima parte de la complejidad.

Todo esto es una hipótesis escrita desde un escritorio con datos sintéticos.
No vale nada hasta que 15 personas cuenten qué hicieron la semana pasada.
