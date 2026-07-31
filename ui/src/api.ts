// Cliente de la API FastAPI (proxy de Vite: /api -> localhost:8000).

import type { CatalogoModelos, Grafo, Intervalos, Paciente } from "@/tipos";

async function mensajeError(resp: Response): Promise<string> {
  try {
    const cuerpo = (await resp.json()) as { detail?: string };
    if (cuerpo.detail) return cuerpo.detail;
  } catch {
    // Algunos proxies responden HTML/texto; usamos el estado HTTP.
  }
  return `${resp.status} ${resp.statusText}`;
}

async function json<T>(url: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(url, init);
  if (!resp.ok) throw new Error(await mensajeError(resp));
  return resp.json();
}

export function obtenerPacientes(): Promise<Paciente[]> {
  return json("/api/pacientes");
}

export function obtenerModelos(): Promise<CatalogoModelos> {
  return json("/api/modelos");
}

export function obtenerGrafo(pid: string): Promise<Grafo> {
  return json(`/api/pacientes/${pid}/grafo`);
}

export function obtenerGrafoCompleto(pid: string): Promise<Grafo> {
  return json(`/api/pacientes/${pid}/grafo/completo`);
}

export function obtenerIntervalos(pid: string): Promise<Intervalos> {
  return json(`/api/pacientes/${pid}/intervalos`);
}

export function obtenerVecinos(nodoId: string, pid: string): Promise<Grafo> {
  return json(`/api/nodos/${encodeURIComponent(nodoId)}/vecinos?pid=${pid}`);
}

export function obtenerLote(ids: string[], pid: string): Promise<Grafo> {
  return json("/api/nodos/lote", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ids, pid }),
  });
}

export interface PeticionChat {
  paciente_id: string;
  mensaje: string;
  sesion_id?: string;
  modelo?: string;
}

/**
 * Cliente SSE sobre fetch + ReadableStream (EventSource no soporta POST).
 * Invoca onEvento(evento, datos) por cada bloque `event:`/`data:` recibido.
 */
export async function chatSSE(
  cuerpo: PeticionChat,
  onEvento: (evento: string, datos: Record<string, unknown>) => void | Promise<void>,
  signal?: AbortSignal,
): Promise<void> {
  const resp = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(cuerpo),
    signal,
  });
  if (!resp.ok) throw new Error(await mensajeError(resp));
  if (!resp.body) throw new Error("El servidor no inició el stream de respuesta");

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let corte;
    while ((corte = buffer.indexOf("\n\n")) >= 0) {
      const bloque = buffer.slice(0, corte);
      buffer = buffer.slice(corte + 2);
      let evento = "message";
      let datos = "";
      for (const linea of bloque.split("\n")) {
        if (linea.startsWith("event: ")) evento = linea.slice(7).trim();
        else if (linea.startsWith("data: ")) datos += linea.slice(6);
      }
      if (datos) await onEvento(evento, JSON.parse(datos));
    }
  }
}
