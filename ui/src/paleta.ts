// Paleta categórica dark validada (dataviz: banda L, croma, CVD, contraste ≥3:1
// sobre #1a1a19). Asignación fija tipo→hue; los conceptos se pliegan en una
// categoría neutra con forma cuadrada (codificación compuesta) y el Paciente es
// el hub en tinta primaria, no una serie.

import type { NodoGrafo } from "@/tipos";

export const COLOR_TIPO: Record<string, string> = {
  Prescripcion: "#3987e5", // azul
  Procedimiento: "#199e70", // aqua
  Encuentro: "#c98500", // amarillo
  Inmunizacion: "#008300", // verde
  Farmaco: "#9085e9", // violeta
  Condicion: "#e66767", // rojo
  Alergia: "#d55181", // magenta
  Observacion: "#d95926", // naranja
  Paciente: "#ffffff",
  Concepto: "#898781", // neutro (ConceptoDiagnostico/Lab/Procedimiento/Sustancia)
};

export function esConcepto(tipo: string): boolean {
  return tipo.startsWith("Concepto") || tipo === "Sustancia";
}

/** Clave de leyenda: los 4 tipos de concepto comparten entrada. */
export function claveLeyenda(tipo: string): string {
  return esConcepto(tipo) ? "Concepto" : tipo;
}

export function colorNodo(n: Pick<NodoGrafo, "tipo">): string {
  return COLOR_TIPO[claveLeyenda(n.tipo)] ?? COLOR_TIPO.Concepto;
}

const RADIO_TIPO: Record<string, number> = {
  Paciente: 24,
  Condicion: 11,
  Prescripcion: 10,
  Farmaco: 9,
  Alergia: 9,
  Encuentro: 9,
  Procedimiento: 8,
  Inmunizacion: 8,
  Observacion: 7,
  Concepto: 6,
};

export function radioNodo(n: Pick<NodoGrafo, "tipo">): number {
  return RADIO_TIPO[claveLeyenda(n.tipo)] ?? 7;
}

/** Relleno por estado: activo = sólido, resuelto/finalizado = hueco (superficie). */
export function rellenoNodo(n: Pick<NodoGrafo, "tipo" | "estado">): string {
  if (n.tipo === "Paciente") return "#1a1a19";
  return esInactivo(n.estado) ? "#1a1a19" : colorNodo(n);
}

/** Estados terminales en los datos reales: resolved (Condicion), completed/stopped (Prescripcion). */
export function esInactivo(estado?: string): boolean {
  return estado === "resolved" || estado === "stopped" || estado === "completed";
}

/** Tipos con etiqueta directa; el resto se lee por tooltip (evita saturación). */
export function muestraEtiqueta(tipo: string): boolean {
  return ["Paciente", "Condicion", "Prescripcion", "Farmaco", "Alergia"].includes(tipo);
}

export interface EstiloArista {
  color: string;
  ancho: number;
  guiones?: string;
  flecha?: boolean;
}

const CAUSAL: EstiloArista = { color: "#c3c2b7", ancho: 1.5, flecha: true };
const ESTRUCTURAL: EstiloArista = { color: "#2c2c2a", ancho: 1 };

export function estiloArista(tipo: string): EstiloArista {
  switch (tipo) {
    case "TRATA":
      return CAUSAL;
    case "INDICADO_POR":
    case "EVIDENCIA_DE":
    case "COMPLICACION_DE":
    case "MOTIVO_SUSPENSION_DE":
    case "REEMPLAZA_A":
    case "MONITOREA":
      return { ...CAUSAL, guiones: "5 3" };
    case "INTERACTUA_CON":
      // estado crítico reservado: interacción farmacológica
      return { color: "#d03b3b", ancho: 2, guiones: "4 3" };
    default:
      return ESTRUCTURAL; // DE_PACIENTE, *_EN, CODIFICADA_COMO, DE_FARMACO...
  }
}

/** Orden fijo de la leyenda (nunca ciclado). */
export const TIPOS_LEYENDA = [
  "Condicion",
  "Prescripcion",
  "Farmaco",
  "Encuentro",
  "Procedimiento",
  "Observacion",
  "Inmunizacion",
  "Alergia",
  "Concepto",
];
