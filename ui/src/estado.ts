// Store global (zustand): suscripciones selectivas para que los deltas del
// stream SSE no re-rendericen el grafo, solo el panel de chat.

import { create } from "zustand";
import {
  chatSSE,
  obtenerGrafo,
  obtenerIntervalos,
  obtenerLote,
  obtenerPacientes,
  obtenerVecinos,
} from "@/api";
import type { Arista, Grafo, Intervalos, Mensaje, NodoGrafo, Paciente } from "@/tipos";
import { claveLeyenda } from "@/paleta";
import type { RangoTiempo } from "@/tiempo";

interface EstadoApp {
  pacientes: Paciente[];
  pacienteId: string | null;
  cargandoGrafo: boolean;
  nodos: NodoGrafo[];
  aristas: Arista[];
  versionGrafo: number; // bump -> GrafoPaciente re-hace el join de D3
  resaltados: Set<string>;
  tiposOcultos: Set<string>;
  mensajes: Mensaje[];
  streamActivo: boolean;
  abortCtrl: AbortController | null;
  sesiones: Record<string, string>; // pacienteId -> sesion_id

  // vista temporal
  intervalos: Intervalos | null;
  timelineAbierta: boolean;
  rangoTiempo: RangoTiempo;

  cargarPacientes(): Promise<void>;
  seleccionarPaciente(id: string): Promise<void>;
  expandirNodo(id: string): Promise<void>;
  fusionarGrafo(g: Grafo): void;
  alternarTipo(clave: string): void;
  resaltar(ids: string[]): void;
  vincularEvidencia(ids: string[]): Promise<void>;
  enviarMensaje(texto: string): Promise<void>;
  abortarStream(): void;
  alternarTimeline(): void;
  fijarRangoTiempo(rango: RangoTiempo): void;
}

const claveArista = (a: Arista) => `${a.origen}|${a.tipo}|${a.destino}`;

