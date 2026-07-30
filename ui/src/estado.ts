// Store global (zustand): suscripciones selectivas para que los deltas del
// stream SSE no re-rendericen el grafo, solo el panel de chat.

import { create } from "zustand";
import {
  chatSSE,
  obtenerGrafo,
  obtenerGrafoCompleto,
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
  grafoCompleto: boolean; // true tras "desplegar todo"
  idsNucleo: Set<string>; // ids del nucleo clinico inicial (para compactar)
  resaltados: Set<string>;
  tiposOcultos: Set<string>;
  mensajes: Mensaje[];
  streamActivo: boolean;
  abortCtrl: AbortController | null;
  sesiones: Record<string, string>; // pacienteId -> sesion_id

  // preferencias puramente visuales (persistidas en localStorage)
  chatAbierto: boolean;

  // vista temporal
  intervalos: Intervalos | null;
  timelineAbierta: boolean;
  timelineAltura: number;
  gruposColapsados: Record<string, boolean>; // clave de grupo del Gantt -> colapsado
  rangoTiempo: RangoTiempo;

  cargarPacientes(): Promise<void>;
  seleccionarPaciente(id: string): Promise<void>;
  expandirNodo(id: string): Promise<void>;
  alternarGrafoCompleto(): Promise<void>;
  fusionarGrafo(g: Grafo): void;
  alternarTipo(clave: string): void;
  resaltar(ids: string[]): void;
  vincularEvidencia(ids: string[]): Promise<void>;
  enviarMensaje(texto: string): Promise<void>;
  abortarStream(): void;
  alternarChat(): void;
  alternarTimeline(): void;
  alternarGrupoTimeline(clave: string): void;
  fijarTimelineAltura(altura: number): void;
  fijarRangoTiempo(rango: RangoTiempo): void;
}

const claveArista = (a: Arista) => `${a.origen}|${a.tipo}|${a.destino}`;

const CLAVE_PREFERENCIAS = "ehr-graph:ui:v1";
const ALTURA_TIMELINE_DEFAULT = 380;

interface PreferenciasUI {
  chatAbierto: boolean;
  timelineAbierta: boolean;
  timelineAltura: number;
  gruposColapsados: Record<string, boolean>;
}

function leerPreferencias(): PreferenciasUI {
  const base = {
    chatAbierto: true,
    timelineAbierta: true,
    timelineAltura: ALTURA_TIMELINE_DEFAULT,
    gruposColapsados: {},
  };
  try {
    const guardadas = JSON.parse(localStorage.getItem(CLAVE_PREFERENCIAS) ?? "null");
    if (!guardadas || typeof guardadas !== "object") return base;
    return {
      chatAbierto: typeof guardadas.chatAbierto === "boolean" ? guardadas.chatAbierto : true,
      timelineAbierta:
        typeof guardadas.timelineAbierta === "boolean" ? guardadas.timelineAbierta : true,
      timelineAltura:
        typeof guardadas.timelineAltura === "number"
          ? Math.max(280, Math.min(620, guardadas.timelineAltura))
          : ALTURA_TIMELINE_DEFAULT,
      gruposColapsados:
        guardadas.gruposColapsados && typeof guardadas.gruposColapsados === "object"
          ? guardadas.gruposColapsados
          : {},
    };
  } catch {
    return base;
  }
}

function guardarPreferencias(preferencias: PreferenciasUI) {
  try {
    localStorage.setItem(CLAVE_PREFERENCIAS, JSON.stringify(preferencias));
  } catch {
    // La UI sigue funcionando si el navegador bloquea almacenamiento local.
  }
}

const preferenciasIniciales = leerPreferencias();

export const useEstado = create<EstadoApp>((set, get) => ({
  pacientes: [],
  pacienteId: null,
  cargandoGrafo: false,
  nodos: [],
  aristas: [],
  versionGrafo: 0,
  grafoCompleto: false,
  idsNucleo: new Set(),
  resaltados: new Set(),
  tiposOcultos: new Set(),
  mensajes: [],
  streamActivo: false,
  abortCtrl: null,
  sesiones: {},
  chatAbierto: preferenciasIniciales.chatAbierto,
  intervalos: null,
  timelineAbierta: preferenciasIniciales.timelineAbierta,
  timelineAltura: preferenciasIniciales.timelineAltura,
  gruposColapsados: preferenciasIniciales.gruposColapsados,
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
      grafoCompleto: false,
      idsNucleo: new Set<string>(),
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
        idsNucleo: new Set(g.nodos.map((n) => n.id)),
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

  // Despliega TODO el grafo EHR del paciente o lo compacta al nucleo inicial.
  async alternarGrafoCompleto() {
    const { pacienteId, grafoCompleto, cargandoGrafo } = get();
    if (!pacienteId || cargandoGrafo) return;
    if (grafoCompleto) {
      // Compactar: conservar solo el nucleo (sin llamada de red, mantiene posiciones).
      set((s) => {
        const idsNucleo = s.idsNucleo;
        return {
          nodos: s.nodos.filter((n) => idsNucleo.has(n.id)),
          aristas: s.aristas.filter(
            (a) => idsNucleo.has(a.origen) && idsNucleo.has(a.destino),
          ),
          grafoCompleto: false,
          versionGrafo: s.versionGrafo + 1,
        };
      });
      return;
    }
    set({ cargandoGrafo: true });
    try {
      const g = await obtenerGrafoCompleto(pacienteId);
      if (get().pacienteId !== pacienteId) return; // cambio de paciente durante la carga
      get().fusionarGrafo(g); // merge deduplicado: preserva las posiciones actuales
      set({ grafoCompleto: true, cargandoGrafo: false });
    } catch {
      set({ cargandoGrafo: false });
    }
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
        const detalle = e instanceof Error ? e.message : "No se pudo conectar con la demo";
        actualizarUltimo((m) => ({
          ...m,
          error: true,
          partes: [...m.partes, { tipo: "texto", texto: detalle }],
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

  alternarChat() {
    set((s) => {
      const chatAbierto = !s.chatAbierto;
      guardarPreferencias({
        chatAbierto,
        timelineAbierta: s.timelineAbierta,
        timelineAltura: s.timelineAltura,
        gruposColapsados: s.gruposColapsados,
      });
      return { chatAbierto };
    });
  },

  alternarTimeline() {
    set((s) => {
      const timelineAbierta = !s.timelineAbierta;
      guardarPreferencias({
        chatAbierto: s.chatAbierto,
        timelineAbierta,
        timelineAltura: s.timelineAltura,
        gruposColapsados: s.gruposColapsados,
      });
      return { timelineAbierta };
    });
  },

  alternarGrupoTimeline(clave) {
    set((s) => {
      const gruposColapsados = { ...s.gruposColapsados, [clave]: !s.gruposColapsados[clave] };
      guardarPreferencias({
        chatAbierto: s.chatAbierto,
        timelineAbierta: s.timelineAbierta,
        timelineAltura: s.timelineAltura,
        gruposColapsados,
      });
      return { gruposColapsados };
    });
  },

  fijarTimelineAltura(altura) {
    set((s) => {
      const timelineAltura = Math.max(280, Math.min(620, Math.round(altura)));
      guardarPreferencias({
        chatAbierto: s.chatAbierto,
        timelineAbierta: s.timelineAbierta,
        timelineAltura,
        gruposColapsados: s.gruposColapsados,
      });
      return { timelineAltura };
    });
  },

  // El throttle (rAF) vive en VistaTemporal; aquí solo el set.
  fijarRangoTiempo(rango) {
    set({ rangoTiempo: rango });
  },
}));

export { claveLeyenda };
