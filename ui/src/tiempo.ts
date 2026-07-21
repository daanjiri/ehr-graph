// Lógica temporal pura (sin D3 ni React): vigencia de nodos frente a un rango
// y empaquetado de barras en sub-filas. Aislada aquí para poder testearse con
// vitest en el futuro sin refactor.

import type { NodoGrafo } from "@/tipos";
import { esConcepto, esInactivo } from "@/paleta";

export type RangoTiempo = [number, number] | null; // timestamps ms UTC

const SIEMPRE_VIGENTES = new Set(["Paciente", "Farmaco"]);

/**
 * ¿Está el nodo "vigente" dentro del rango temporal?
 * - Sin rango, sin fecha (fecha_desconocida) o entidades atemporales → true
 *   (nunca ocultar lo que no se puede datar — regla de oro 4).
 * - Condicion: intervalo [fecha, fecha_fin ?? (activa ? hoy : fecha)].
 * - Prescripcion activa: [fecha, hoy]; completed/stopped: puntual en fecha
 *   (Synthea no exporta fin de prescripción — limitación #5).
 * - Encuentro: [fecha, fecha_fin ?? fecha].
 * - Puntuales: fecha dentro del rango.
 */
export function vigenteEn(
  n: Pick<NodoGrafo, "tipo" | "fecha" | "fecha_fin" | "estado">,
  rango: RangoTiempo,
  hoy: number = Date.now(),
): boolean {
  if (!rango) return true;
  if (SIEMPRE_VIGENTES.has(n.tipo) || esConcepto(n.tipo)) return true;
  if (!n.fecha) return true;
  const inicio = Date.parse(n.fecha);
  if (Number.isNaN(inicio)) return true;

  let fin = inicio;
  if (n.fecha_fin) {
    fin = Date.parse(n.fecha_fin);
    if (Number.isNaN(fin)) fin = inicio;
  } else if (
    (n.tipo === "Condicion" || n.tipo === "Prescripcion") &&
    !esInactivo(n.estado)
  ) {
    fin = hoy; // activa sin fin conocido → sigue vigente
  }
  const [desde, hasta] = rango;
  return inicio <= hasta && fin >= desde;
}

/**
 * Lane-packing: asigna cada intervalo (ordenado por inicio) a la primera
 * sub-fila cuyo último fin + margen no lo solape. Devuelve el índice de
 * sub-fila por elemento (mismo orden que la entrada).
 */
export function empaquetarFilas(
  items: { inicio: number; fin: number }[],
  margen = 0,
): number[] {
  const finales: number[] = []; // último fin ocupado por sub-fila
  return items.map((item) => {
    for (let fila = 0; fila < finales.length; fila++) {
      if (finales[fila] + margen <= item.inicio) {
        finales[fila] = item.fin;
        return fila;
      }
    }
    finales.push(item.fin);
    return finales.length - 1;
  });
}
