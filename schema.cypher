// schema.cypher — DDL del grafo clínico FHIR robusto.
// Requiere reconstruir una base creada con el esquema v2: las claves cambiaron.

// Recursos FHIR. `id` es la clave canónica fuente|resourceType/id.
CREATE CONSTRAINT paciente_id IF NOT EXISTS
FOR (p:Paciente) REQUIRE p.id IS UNIQUE;
CREATE CONSTRAINT evento_id IF NOT EXISTS
FOR (e:Evento) REQUIRE e.id IS UNIQUE;
CREATE CONSTRAINT componente_observacion_id IF NOT EXISTS
FOR (c:ComponenteObservacion) REQUIRE c.id IS UNIQUE;

// Conceptos: la identidad FHIR/terminológica siempre es (sistema, código).
CREATE CONSTRAINT snomed IF NOT EXISTS
FOR (c:ConceptoDiagnostico) REQUIRE (c.sistema, c.codigo) IS UNIQUE;
CREATE CONSTRAINT rxnorm IF NOT EXISTS
FOR (f:Farmaco) REQUIRE (f.sistema, f.codigo) IS UNIQUE;
CREATE CONSTRAINT loinc IF NOT EXISTS
FOR (l:ConceptoLab) REQUIRE (l.sistema, l.codigo) IS UNIQUE;
CREATE CONSTRAINT cproc IF NOT EXISTS
FOR (c:ConceptoProcedimiento) REQUIRE (c.sistema, c.codigo) IS UNIQUE;
CREATE CONSTRAINT sustancia IF NOT EXISTS
FOR (s:Sustancia) REQUIRE (s.sistema, s.codigo) IS UNIQUE;
CREATE CONSTRAINT concepto_motivo IF NOT EXISTS
FOR (c:ConceptoMotivo) REQUIRE (c.sistema, c.codigo) IS UNIQUE;
CREATE CONSTRAINT concepto_vacuna IF NOT EXISTS
FOR (v:ConceptoVacuna) REQUIRE (v.sistema, v.codigo) IS UNIQUE;

// Consultas temporales y de estado.
CREATE INDEX evento_fecha IF NOT EXISTS
FOR (e:Evento) ON (e.fecha_efectiva);
CREATE INDEX evento_pac_fecha IF NOT EXISTS
FOR (e:Evento) ON (e.paciente_id, e.fecha_efectiva);
CREATE INDEX evento_fhir_ref IF NOT EXISTS
FOR (e:Evento) ON (e.fuente_datos, e.fhir_tipo, e.fhir_id);
CREATE INDEX paciente_fhir_ref IF NOT EXISTS
FOR (p:Paciente) ON (p.fuente_datos, p.fhir_id);
CREATE INDEX rx_estado IF NOT EXISTS
FOR (r:Prescripcion) ON (r.estado);
CREATE INDEX cond_estado IF NOT EXISTS
FOR (c:Condicion) ON (c.estado_clinico);

// El índice vectorial se crea en semantica.py (384 dimensiones, cosine).