export const useEstado = create<EstadoApp>((set, get) => ({
  pacientes: [],
  pacienteId: null,
  cargandoGrafo: false,
  nodos: [],
  aristas: [],
  versionGrafo: 0,
  resaltados: new Set(),
  tiposOcultos: new Set(),
  mensajes: [],
  streamActivo: false,
  abortCtrl: null,
  sesiones: {},
  intervalos: null,
  timelineAbierta: true,
  rangoTiempo: null,

  async cargarPacientes() {
    set({ pacientes: await obtenerPacientes() });
  },

  async seleccionarPaciente(id) {
    get().abortarStream();
    set((s) => ({
      pacienteId: id,
      nodos: [],
      aristas: [],
      resaltados: new Set<string>(),
      mensajes: [],
      cargandoGrafo: true,
      intervalos: null,
      rangoTiempo: null,
      versionGrafo: s.versionGrafo + 1,
    }));
    // la timeline se carga en paralelo y no bloquea el grafo si falla
    obtenerIntervalos(id)
      .then((iv) => {
        if (get().pacienteId === id) set({ intervalos: iv });
      })
      .catch(() => {});
    try {
      const g = await obtenerGrafo(id);
      const paciente = g.nodos.find((n) => n.tipo === "Paciente");
      if (paciente) {
        paciente.fx = 0; // hub anclado al centro
        paciente.fy = 0;
      }
      set((s) => ({
        nodos: g.nodos,
        aristas: g.aristas,
        cargandoGrafo: false,
        versionGrafo: s.versionGrafo + 1,
      }));
    } catch {
      set({ cargandoGrafo: false });
    }
  },

  async expandirNodo(id) {
    const { pacienteId } = get();
    if (!pacienteId) return;
    get().fusionarGrafo(await obtenerVecinos(id, pacienteId));
  },

  fusionarGrafo(g) {
    set((s) => {
      const idsExistentes = new Set(s.nodos.map((n) => n.id));
      const nuevos = g.nodos.filter((n) => !idsExistentes.has(n.id));
      for (const n of nuevos) idsExistentes.add(n.id);

      const claves = new Set(s.aristas.map(claveArista));
      const nuevasAristas = g.aristas.filter((a) => {
        if (!idsExistentes.has(a.origen) || !idsExistentes.has(a.destino)) return false;
        if (claves.has(claveArista(a))) return false;
        claves.add(claveArista(a));
        return true;
      });

      if (!nuevos.length && !nuevasAristas.length) return {};
      return {
        nodos: [...s.nodos, ...nuevos],
        aristas: [...s.aristas, ...nuevasAristas],
        versionGrafo: s.versionGrafo + 1,
      };
    });
  },

  alternarTipo(clave) {
    set((s) => {
      const tiposOcultos = new Set(s.tiposOcultos);
      if (tiposOcultos.has(clave)) tiposOcultos.delete(clave);
      else tiposOcultos.add(clave);
      return { tiposOcultos, versionGrafo: s.versionGrafo + 1 };
    });
  },

  resaltar(ids) {
    set({ resaltados: new Set(ids) });
  },

  /** Resalta la evidencia del chat; trae al grafo los nodos que falten. */
  async vincularEvidencia(ids) {
    const { pacienteId, nodos } = get();
    if (!pacienteId || !ids.length) return;
    const presentes = new Set(nodos.map((n) => n.id));
    if (ids.some((id) => !presentes.has(id))) {
      // Pide TODOS los ids del turno para traer también aristas nuevos<->previos.
      // El backend filtra por paciente: evidencia de otro paciente no se pinta.
      try {
        get().fusionarGrafo(await obtenerLote(ids, pacienteId));
      } catch {
        /* la evidencia no bloquea el chat */
      }
    }
    get().resaltar(ids);
  },

  async enviarMensaje(texto) {
    const { pacienteId, streamActivo, sesiones } = get();
    if (!pacienteId || streamActivo || !texto.trim()) return;
    const ctrl = new AbortController();
    const idsTurno: string[] = [];

    const actualizarUltimo = (fn: (m: Mensaje) => Mensaje) =>
      set((s) => {
        const mensajes = [...s.mensajes];
        mensajes[mensajes.length - 1] = fn(mensajes[mensajes.length - 1]);
        return { mensajes };
      });

    set((s) => ({
      streamActivo: true,
      abortCtrl: ctrl,
      resaltados: new Set<string>(),
      mensajes: [
        ...s.mensajes,
        { rol: "usuario", partes: [{ tipo: "texto", texto }] },
        { rol: "asistente", partes: [], enCurso: true },
      ],
    }));

    try {
      await chatSSE(
        { paciente_id: pacienteId, mensaje: texto, sesion_id: sesiones[pacienteId] },
        async (evento, datos) => {
          if (evento === "inicio") {
            const sesionId = datos.sesion_id as string;
            set((s) => ({ sesiones: { ...s.sesiones, [pacienteId]: sesionId } }));
          } else if (evento === "texto") {
            actualizarUltimo((m) => {
              const partes = [...m.partes];
              const ultima = partes[partes.length - 1];
              if (ultima?.tipo === "texto") {
                partes[partes.length - 1] = {
                  tipo: "texto",
                  texto: ultima.texto + (datos.delta as string),
                };
              } else {
                partes.push({ tipo: "texto", texto: datos.delta as string });
              }
              return { ...m, partes };
            });
          } else if (evento === "tool_call") {
            actualizarUltimo((m) => ({
              ...m,
              partes: [
                ...m.partes,
                { tipo: "traza", traza: { nombre: datos.nombre as string, pendiente: true } },
              ],
            }));
          } else if (evento === "tool_result") {
            const nodoIds = (datos.nodo_ids as string[]) ?? [];
            actualizarUltimo((m) => {
              const partes = [...m.partes];
              for (let i = partes.length - 1; i >= 0; i--) {
                const p = partes[i];
                if (p.tipo === "traza" && p.traza.pendiente && p.traza.nombre === datos.nombre) {
                  partes[i] = {
                    tipo: "traza",
                    traza: {
                      nombre: p.traza.nombre,
                      pendiente: false,
                      nResultados: datos.n_resultados as number,
                      nodoIds,
                      error: datos.error as string | undefined,
                    },
                  };
                  break;
                }
              }
              return { ...m, partes };
            });
            for (const id of nodoIds) if (!idsTurno.includes(id)) idsTurno.push(id);
            await get().vincularEvidencia([...idsTurno]);
          } else if (evento === "fin") {
            const nodoIds = (datos.nodo_ids as string[]) ?? [];
            actualizarUltimo((m) => ({ ...m, enCurso: false, nodoIds }));
            await get().vincularEvidencia(nodoIds);
          } else if (evento === "error") {
            actualizarUltimo((m) => ({
              ...m,
              enCurso: false,
              error: true,
              partes: [...m.partes, { tipo: "texto", texto: `Error: ${datos.mensaje}` }],
            }));
          }
        },
        ctrl.signal,
      );
    } catch (e) {
      if ((e as Error).name !== "AbortError") {
        actualizarUltimo((m) => ({
          ...m,
          error: true,
          partes: [...m.partes, { tipo: "texto", texto: `Error de conexión: ${String(e)}` }],
        }));
      }
    } finally {
      actualizarUltimo((m) => ({ ...m, enCurso: false }));
      set({ streamActivo: false, abortCtrl: null });
    }
  },

  abortarStream() {
    get().abortCtrl?.abort();
  },

  alternarTimeline() {
    set((s) => ({ timelineAbierta: !s.timelineAbierta }));
  },

  // El throttle (rAF) vive en VistaTemporal; aquí solo el set.
  fijarRangoTiempo(rango) {
    set({ rangoTiempo: rango });
  },
}));

export { claveLeyenda };
