// Diagrama de Gantt clínico: una fila por ítem, agrupadas en secciones
// colapsables (Condiciones, Prescripciones, Encuentros, Eventos/mes). Gutter
// izquierdo fijo con nombres; barras con línea "hoy", hitos en rombo y flechas
// de "en curso". Dos SVG: carriles scrolleables + eje/brush con escala fija.

import { useEffect, useRef, useState } from "react";
import * as d3 from "d3";
import { useEstado } from "@/estado";
import { COLOR_TIPO } from "@/paleta";
import { empaquetarFilas, type RangoTiempo } from "@/tiempo";
import type { Intervalos } from "@/tipos";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import {
  CalendarRange,
  ChevronDown,
  ChevronUp,
  GripHorizontal,
  Loader2,
  X,
} from "lucide-react";

const GUTTER = 190;
const MARGEN_DER = 14;
const ALTO_EJE = 34;
const ALTO_HEADER = 26;
const FILA_ITEM = 20; // fila por ítem (grupo expandido)
const FILA_COND = 18; // sub-fila lane-packed (grupo colapsado)
const FILA_RX = 16;
const ALTO_LANE_ENC = 34;
const ALTO_DENSIDAD = 72;
const ALTO_BARRA = 12;
const ESPACIO_GRUPO = 10;
const PAD_VERTICAL = 10;
const ALTURA_DEFAULT = 380;
const TIPOS_BIN = ["Observacion", "Procedimiento", "Inmunizacion", "Alergia"];
const DIA = 24 * 3600 * 1000;

type ClaveGrupo = "condiciones" | "prescripciones" | "encuentros" | "densidad";

const GRUPOS: { clave: ClaveGrupo; etiqueta: string; color: string; modo: "multi" | "lane" }[] = [
  { clave: "condiciones", etiqueta: "Condiciones", color: COLOR_TIPO.Condicion, modo: "multi" },
  { clave: "prescripciones", etiqueta: "Prescripciones", color: COLOR_TIPO.Prescripcion, modo: "multi" },
  { clave: "encuentros", etiqueta: "Encuentros", color: COLOR_TIPO.Encuentro, modo: "lane" },
  { clave: "densidad", etiqueta: "Eventos / mes", color: COLOR_TIPO.Observacion, modo: "lane" },
];

const INACTIVO = (estado?: string) =>
  estado === "resolved" || estado === "completed" || estado === "stopped";

interface DatoBarra {
  id: string;
  nombre: string;
  inicio: number;
  fin: number;
  estado?: string;
  fila: number; // sub-fila lane-packed (modo colapsado)
  puntual: boolean; // sin duración -> hito en rombo
  enCurso: boolean; // barra activa que llega a "hoy" -> flecha
}

interface DatoBin {
  clave: string;
  mes: number;
  tipo: string;
  y0: number;
  y1: number;
}

interface DatoEncuentro {
  id: string;
  inicio: number;
  tipo?: string;
  motivo?: string;
}

interface TooltipTL {
  titulo: string;
  sub: string;
  color: string;
  x: number;
  y: number;
}

interface Layout {
  headerY: number;
  y0: number;
  alto: number;
  colapsado: boolean;
}

interface CapasTimeline {
  hairlines: d3.Selection<SVGGElement, unknown, null, undefined>;
  overlay: d3.Selection<SVGGElement, unknown, null, undefined>;
  bins: d3.Selection<SVGGElement, unknown, null, undefined>;
  cond: d3.Selection<SVGGElement, unknown, null, undefined>;
  rx: d3.Selection<SVGGElement, unknown, null, undefined>;
  enc: d3.Selection<SVGGElement, unknown, null, undefined>;
  marcas: d3.Selection<SVGGElement, unknown, null, undefined>;
  hoy: d3.Selection<SVGGElement, unknown, null, undefined>;
  gutter: d3.Selection<SVGGElement, unknown, null, undefined>;
  eje: d3.Selection<SVGGElement, unknown, null, undefined>;
  brush: d3.Selection<SVGGElement, unknown, null, undefined>;
}

const rombo = d3.symbol(d3.symbolDiamond, 52);
const flechaDer = (x: number, cy: number) =>
  `M${x},${cy - 4.5}L${x + 7},${cy}L${x},${cy + 4.5}Z`;

