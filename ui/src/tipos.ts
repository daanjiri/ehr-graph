// Tipos compartidos del frontend (contratos con la API FastAPI).

export interface NodoGrafo {
  id: string;
  fhir_id?: string; // logical id original; `id` es la clave canónica del grafo
  tipo: string; // 'Paciente' | 'Condicion' | 'Prescripcion' | 'Farmaco' | ...
  etiqueta: string;
  descripcion?: string;
  fecha?: string;
  fecha_fin?: string; // fecha_resolucion (Condicion) / fecha_fin (Encuentro)
  estado?: string;
  // Campos de la simulación d3-force (los muta D3, nunca React):
  x?: number;
  y?: number;
  vx?: number;
  vy?: number;
  fx?: number | null;
  fy?: number | null;
}

export interface Arista {
  origen: string;
  destino: string;
  tipo: string;
  severidad?: string;
}

export interface Grafo {
  nodos: NodoGrafo[];
  aristas: Arista[];
}

export interface Paciente {
  id: string;
  fhir_id?: string;
  nombre: string;
  sexo?: string;
  fecha_nacimiento?: string;
  fallecido?: boolean;
}

export interface ModeloAnthropic {
  id: string;
  nombre: string;
  descripcion: string;
  nivel_costo: "bajo" | "medio" | "alto";
}

export interface CatalogoModelos {
  predeterminado: string;
  modelos: ModeloAnthropic[];
}

// --- Vista temporal (Fase 6b) ---

export interface IntervaloCondicion {
  id: string;
  nombre: string;
  fecha_inicio?: string;
  fecha_resolucion?: string;
  estado?: string;
}

export interface IntervaloPrescripcion {
  id: string;
  farmaco: string;
  fecha_inicio?: string;
  estado?: string;
}

export interface IntervaloEncuentro {
  id: string;
  fecha_inicio: string;
  fecha_fin?: string;
  tipo?: string;
  motivo?: string;
}

export interface BinMensual {
  mes: string; // 'YYYY-MM'
  tipo: string;
  n: number;
}

export interface Intervalos {
  condiciones: IntervaloCondicion[];
  prescripciones: IntervaloPrescripcion[];
  encuentros: IntervaloEncuentro[];
  bins: BinMensual[];
}

export interface Traza {
  nombre: string;
  pendiente: boolean;
  nResultados?: number;
  nodoIds?: string[];
  error?: string;
}

export type Parte =
  | { tipo: "texto"; texto: string }
  | { tipo: "traza"; traza: Traza };

export interface Mensaje {
  rol: "usuario" | "asistente";
  partes: Parte[];
  modelo?: ModeloAnthropic;
  nodoIds?: string[]; // evidencia final del turno (para re-resaltar)
  enCurso?: boolean;
  error?: boolean;
}
