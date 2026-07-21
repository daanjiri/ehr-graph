// Grafo force-directed sobre SVG. D3 es dueño del interior del SVG (refs +
// data-join); React solo posee el contenedor, el tooltip y los estados vacíos.
// La simulación se crea una vez y se alimenta incrementalmente: expandir un
// nodo no recoloca el resto del grafo.

import { useEffect, useRef, useState } from "react";
import * as d3 from "d3";
import { useEstado } from "@/estado";
import {
  claveLeyenda,
  colorNodo,
  esConcepto,
  estiloArista,
  muestraEtiqueta,
  radioNodo,
  rellenoNodo,
} from "@/paleta";
import type { NodoGrafo } from "@/tipos";
import { vigenteEn } from "@/tiempo";
import { Loader2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";

interface EnlaceSim extends d3.SimulationLinkDatum<NodoGrafo> {
  tipo: string;
  clave: string;
}

interface Selecciones {
  nodos: d3.Selection<SVGGElement, NodoGrafo, SVGGElement, unknown>;
  aristas: d3.Selection<SVGLineElement, EnlaceSim, SVGGElement, unknown>;
}

const idExtremo = (extremo: string | number | NodoGrafo): string =>
  typeof extremo === "object" ? extremo.id : String(extremo);

function distanciaEnlace(tipo: string): number {
  if (tipo === "DE_PACIENTE") return 130;
  if (tipo === "TRATA" || tipo === "INDICADO_POR") return 70;
  return 55;
}

export function GrafoPaciente() {
  const contenedorRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const simRef = useRef<d3.Simulation<NodoGrafo, EnlaceSim> | null>(null);
  const gRef = useRef<{ aristas: SVGGElement; nodos: SVGGElement } | null>(null);
  const selRef = useRef<Selecciones | null>(null);
  const primeraVezRef = useRef(true);

  const [tooltip, setTooltip] = useState<{ nodo: NodoGrafo; x: number; y: number } | null>(null);

  const pacienteId = useEstado((s) => s.pacienteId);
  const cargandoGrafo = useEstado((s) => s.cargandoGrafo);
  const versionGrafo = useEstado((s) => s.versionGrafo);
  const resaltados = useEstado((s) => s.resaltados);
  const rangoTiempo = useEstado((s) => s.rangoTiempo);

  // --- montaje: estructura SVG, zoom y simulación (una sola vez) ---
  useEffect(() => {
    const svg = d3.select(svgRef.current!);
    const defs = svg.append("defs");
    defs
      .append("marker")
      .attr("id", "flecha")
      .attr("viewBox", "0 -5 10 10")
      .attr("refX", 20)
      .attr("refY", 0)
      .attr("markerWidth", 5)
      .attr("markerHeight", 5)
      .attr("orient", "auto")
      .append("path")
      .attr("d", "M0,-5L10,0L0,5")
      .attr("fill", "#c3c2b7");

    const raiz = svg.append("g").attr("class", "zoom-root");
    const gAristas = raiz.append("g").attr("class", "capa-aristas");
    const gNodos = raiz.append("g").attr("class", "capa-nodos");
    gRef.current = { aristas: gAristas.node()!, nodos: gNodos.node()! };

    const zoom = d3
      .zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.15, 4])
      .on("zoom", (ev) => raiz.attr("transform", ev.transform));
    svg.call(zoom).on("dblclick.zoom", null);

    const sim = d3
      .forceSimulation<NodoGrafo>()
      .force(
        "enlace",
        d3
          .forceLink<NodoGrafo, EnlaceSim>()
          .id((d) => d.id)
          .distance((l) => distanciaEnlace(l.tipo))
          .strength(0.5),
      )
      .force("carga", d3.forceManyBody().strength(-280))
      .force("colision", d3.forceCollide<NodoGrafo>().radius((d) => radioNodo(d) + 7))
      .force("x", d3.forceX(0).strength(0.035))
      .force("y", d3.forceY(0).strength(0.035))
      .on("tick", () => {
        const sel = selRef.current;
        if (!sel) return;
        sel.aristas
          .attr("x1", (d) => (d.source as NodoGrafo).x ?? 0)
          .attr("y1", (d) => (d.source as NodoGrafo).y ?? 0)
          .attr("x2", (d) => (d.target as NodoGrafo).x ?? 0)
          .attr("y2", (d) => (d.target as NodoGrafo).y ?? 0);
        sel.nodos.attr("transform", (d) => `translate(${d.x ?? 0},${d.y ?? 0})`);
      });
    simRef.current = sim;

    // viewBox centrado en el origen, actualizado con el tamaño real
    const observar = new ResizeObserver(([entrada]) => {
      const { width, height } = entrada.contentRect;
      svg.attr("viewBox", [-width / 2, -height / 2, width, height].join(" "));
    });
    observar.observe(contenedorRef.current!);

    return () => {
      observar.disconnect();
      sim.stop();
      svg.selectAll("*").remove();
    };
  }, []);

  // el paciente cambia -> el próximo join arranca la simulación en caliente
  useEffect(() => {
    primeraVezRef.current = true;
  }, [pacienteId]);

  // --- data-join incremental en cada cambio de grafo o visibilidad ---
  useEffect(() => {
    const sim = simRef.current;
    const capas = gRef.current;
    if (!sim || !capas) return;
    const { nodos, aristas, tiposOcultos, expandirNodo } = useEstado.getState();

    const visibles = nodos.filter((n) => !tiposOcultos.has(claveLeyenda(n.tipo)));
    const idsVisibles = new Set(visibles.map((n) => n.id));
    const enlaces: EnlaceSim[] = aristas
      .filter((a) => idsVisibles.has(a.origen) && idsVisibles.has(a.destino))
      .map((a) => ({
        source: a.origen,
        target: a.destino,
        tipo: a.tipo,
        clave: `${a.origen}|${a.tipo}|${a.destino}`,
      }));

    // nodos nuevos entran junto a un vecino ya posicionado (evita saltos)
    const porId = new Map(visibles.map((n) => [n.id, n]));
    for (const n of visibles) {
      if (n.x == null) {
        const enlace = enlaces.find((e) => e.source === n.id || e.target === n.id);
        const vecinoId = enlace
          ? idExtremo(enlace.source === n.id ? enlace.target : enlace.source)
          : null;
        const vecino = vecinoId ? porId.get(vecinoId) : null;
        n.x = (vecino?.x ?? 0) + (Math.random() - 0.5) * 80;
        n.y = (vecino?.y ?? 0) + (Math.random() - 0.5) * 80;
      }
    }

    const selAristas = d3
      .select(capas.aristas)
      .selectAll<SVGLineElement, EnlaceSim>("line")
      .data(enlaces, (d) => d.clave)
      .join("line")
      .attr("class", "arista")
      .attr("stroke", (d) => estiloArista(d.tipo).color)
      .attr("stroke-width", (d) => estiloArista(d.tipo).ancho)
      .attr("stroke-dasharray", (d) => estiloArista(d.tipo).guiones ?? null)
      .attr("marker-end", (d) => (estiloArista(d.tipo).flecha ? "url(#flecha)" : null))
      .attr("stroke-opacity", 0.85);

    const drag = d3
      .drag<SVGGElement, NodoGrafo>()
      .on("start", (ev, d) => {
        if (!ev.active) sim.alphaTarget(0.25).restart();
        d.fx = d.x;
        d.fy = d.y;
      })
      .on("drag", (ev, d) => {
        d.fx = ev.x;
        d.fy = ev.y;
      })
      .on("end", (ev) => {
        if (!ev.active) sim.alphaTarget(0); // el nodo queda fijado donde se soltó
      });

    const selNodos = d3
      .select(capas.nodos)
      .selectAll<SVGGElement, NodoGrafo>("g.nodo")
      .data(visibles, (d) => d.id)
      .join((enter) => {
        const g = enter.append("g").attr("class", "nodo");
        g.each(function (d) {
          const sel = d3.select(this);
          const r = radioNodo(d);
          if (esConcepto(d.tipo)) {
            sel
              .append("rect")
              .attr("class", "forma")
              .attr("x", -r)
              .attr("y", -r)
              .attr("width", r * 2)
              .attr("height", r * 2)
              .attr("rx", 2)
              .attr("transform", "rotate(45)");
          } else {
            sel.append("circle").attr("class", "forma").attr("r", r);
          }
          sel
            .append("text")
            .attr("class", "etiqueta")
            .attr("text-anchor", "middle")
            .attr("dy", r + 13)
            .attr("font-size", d.tipo === "Paciente" ? 12 : 9.5)
            .attr("font-weight", d.tipo === "Paciente" ? 600 : 400)
            .attr("fill", d.tipo === "Paciente" ? "#ffffff" : "#c3c2b7")
            .text(
              muestraEtiqueta(d.tipo)
                ? d.etiqueta.length > 22
                  ? d.etiqueta.slice(0, 21) + "…"
                  : d.etiqueta
                : "",
            );
        });
        g.call(drag)
          .on("click", (_ev, d) => void expandirNodo(d.id))
          .on("dblclick", (_ev, d) => {
            if (d.tipo === "Paciente") return; // el hub queda anclado
            d.fx = null;
            d.fy = null;
            sim.alpha(0.2).restart();
          })
          .on("mouseenter", (ev: MouseEvent, d) =>
            setTooltip({ nodo: d, x: ev.clientX, y: ev.clientY }),
          )
          .on("mousemove", (ev: MouseEvent, d) =>
            setTooltip({ nodo: d, x: ev.clientX, y: ev.clientY }),
          )
          .on("mouseleave", () => setTooltip(null));
        return g;
      });

    // atributos que dependen del estado (relleno activo/hueco) en cada pasada
    selNodos
      .select<SVGElement>(".forma")
      .attr("fill", (d) => rellenoNodo(d))
      .attr("stroke", (d) => (d.tipo === "Paciente" ? "#ffffff" : colorNodo(d)))
      .attr("stroke-width", (d) => (d.tipo === "Paciente" ? 2 : 1.5));

    selRef.current = { nodos: selNodos, aristas: selAristas };

    sim.nodes(visibles);
    (sim.force("enlace") as d3.ForceLink<NodoGrafo, EnlaceSim>).links(enlaces);
    sim.alpha(primeraVezRef.current ? 0.9 : 0.3).restart();
    primeraVezRef.current = false;
  }, [versionGrafo]);

  // --- resaltado de evidencia: solo clases CSS, sin re-join ---
  useEffect(() => {
    const sel = selRef.current;
    if (!sel) return;
    const activo = resaltados.size > 0;
    sel.nodos
      .classed("resaltado", (d) => resaltados.has(d.id))
      .classed("atenuado", (d) => activo && !resaltados.has(d.id) && d.tipo !== "Paciente");
    sel.aristas.classed(
      "atenuada",
      (d) =>
        activo &&
        !(resaltados.has(idExtremo(d.source)) && resaltados.has(idExtremo(d.target))),
    );
  }, [resaltados, versionGrafo]);

  // --- scrubber temporal: atenuar lo no vigente en el rango (solo clases) ---
  useEffect(() => {
    const sel = selRef.current;
    if (!sel) return;
    const porId = new Map(useEstado.getState().nodos.map((n) => [n.id, n]));
    const vigente = (extremo: string | number | NodoGrafo) => {
      const n = typeof extremo === "object" ? extremo : porId.get(String(extremo));
      return !n || vigenteEn(n, rangoTiempo);
    };
    sel.nodos.classed("fuera-de-tiempo", (d) => !vigenteEn(d, rangoTiempo));
    sel.aristas.classed(
      "fuera-de-tiempo",
      (d) => !(vigente(d.source) && vigente(d.target)),
    );
  }, [rangoTiempo, versionGrafo]);

  return (
    <div ref={contenedorRef} className="relative h-full w-full overflow-hidden">
      <svg ref={svgRef} className="h-full w-full" />

      {!pacienteId && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-muted-foreground">
          <p className="text-lg font-medium text-secondary-foreground">
            Selecciona un paciente
          </p>
          <p className="max-w-sm text-center text-sm">
            Verás su núcleo clínico (condiciones, medicación y fármacos). Haz click en
            un nodo para expandir sus vecinos y pregunta lo que quieras en el chat.
          </p>
        </div>
      )}

      {cargandoGrafo && (
        <div className="absolute inset-0 flex items-center justify-center">
          <Loader2 className="size-6 animate-spin text-muted-foreground" />
        </div>
      )}

      {tooltip && (
        <div
          className="pointer-events-none fixed z-50 max-w-xs rounded-md border border-border bg-popover p-3 text-popover-foreground shadow-lg"
          style={{ left: tooltip.x + 14, top: tooltip.y + 14 }}
        >
          <div className="mb-1 flex items-center gap-2">
            <span
              className="inline-block size-2.5 rounded-full"
              style={{ background: colorNodo(tooltip.nodo) }}
            />
            <span className="text-xs font-semibold">{tooltip.nodo.tipo}</span>
            {tooltip.nodo.estado && (
              <Badge variant="outline" className="px-1.5 py-0 text-[10px]">
                {tooltip.nodo.estado}
              </Badge>
            )}
          </div>
          <p className="text-sm leading-snug">
            {tooltip.nodo.descripcion ?? tooltip.nodo.etiqueta}
          </p>
          {tooltip.nodo.fecha && (
            <p className="mt-1 text-xs text-muted-foreground">
              {tooltip.nodo.fecha.slice(0, 10)}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