function prepararDatos(iv: Intervalos, hoy: number) {
  const condiciones: DatoBarra[] = iv.condiciones
    .filter((c) => c.fecha_inicio)
    .map((c) => ({
      id: c.id,
      nombre: c.nombre,
      inicio: Date.parse(c.fecha_inicio!),
      fin: c.fecha_resolucion ? Date.parse(c.fecha_resolucion) : hoy,
      estado: c.estado,
      fila: 0,
      puntual: false,
      enCurso: !c.fecha_resolucion && !INACTIVO(c.estado),
    }))
    .sort((a, b) => a.inicio - b.inicio);
  empaquetarFilas(condiciones).forEach((fila, i) => (condiciones[i].fila = fila));

  const prescripciones: DatoBarra[] = iv.prescripciones
    .filter((rx) => rx.fecha_inicio)
    .map((rx) => {
      const inicio = Date.parse(rx.fecha_inicio!);
      const activa = rx.estado === "active";
      return {
        id: rx.id,
        nombre: rx.farmaco,
        inicio,
        fin: activa ? hoy : inicio,
        estado: rx.estado,
        fila: 0,
        puntual: !activa,
        enCurso: activa,
      };
    })
    .sort((a, b) => a.inicio - b.inicio);
  const MARGEN_RX = 90 * DIA;
  empaquetarFilas(
    prescripciones.map((r) => ({ inicio: r.inicio, fin: Math.max(r.fin, r.inicio + MARGEN_RX) })),
  ).forEach((fila, i) => (prescripciones[i].fila = fila));

  const encuentros: DatoEncuentro[] = iv.encuentros
    .filter((e) => e.fecha_inicio)
    .map((e) => ({ id: e.id, inicio: Date.parse(e.fecha_inicio), tipo: e.tipo, motivo: e.motivo }));

  const porMes = d3.group(iv.bins, (b) => b.mes);
  const bins: DatoBin[] = [];
  let maxMes = 1;
  for (const [mes, filas] of porMes) {
    const ts = Date.parse(`${mes}-01T00:00:00Z`);
    let acum = 0;
    for (const tipo of TIPOS_BIN) {
      const n = filas.find((f) => f.tipo === tipo)?.n ?? 0;
      if (n > 0) {
        bins.push({ clave: `${mes}|${tipo}`, mes: ts, tipo, y0: acum, y1: acum + n });
        acum += n;
      }
    }
    maxMes = Math.max(maxMes, acum);
  }

  const fechas = [
    ...condiciones.map((c) => c.inicio),
    ...prescripciones.map((r) => r.inicio),
    ...encuentros.map((e) => e.inicio),
    ...bins.map((b) => b.mes),
  ];
  const minFecha = fechas.length ? Math.min(...fechas) : hoy - 365 * DIA;
  const nFilasCond = Math.max(1, ...condiciones.map((c) => c.fila + 1));
  const nFilasRx = Math.max(1, ...prescripciones.map((r) => r.fila + 1));
  return { condiciones, prescripciones, encuentros, bins, maxMes, minFecha, nFilasCond, nFilasRx };
}

type Datos = ReturnType<typeof prepararDatos>;

function recortar(texto: string, ancho: number): string {
  if (ancho < 46) return "";
  const max = Math.max(3, Math.floor((ancho - 8) / 6));
  return texto.length > max ? `${texto.slice(0, max - 1)}…` : texto;
}

function recortarGutter(texto: string, px: number): string {
  const max = Math.max(3, Math.floor(px / 6.1));
  return texto.length > max ? `${texto.slice(0, max - 1)}…` : texto;
}

function fmt(ts: number): string {
  return new Date(ts).toISOString().slice(0, 10);
}

export function VistaTemporal() {
  const raizRef = useRef<HTMLDivElement>(null);
  const contRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const ejeSvgRef = useRef<SVGSVGElement>(null);
  const capasRef = useRef<CapasTimeline | null>(null);
  const datosRef = useRef<Datos | null>(null);
  const escalaBaseRef = useRef<d3.ScaleTime<number, number> | null>(null);
  const transformRef = useRef<d3.ZoomTransform>(d3.zoomIdentity);
  const zoomRef = useRef<d3.ZoomBehavior<SVGSVGElement, unknown> | null>(null);
  const brushRef = useRef<d3.BrushBehavior<unknown> | null>(null);
  const brushProgRef = useRef(false);
  const rangoRef = useRef<RangoTiempo>(null);
  const rafRef = useRef(0);
  const dimRef = useRef({ w: 0, h: 0 });
  const hoyRef = useRef(Date.now());
  const redibujarRef = useRef<() => void>(() => {});
  const resizeRef = useRef<{ y: number; altura: number } | null>(null);

  const [tooltip, setTooltip] = useState<TooltipTL | null>(null);
  const [redimensionando, setRedimensionando] = useState(false);

  const pacienteId = useEstado((s) => s.pacienteId);
  const intervalos = useEstado((s) => s.intervalos);
  const timelineAbierta = useEstado((s) => s.timelineAbierta);
  const timelineAltura = useEstado((s) => s.timelineAltura);
  const alternarTimeline = useEstado((s) => s.alternarTimeline);
  const fijarTimelineAltura = useEstado((s) => s.fijarTimelineAltura);
  const rangoTiempo = useEstado((s) => s.rangoTiempo);
  const resaltados = useEstado((s) => s.resaltados);
  const gruposColapsados = useEstado((s) => s.gruposColapsados);

  function escalaActual() {
    const base = escalaBaseRef.current;
    return base ? transformRef.current.rescaleX(base) : null;
  }

  function empujarRango(rango: RangoTiempo, inmediato = false) {
    rangoRef.current = rango;
    if (inmediato) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = 0;
      useEstado.getState().fijarRangoTiempo(rango);
      return;
    }
    if (!rafRef.current) {
      rafRef.current = requestAnimationFrame(() => {
        rafRef.current = 0;
        useEstado.getState().fijarRangoTiempo(rangoRef.current);
      });
    }
  }

  function mostrarTooltip(ev: MouseEvent, datos: Omit<TooltipTL, "x" | "y">) {
    const ancho = 300;
    const alto = 76;
    setTooltip({
      ...datos,
      x: Math.max(8, Math.min(window.innerWidth - ancho - 8, ev.clientX + 12)),
      y: Math.max(8, Math.min(window.innerHeight - alto - 8, ev.clientY - 42)),
    });
  }

  function dibujarOverlay(alto: number) {
    const capas = capasRef.current;
    const escala = escalaActual();
    if (!capas || !escala) return;
    const rango = rangoRef.current;
    const datos = rango ? [[escala(new Date(rango[0])), escala(new Date(rango[1]))]] : [];
    capas.overlay
      .selectAll<SVGRectElement, number[]>("rect")
      .data(datos)
      .join("rect")
      .attr("x", (d) => d[0])
      .attr("y", 0)
      .attr("width", (d) => Math.max(1, d[1] - d[0]))
      .attr("height", alto)
      .attr("fill", "#ffffff")
      .attr("fill-opacity", 0.055)
      .attr("stroke", "rgba(255,255,255,0.22)")
      .attr("pointer-events", "none");
  }

  useEffect(() => {
    const svg = d3.select(svgRef.current!);
    const ejeSvg = d3.select(ejeSvgRef.current!);
    // Recorte del área de trazado: las barras no invaden el gutter al hacer pan.
    svg
      .append("defs")
      .append("clipPath")
      .attr("id", "recorte-tl")
      .append("rect")
      .attr("class", "rect-recorte");
    const conRecorte = () => svg.append("g").attr("clip-path", "url(#recorte-tl)");
    const capas: CapasTimeline = {
      hairlines: conRecorte(),
      overlay: conRecorte(),
      bins: conRecorte(),
      cond: conRecorte(),
      rx: conRecorte(),
      enc: conRecorte(),
      marcas: conRecorte(),
      hoy: conRecorte(),
      gutter: svg.append("g"), // sin recorte, encima de todo
      eje: ejeSvg.append("g").attr("class", "eje-fijo"),
      brush: ejeSvg.append("g").attr("class", "grupo-brush"),
    };
    capasRef.current = capas;

    const zoom = d3
      .zoom<SVGSVGElement, unknown>()
      .scaleExtent([1, 60])
      .filter((ev: Event) => ev.type !== "wheel" || !(ev as WheelEvent).shiftKey)
      .on("zoom", (ev) => {
        transformRef.current = ev.transform;
        redibujarRef.current();
      });
    zoomRef.current = zoom;
    svg.call(zoom).on("dblclick.zoom", null);

    const brush = d3.brushX().on("brush end", (ev) => {
      if (brushProgRef.current) return;
      const escala = escalaActual();
      if (!escala) return;
      if (!ev.selection) {
        rangoRef.current = null;
        redibujarRef.current();
        if (ev.type === "end") empujarRango(null, true);
        return;
      }
      const [x0, x1] = ev.selection as [number, number];
      const rango: RangoTiempo = [escala.invert(x0).getTime(), escala.invert(x1).getTime()];
      rangoRef.current = rango;
      redibujarRef.current();
      empujarRango(rango, ev.type === "end");
    });
    brushRef.current = brush;
    capas.brush.call(brush);

    const observar = new ResizeObserver(([entrada]) => {
      dimRef.current = { w: entrada.contentRect.width, h: entrada.contentRect.height };
      redibujarRef.current();
    });
    observar.observe(contRef.current!);

    return () => {
      observar.disconnect();
      cancelAnimationFrame(rafRef.current);
      svg.selectAll("*").remove();
      ejeSvg.selectAll("*").remove();
    };
  }, []);

  useEffect(() => {
    redibujarRef.current = () => {
      const capas = capasRef.current;
      const datos = datosRef.current;
      const { w, h } = dimRef.current;
      if (!capas || !datos || w < 180 || h < 80) return;
      const hoy = hoyRef.current;
      const { resaltados: res, nodos, gruposColapsados: col, expandirNodo, alternarGrupoTimeline } =
        useEstado.getState();
      const hayResaltados = res.size > 0;
      const claseEl = (id: string) =>
        cn("tl-el", res.has(id) && "resaltado", hayResaltados && !res.has(id) && "atenuado");

      const margen = Math.max(86400000, (hoy - datos.minFecha) * 0.02);
      escalaBaseRef.current = d3
        .scaleUtc()
        .domain([new Date(datos.minFecha - margen), new Date(hoy + margen)])
        .range([GUTTER, w - MARGEN_DER]);
      const escala = escalaActual()!;

      // --- layout vertical de grupos ---
      const L: Record<ClaveGrupo, Layout> = {} as Record<ClaveGrupo, Layout>;
      let y = PAD_VERTICAL;
      for (const g of GRUPOS) {
        const colapsado = !!col[g.clave];
        const headerY = y;
        y += ALTO_HEADER;
        let alto = 0;
        if (g.clave === "condiciones") {
          alto = colapsado
            ? datos.nFilasCond * FILA_COND
            : Math.max(FILA_ITEM, datos.condiciones.length * FILA_ITEM);
        } else if (g.clave === "prescripciones") {
          alto = colapsado
            ? datos.nFilasRx * FILA_RX
            : Math.max(FILA_ITEM, datos.prescripciones.length * FILA_ITEM);
        } else if (g.clave === "encuentros") {
          alto = colapsado ? 0 : ALTO_LANE_ENC;
        } else {
          alto = colapsado ? 0 : ALTO_DENSIDAD;
        }
        L[g.clave] = { headerY, y0: y, alto, colapsado };
        y += alto + ESPACIO_GRUPO;
      }
      const altoContenido = Math.max(h, y + PAD_VERTICAL);

      d3.select(svgRef.current!)
        .attr("width", w)
        .attr("height", altoContenido)
        .attr("viewBox", `0 0 ${w} ${altoContenido}`);
      d3.select(ejeSvgRef.current!).attr("width", w).attr("height", ALTO_EJE);
      d3.select(svgRef.current!)
        .select(".rect-recorte")
        .attr("x", GUTTER)
        .attr("y", 0)
        .attr("width", Math.max(1, w - MARGEN_DER - GUTTER))
        .attr("height", altoContenido);

      // --- eje inferior fijo + hairlines ---
      const ticks = escala.ticks(Math.max(3, Math.floor((w - GUTTER) / 105)));
      const span = escala.domain()[1].getTime() - escala.domain()[0].getTime();
      const formato = span < 3 * 365 * 86400000 ? d3.utcFormat("%b %Y") : d3.utcFormat("%Y");
      const eje = d3.axisBottom(escala).tickValues(ticks).tickFormat(formato as never).tickSizeOuter(0);
      const ejeSel = capas.eje.attr("transform", "translate(0,1)").call(eje as never);
      ejeSel.selectAll("text").attr("fill", "#9c9a93").attr("font-size", 11).attr("dy", "0.9em");
      ejeSel.selectAll("line").attr("stroke", "#44443f");
      ejeSel.select(".domain").attr("stroke", "#44443f");

      capas.hairlines
        .selectAll<SVGLineElement, Date>("line")
        .data(ticks, (d: Date) => +d)
        .join("line")
        .attr("x1", (d) => escala(d))
        .attr("x2", (d) => escala(d))
        .attr("y1", 0)
        .attr("y2", altoContenido)
        .attr("stroke", "#2c2c2a")
        .attr("stroke-width", 1);

      // --- Condiciones y Prescripciones (barras / hitos por ítem o lane-packed) ---
      const pintarBarras = (
        capa: d3.Selection<SVGGElement, unknown, null, undefined>,
        items: DatoBarra[],
        lay: Layout,
        color: string,
        filaAlto: number,
      ) => {
        const yDe = (d: DatoBarra, i: number) =>
          lay.colapsado ? lay.y0 + d.fila * filaAlto : lay.y0 + i * FILA_ITEM;
        const g = capa
          .selectAll<SVGGElement, DatoBarra>("g.tl-el")
          .data(items, (d) => d.id)
          .join((enter) => {
            const e = enter.append("g");
            e.append("rect").attr("class", "barra");
            e.append("path").attr("class", "hito");
            e.append("path").attr("class", "flecha");
            e.append("text").attr("font-size", 10.5).attr("fill", "#e6e4dc").attr("pointer-events", "none");
            return e;
          });
        g.attr("class", (d) => cn("gantt-barra", claseEl(d.id)))
          .on("click", (_ev, d) => void expandirNodo(d.id))
          .on("mouseenter mousemove", (ev: MouseEvent, d) =>
            mostrarTooltip(ev, {
              titulo: d.nombre,
              sub: d.puntual
                ? `${fmt(d.inicio)} · ${d.estado} (fin no registrado en Synthea)`
                : `${fmt(d.inicio)} → ${d.enCurso ? "hoy (activa)" : fmt(d.fin)}`,
              color,
            }),
          )
          .on("mouseleave", () => setTooltip(null));

        const cy = (d: DatoBarra, i: number) => yDe(d, i) + filaAlto / 2;
        // Barra (ítems con duración)
        g.select<SVGRectElement>("rect.barra")
          .attr("display", (d) => (d.puntual ? "none" : null))
          .attr("x", (d) => escala(d.inicio))
          .attr("y", (d, i) => cy(d, i) - ALTO_BARRA / 2)
          .attr("width", (d) => Math.max(3, escala(d.fin) - escala(d.inicio)))
          .attr("height", ALTO_BARRA)
          .attr("rx", 3)
          .attr("fill", color)
          .attr("fill-opacity", (d) => (INACTIVO(d.estado) ? 0.22 : 0.9))
          .attr("stroke", color)
          .attr("stroke-width", 1);
        // Hito (rombo) para ítems puntuales
        g.select<SVGPathElement>("path.hito")
          .attr("display", (d) => (d.puntual ? null : "none"))
          .attr("d", rombo)
          .attr("transform", (d, i) => `translate(${escala(d.inicio)},${cy(d, i)})`)
          .attr("fill", color)
          .attr("fill-opacity", 0.55)
          .attr("stroke", color);
        // Flecha "en curso" al final de las barras activas
        g.select<SVGPathElement>("path.flecha")
          .attr("display", (d) => (d.enCurso && !d.puntual ? null : "none"))
          .attr("d", (d, i) => flechaDer(escala(d.fin), cy(d, i)))
          .attr("fill", color);
        // Etiqueta dentro de la barra solo en modo colapsado (en expandido va al gutter)
        g.select<SVGTextElement>("text")
          .attr("x", (d) => escala(d.inicio) + 6)
          .attr("y", (d, i) => cy(d, i) + 3.5)
          .text((d) =>
            lay.colapsado && !d.puntual ? recortar(d.nombre, escala(d.fin) - escala(d.inicio)) : "",
          );
      };

      pintarBarras(capas.cond, datos.condiciones, L.condiciones, COLOR_TIPO.Condicion, FILA_COND);
      pintarBarras(capas.rx, datos.prescripciones, L.prescripciones, COLOR_TIPO.Prescripcion, FILA_RX);

      // --- Encuentros (carril de hitos) ---
      const encVisibles = L.encuentros.colapsado ? [] : datos.encuentros;
      const yEnc = L.encuentros.y0 + ALTO_LANE_ENC / 2;
      capas.enc
        .selectAll<SVGPathElement, DatoEncuentro>("path")
        .data(encVisibles, (d) => d.id)
        .join("path")
        .attr("class", (d) => cn("gantt-hito", claseEl(d.id)))
        .attr("d", rombo)
        .attr("transform", (d) => `translate(${escala(d.inicio)},${yEnc})`)
        .attr("fill", COLOR_TIPO.Encuentro)
        .attr("fill-opacity", 0.9)
        .attr("stroke", COLOR_TIPO.Encuentro)
        .on("click", (_ev, d) => void useEstado.getState().expandirNodo(d.id))
        .on("mouseenter mousemove", (ev: MouseEvent, d) =>
          mostrarTooltip(ev, {
            titulo: `Encuentro (${d.tipo ?? "clínico"})`,
            sub: `${fmt(d.inicio)}${d.motivo ? ` · ${d.motivo}` : ""} · click para expandir`,
            color: COLOR_TIPO.Encuentro,
          }),
        )
        .on("mouseleave", () => setTooltip(null));

      // --- Densidad mensual (histograma apilado) ---
      const binsVisibles = L.densidad.colapsado ? [] : datos.bins;
      const escalaY = d3.scaleLinear().domain([0, datos.maxMes]).range([0, ALTO_DENSIDAD - 10]);
      const unMes = 30 * DIA;
      const baseBins = L.densidad.y0 + ALTO_DENSIDAD;
      capas.bins
        .selectAll<SVGRectElement, DatoBin>("rect")
        .data(binsVisibles, (d) => d.clave)
        .join("rect")
        .attr("x", (d) => escala(d.mes))
        .attr("width", (d) => Math.max(1.5, escala(d.mes + unMes) - escala(d.mes) - 0.5))
        .attr("y", (d) => baseBins - escalaY(d.y1))
        .attr("height", (d) => Math.max(1, escalaY(d.y1) - escalaY(d.y0)))
        .attr("fill", (d) => COLOR_TIPO[d.tipo] ?? COLOR_TIPO.Concepto)
        .attr("fill-opacity", 0.78)
        .on("mouseenter mousemove", (ev: MouseEvent, d) =>
          mostrarTooltip(ev, {
            titulo: `${d.y1 - d.y0} × ${d.tipo}`,
            sub: new Date(d.mes).toISOString().slice(0, 7),
            color: COLOR_TIPO[d.tipo] ?? COLOR_TIPO.Concepto,
          }),
        )
        .on("mouseleave", () => setTooltip(null));

      // Marcas de evidencia (triángulos) sobre el carril de densidad
      const marcas =
        hayResaltados && !L.densidad.colapsado
          ? nodos.filter((n) => res.has(n.id) && n.fecha && TIPOS_BIN.includes(n.tipo))
          : [];
      capas.marcas
        .selectAll<SVGPathElement, (typeof marcas)[0]>("path")
        .data(marcas, (d) => d.id)
        .join("path")
        .attr("class", "tl-el resaltado")
        .attr("d", d3.symbol(d3.symbolTriangle, 48))
        .attr("transform", (d) => `translate(${escala(Date.parse(d.fecha!))},${L.densidad.y0 - 6}) rotate(180)`)
        .attr("fill", (d) => COLOR_TIPO[d.tipo] ?? "#fff")
        .attr("stroke", "#ffffff");

      // --- Línea "hoy" (convención Gantt) ---
      const xHoy = escala(hoy);
      capas.hoy.selectAll<SVGGElement, number>("g").data([xHoy]).join(
        (enter) => {
          const g = enter.append("g");
          g.append("line").attr("class", "gantt-hoy");
          g.append("text").attr("class", "gantt-hoy-txt");
          return g;
        },
      );
      capas.hoy
        .select<SVGLineElement>("line")
        .attr("x1", xHoy)
        .attr("x2", xHoy)
        .attr("y1", 0)
        .attr("y2", altoContenido)
        .attr("stroke", COLOR_TIPO.Prescripcion)
        .attr("stroke-width", 1)
        .attr("stroke-dasharray", "3 3")
        .attr("stroke-opacity", 0.6);
      capas.hoy
        .select<SVGTextElement>("text")
        .attr("x", xHoy - 4)
        .attr("y", 10)
        .attr("text-anchor", "end")
        .attr("font-size", 9)
        .attr("fill", COLOR_TIPO.Prescripcion)
        .text("hoy");

      // --- Gutter izquierdo: fondo, cabeceras colapsables y nombres por ítem ---
      capas.gutter.selectAll("rect.gutter-bg").data([0]).join("rect")
        .attr("class", "gutter-bg")
        .attr("x", 0).attr("y", 0).attr("width", GUTTER - 1).attr("height", altoContenido)
        .attr("fill", "#161615");
      capas.gutter.selectAll("line.gutter-borde").data([0]).join("line")
        .attr("class", "gutter-borde")
        .attr("x1", GUTTER - 0.5).attr("x2", GUTTER - 0.5).attr("y1", 0).attr("y2", altoContenido)
        .attr("stroke", "#2c2c2a");

      const conteo: Record<ClaveGrupo, number> = {
        condiciones: datos.condiciones.length,
        prescripciones: datos.prescripciones.length,
        encuentros: datos.encuentros.length,
        densidad: datos.bins.reduce((s, b) => s + (b.y1 - b.y0), 0),
      };
      const gHead = capas.gutter
        .selectAll<SVGGElement, (typeof GRUPOS)[0]>("g.gantt-header")
        .data(GRUPOS, (d) => d.clave)
        .join((enter) => {
          const g = enter.append("g").attr("class", "gantt-header");
          g.append("rect").attr("class", "gantt-header-bg").attr("x", 0).attr("width", GUTTER - 1).attr("height", ALTO_HEADER).attr("fill", "transparent");
          g.append("text").attr("class", "chevron").attr("x", 10).attr("font-size", 10);
          g.append("text").attr("class", "titulo").attr("x", 24).attr("font-size", 11.5).attr("font-weight", 600);
          g.append("text").attr("class", "conteo").attr("x", GUTTER - 10).attr("text-anchor", "end").attr("font-size", 10.5).attr("fill", "#898781");
          return g;
        });
      gHead
        .on("click", (_ev, d) => alternarGrupoTimeline(d.clave))
        .attr("transform", (d) => `translate(0,${L[d.clave].headerY})`);
      gHead.select<SVGRectElement>("rect.gantt-header-bg").attr("y", 0);
      gHead.select<SVGTextElement>("text.chevron")
        .attr("y", ALTO_HEADER / 2 + 3.5)
        .attr("fill", (d) => d.color)
        .text((d) => (L[d.clave].colapsado ? "▸" : "▾"));
      gHead.select<SVGTextElement>("text.titulo")
        .attr("y", ALTO_HEADER / 2 + 4)
        .attr("fill", "#e6e4dc")
        .text((d) => d.etiqueta);
      gHead.select<SVGTextElement>("text.conteo")
        .attr("y", ALTO_HEADER / 2 + 4)
        .text((d) => conteo[d.clave]);

      // Nombres por ítem (solo grupos multi expandidos)
      interface FilaGutter { id: string; nombre: string; color: string; y: number }
      const itemsGutter: FilaGutter[] = [];
      if (!L.condiciones.colapsado)
        datos.condiciones.forEach((c, i) =>
          itemsGutter.push({ id: c.id, nombre: c.nombre, color: COLOR_TIPO.Condicion, y: L.condiciones.y0 + i * FILA_ITEM + FILA_ITEM / 2 }),
        );
      if (!L.prescripciones.colapsado)
        datos.prescripciones.forEach((r, i) =>
          itemsGutter.push({ id: r.id, nombre: r.nombre, color: COLOR_TIPO.Prescripcion, y: L.prescripciones.y0 + i * FILA_ITEM + FILA_ITEM / 2 }),
        );
      const gItem = capas.gutter
        .selectAll<SVGGElement, FilaGutter>("g.gantt-item")
        .data(itemsGutter, (d) => d.id)
        .join((enter) => {
          const g = enter.append("g").attr("class", "gantt-item");
          g.append("circle").attr("r", 2.5).attr("cx", 18);
          g.append("text").attr("class", "nombre").attr("x", 26).attr("font-size", 10.5);
          return g;
        });
      gItem
        .attr("transform", (d) => `translate(0,${d.y})`)
        .attr("class", (d) => cn("gantt-item", claseEl(d.id)))
        .on("click", (_ev, d) => void expandirNodo(d.id))
        .on("mouseenter mousemove", (ev: MouseEvent, d) =>
          mostrarTooltip(ev, { titulo: d.nombre, sub: "click para expandir en el grafo", color: d.color }),
        )
        .on("mouseleave", () => setTooltip(null));
      gItem.select<SVGCircleElement>("circle").attr("fill", (d) => d.color);
      gItem.select<SVGTextElement>("text.nombre")
        .attr("y", 3.5)
        .attr("fill", "#c3c2b7")
        .text((d) => recortarGutter(d.nombre, GUTTER - 34));

      // --- brush (banda del eje) ---
      if (brushRef.current) {
        brushRef.current.extent([[GUTTER, 0], [w - MARGEN_DER, ALTO_EJE]]);
        brushProgRef.current = true;
        capas.brush.call(brushRef.current as never);
        const rango = rangoRef.current;
        if (rango) {
          const x0 = Math.max(GUTTER, escala(new Date(rango[0])));
          const x1 = Math.min(w - MARGEN_DER, escala(new Date(rango[1])));
          capas.brush.call(brushRef.current.move as never, x1 > x0 ? ([x0, x1] as never) : (null as never));
        } else {
          capas.brush.call(brushRef.current.move as never, null as never);
        }
        brushProgRef.current = false;
        capas.brush.selectAll(".selection")
          .attr("fill", "#ffffff")
          .attr("fill-opacity", 0.13)
          .attr("stroke", "rgba(255,255,255,0.45)");
      }
      dibujarOverlay(altoContenido);
    };
    redibujarRef.current();
  }, []);

  useEffect(() => {
    hoyRef.current = Date.now();
    datosRef.current = intervalos ? prepararDatos(intervalos, hoyRef.current) : null;
    transformRef.current = d3.zoomIdentity;
    rangoRef.current = null;
    if (svgRef.current && zoomRef.current) {
      d3.select(svgRef.current).call(zoomRef.current.transform, d3.zoomIdentity);
    }
    if (!intervalos && capasRef.current) {
      for (const capa of Object.values(capasRef.current)) capa.selectAll("*").remove();
    }
    redibujarRef.current();
  }, [intervalos]);

  useEffect(() => {
    rangoRef.current = rangoTiempo;
    redibujarRef.current();
  }, [resaltados, rangoTiempo, timelineAbierta, timelineAltura, gruposColapsados]);

  const limpiarRango = () => {
    rangoRef.current = null;
    useEstado.getState().fijarRangoTiempo(null);
  };

  const limiteMaximo = () => {
    const altoPadre = raizRef.current?.parentElement?.clientHeight ?? 800;
    return Math.min(620, Math.max(280, altoPadre * 0.7));
  };

  useEffect(() => {
    if (!timelineAbierta) return;
    const ajustarAlViewport = () => {
      const maximo = limiteMaximo();
      if (useEstado.getState().timelineAltura > maximo) fijarTimelineAltura(maximo);
    };
    requestAnimationFrame(ajustarAlViewport);
    window.addEventListener("resize", ajustarAlViewport);
    return () => window.removeEventListener("resize", ajustarAlViewport);
  }, [timelineAbierta, fijarTimelineAltura]);

  const iniciarResize = (ev: React.PointerEvent<HTMLButtonElement>) => {
    ev.currentTarget.setPointerCapture(ev.pointerId);
    resizeRef.current = { y: ev.clientY, altura: timelineAltura };
    setRedimensionando(true);
  };

  const moverResize = (ev: React.PointerEvent<HTMLButtonElement>) => {
    if (!resizeRef.current) return;
    const siguiente = resizeRef.current.altura + resizeRef.current.y - ev.clientY;
    fijarTimelineAltura(Math.max(280, Math.min(limiteMaximo(), siguiente)));
  };

  const terminarResize = () => {
    resizeRef.current = null;
    setRedimensionando(false);
  };

  const tecladoResize = (ev: React.KeyboardEvent<HTMLButtonElement>) => {
    if (ev.key === "ArrowUp" || ev.key === "ArrowDown") {
      ev.preventDefault();
      const delta = ev.key === "ArrowUp" ? 24 : -24;
      fijarTimelineAltura(Math.max(280, Math.min(limiteMaximo(), timelineAltura + delta)));
    } else if (ev.key === "Home") {
      ev.preventDefault();
      fijarTimelineAltura(ALTURA_DEFAULT);
    }
  };

  return (
    <div
      ref={raizRef}
      className={cn(
        "relative flex shrink-0 flex-col border-t border-border bg-background",
        !redimensionando && "transition-[height] duration-200",
      )}
      style={{ height: timelineAbierta ? timelineAltura : 40 }}
    >
      {timelineAbierta && (
        <button
          role="separator"
          aria-label="Cambiar altura de la línea de tiempo"
          aria-orientation="horizontal"
          aria-valuemin={280}
          aria-valuemax={Math.round(limiteMaximo())}
          aria-valuenow={timelineAltura}
          className="group absolute -top-1.5 left-0 z-20 flex h-3 w-full cursor-row-resize items-center justify-center"
          onPointerDown={iniciarResize}
          onPointerMove={moverResize}
          onPointerUp={terminarResize}
          onLostPointerCapture={terminarResize}
          onDoubleClick={() => fijarTimelineAltura(ALTURA_DEFAULT)}
          onKeyDown={tecladoResize}
          title="Arrastra para cambiar la altura · doble clic para restaurar"
        >
          <span className="flex h-3 w-12 items-center justify-center rounded-full border border-border bg-background text-muted-foreground shadow-sm group-hover:text-foreground">
            <GripHorizontal className="size-3.5" />
          </span>
        </button>
      )}

      <div className="flex h-10 shrink-0 items-center gap-2 px-3">
        <CalendarRange className="size-4 text-primary" />
        <span className="truncate text-sm font-semibold">Línea de tiempo</span>
        {rangoTiempo && (
          <Badge variant="secondary" className="hidden gap-1 py-0 text-[11px] sm:inline-flex">
            {fmt(rangoTiempo[0])} – {fmt(rangoTiempo[1])}
            <button onClick={limpiarRango} title="Quitar filtro temporal" className="rounded hover:text-foreground">
              <X className="size-3" />
            </button>
          </Badge>
        )}
        {rangoTiempo && (
          <span
            className="size-2 rounded-full bg-primary sm:hidden"
            title={`${fmt(rangoTiempo[0])} – ${fmt(rangoTiempo[1])}`}
          />
        )}
        {timelineAbierta && (
          <span className="hidden truncate text-[11px] text-muted-foreground xl:inline">
            rueda = zoom · arrastra = desplazar · selecciona en el eje = filtrar · click en un grupo = colapsar
          </span>
        )}
        <button
          onClick={alternarTimeline}
          className="ml-auto rounded-md p-2 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          title={timelineAbierta ? "Colapsar línea de tiempo" : "Abrir línea de tiempo"}
          aria-label={timelineAbierta ? "Colapsar línea de tiempo" : "Abrir línea de tiempo"}
          aria-expanded={timelineAbierta}
        >
          {timelineAbierta ? <ChevronDown className="size-4" /> : <ChevronUp className="size-4" />}
        </button>
      </div>

      <div className={cn("min-h-0 flex-1 flex-col", timelineAbierta ? "flex" : "hidden")}>
        <div ref={contRef} className="timeline-scroll relative min-h-0 flex-1 overflow-y-auto overscroll-contain">
          <svg ref={svgRef} className="block min-w-full" />
          {pacienteId && !intervalos && (
            <div className="absolute inset-0 flex items-center justify-center">
              <Loader2 className="size-5 animate-spin text-muted-foreground" />
            </div>
          )}
          {!pacienteId && (
            <div className="absolute inset-0 flex items-center justify-center text-sm text-muted-foreground">
              Selecciona un paciente para ver su historia clínica en el tiempo
            </div>
          )}
        </div>
        <div className="h-[34px] shrink-0 border-t border-border bg-background/95">
          <svg ref={ejeSvgRef} className="h-full w-full" />
        </div>
      </div>

      {tooltip && (
        <div
          className="pointer-events-none fixed z-50 max-w-[300px] rounded-md border border-border bg-popover p-2.5 text-popover-foreground shadow-lg"
          style={{ left: tooltip.x, top: tooltip.y }}
        >
          <div className="flex items-center gap-1.5">
            <span className="size-2 rounded-full" style={{ background: tooltip.color }} />
            <span className="text-sm font-medium leading-tight">{tooltip.titulo}</span>
          </div>
          <p className="mt-1 text-xs text-muted-foreground">{tooltip.sub}</p>
        </div>
      )}
    </div>
  );
}
