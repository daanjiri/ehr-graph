// Línea de tiempo por capas de duración clínica (crónico arriba → puntual
// abajo). D3 es dueño del interior del SVG; React posee cabecera, tooltip y
// estados vacíos. Gestos: rueda = zoom horizontal, arrastre en carriles = pan,
// arrastre en la banda del eje = brush (scrubber compartido con el grafo).

import { useEffect, useRef, useState } from "react";
import * as d3 from "d3";
import { useEstado } from "@/estado";
import { COLOR_TIPO } from "@/paleta";
import { empaquetarFilas, type RangoTiempo } from "@/tiempo";
import type { Intervalos } from "@/tipos";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { CalendarRange, ChevronDown, ChevronUp, Loader2, X } from "lucide-react";

const GUTTER = 92;
const MARGEN_DER = 10;
const ALTO_EJE = 26;
const ALTO_DENSIDAD = 56;
const ALTO_ENCUENTROS = 24;
const ALTO_RX = 70;
const TIPOS_BIN = ["Observacion", "Procedimiento", "Inmunizacion", "Alergia"];
const SUPERFICIE = "#1a1a19";

const INACTIVO = (estado?: string) =>
  estado === "resolved" || estado === "completed" || estado === "stopped";

interface DatoBarra {
  id: string;
  nombre: string;
  inicio: number;
  fin: number;
  estado?: string;
  fila: number;
  puntual: boolean; // prescripcion completed: sin fin conocido (Synthea)
}

interface DatoBin {
  clave: string;
  mes: number; // timestamp del primer día
  tipo: string;
  y0: number;
  y1: number;
}

interface TooltipTL {
  titulo: string;
  sub: string;
  color: string;
  x: number;
  y: number;
}

function prepararDatos(iv: Intervalos, hoy: number) {
  const condiciones: DatoBarra[] = iv.condiciones
    .filter((c) => c.fecha_inicio)
    .map((c) => {
      const inicio = Date.parse(c.fecha_inicio!);
      const fin = c.fecha_resolucion ? Date.parse(c.fecha_resolucion) : hoy;
      return { id: c.id, nombre: c.nombre, inicio, fin, estado: c.estado, fila: 0, puntual: false };
    })
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
      };
    })
    .sort((a, b) => a.inicio - b.inicio);
  // margen de 90 días para que los ticks puntuales no se apilen en la misma fila
  const MARGEN_RX = 90 * 24 * 3600 * 1000;
  empaquetarFilas(
    prescripciones.map((r) => ({ inicio: r.inicio, fin: Math.max(r.fin, r.inicio + MARGEN_RX) })),
  ).forEach((fila, i) => (prescripciones[i].fila = fila));

  const encuentros = iv.encuentros
    .filter((e) => e.fecha_inicio)
    .map((e) => ({
      id: e.id,
      inicio: Date.parse(e.fecha_inicio),
      tipo: e.tipo,
      motivo: e.motivo,
    }));

  // bins apilados por mes en orden fijo de tipos
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
  const minFecha = fechas.length ? Math.min(...fechas) : hoy - 365 * 24 * 3600 * 1000;
  return { condiciones, prescripciones, encuentros, bins, maxMes, minFecha };
}

type Datos = ReturnType<typeof prepararDatos>;

export function VistaTemporal() {
  const contRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const capasRef = useRef<Record<string, d3.Selection<SVGGElement, unknown, null, undefined>>>({});
  const datosRef = useRef<Datos | null>(null);
  const escalaBaseRef = useRef<d3.ScaleTime<number, number> | null>(null);
  const transformRef = useRef<d3.ZoomTransform>(d3.zoomIdentity);
  const brushRef = useRef<d3.BrushBehavior<unknown> | null>(null);
  const brushProgRef = useRef(false);
  const rangoRef = useRef<RangoTiempo>(null);
  const rafRef = useRef(0);
  const dimRef = useRef({ w: 0, h: 0 });
  const hoyRef = useRef(Date.now());
  const redibujarRef = useRef<() => void>(() => {});

  const [tooltip, setTooltip] = useState<TooltipTL | null>(null);

  const pacienteId = useEstado((s) => s.pacienteId);
  const intervalos = useEstado((s) => s.intervalos);
  const timelineAbierta = useEstado((s) => s.timelineAbierta);
  const alternarTimeline = useEstado((s) => s.alternarTimeline);
  const rangoTiempo = useEstado((s) => s.rangoTiempo);
  const resaltados = useEstado((s) => s.resaltados);

  // --- montaje: estructura del SVG, zoom, brush, resize (una vez) ---
  useEffect(() => {
    const svg = d3.select(svgRef.current!);
    const capas = {
      hairlines: svg.append("g"),
      bins: svg.append("g"),
      cond: svg.append("g"),
      rx: svg.append("g"),
      enc: svg.append("g"),
      marcas: svg.append("g"), // evidencia puntual sobre la densidad
      overlay: svg.append("g"), // rango seleccionado
      eje: svg.append("g").attr("class", "banda-eje"),
      brush: svg.append("g").attr("class", "grupo-brush"),
      etiquetas: svg.append("g"), // gutter izquierdo
    } as const;
    capasRef.current = capas as unknown as typeof capasRef.current;

    const zoom = d3
      .zoom<SVGSVGElement, unknown>()
      .scaleExtent([1, 60])
      // el arrastre en la banda del eje pertenece al brush; la rueda siempre al zoom
      .filter((ev: Event) => {
        if (ev.type === "wheel") return true;
        return !(ev.target as Element).closest(".grupo-brush");
      })
      .on("zoom", (ev) => {
        transformRef.current = ev.transform;
        redibujarRef.current();
      });
    svg.call(zoom).on("dblclick.zoom", null);

    const brush = d3.brushX().on("brush end", (ev) => {
      if (brushProgRef.current) return;
      const escala = escalaActual();
      if (!escala) return;
      if (!ev.selection) {
        rangoRef.current = null;
        dibujarOverlay();
        if (ev.type === "end") empujarRango(null, true);
        return;
      }
      const [x0, x1] = ev.selection as [number, number];
      const rango: RangoTiempo = [
        escala.invert(x0).getTime(),
        escala.invert(x1).getTime(),
      ];
      rangoRef.current = rango;
      dibujarOverlay(); // visual inmediato (60fps)
      empujarRango(rango, ev.type === "end"); // store con throttle rAF
    });
    brushRef.current = brush;
    capas.brush.call(brush);

    const observar = new ResizeObserver(([entrada]) => {
      dimRef.current = {
        w: entrada.contentRect.width,
        h: entrada.contentRect.height,
      };
      redibujarRef.current();
    });
    observar.observe(contRef.current!);

    return () => {
      observar.disconnect();
      cancelAnimationFrame(rafRef.current);
      svg.selectAll("*").remove();
    };
  }, []);

  function escalaActual(): d3.ScaleTime<number, number> | null {
    const base = escalaBaseRef.current;
    return base ? transformRef.current.rescaleX(base) : null;
  }

  function empujarRango(rango: RangoTiempo, forzar: boolean) {
    if (forzar) {
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

  function dibujarOverlay() {
    const capas = capasRef.current;
    const escala = escalaActual();
    const { h } = dimRef.current;
    if (!capas.overlay || !escala) return;
    const rango = rangoRef.current;
    const datos = rango
      ? [[escala(new Date(rango[0])), escala(new Date(rango[1]))]]
      : [];
    capas.overlay
      .selectAll<SVGRectElement, number[]>("rect")
      .data(datos)
      .join("rect")
      .attr("x", (d) => d[0])
      .attr("y", 0)
      .attr("width", (d) => Math.max(1, d[1] - d[0]))
      .attr("height", h - ALTO_EJE)
      .attr("fill", "#ffffff")
      .attr("fill-opacity", 0.06)
      .attr("stroke", "rgba(255,255,255,0.25)")
      .attr("stroke-width", 1)
      .attr("pointer-events", "none");
  }

  // --- redibujado completo (datos, resize, zoom, evidencia) ---
  useEffect(() => {
    redibujarRef.current = () => {
      const capas = capasRef.current;
      const datos = datosRef.current;
      const { w, h } = dimRef.current;
      if (!capas.eje || !datos || w < 100 || h < 80) return;
      const hoy = hoyRef.current;
      const { resaltados: res, nodos } = useEstado.getState();
      const hayResaltados = res.size > 0;

      // escala base (recalculada por si cambió el ancho) + transform de zoom
      const margen = (hoy - datos.minFecha) * 0.02;
      escalaBaseRef.current = d3
        .scaleUtc()
        .domain([new Date(datos.minFecha - margen), new Date(hoy + margen)])
        .range([GUTTER, w - MARGEN_DER]);
      const escala = transformRef.current.rescaleX(escalaBaseRef.current);

      // bandas verticales (de abajo hacia arriba)
      const yEje = h - ALTO_EJE;
      const yBins = yEje - ALTO_DENSIDAD;
      const yEnc = yBins - ALTO_ENCUENTROS;
      const yRx = yEnc - ALTO_RX;
      const hCond = Math.max(30, yRx - 6);

      // --- eje X + hairlines ---
      const ejeSel = capas.eje
        .attr("transform", `translate(0,${yEje})`)
        .call(d3.axisBottom(escala).ticks(Math.max(4, w / 110)).tickSizeOuter(0) as never);
      ejeSel.selectAll("text").attr("fill", "#898781").attr("font-size", 10);
      ejeSel.selectAll("line").attr("stroke", "#383835");
      ejeSel.select(".domain").attr("stroke", "#383835");

      capas.hairlines
        .selectAll<SVGLineElement, Date>("line")
        .data(escala.ticks(Math.max(4, w / 110)), (d: Date) => +d)
        .join("line")
        .attr("x1", (d) => escala(d))
        .attr("x2", (d) => escala(d))
        .attr("y1", 4)
        .attr("y2", yEje)
        .attr("stroke", "#2c2c2a")
        .attr("stroke-width", 1);

      // --- condiciones (barras con lane-packing) ---
      const nFilasCond = Math.max(1, ...datos.condiciones.map((c) => c.fila + 1));
      const altoFilaCond = Math.min(16, Math.max(6, hCond / nFilasCond));
      const altoBarra = Math.max(4, Math.min(8, altoFilaCond - 3));
      const yCond = (fila: number) => 6 + fila * altoFilaCond;

      const gCond = capas.cond
        .selectAll<SVGGElement, DatoBarra>("g")
        .data(datos.condiciones, (d) => d.id)
        .join((enter) => {
          const g = enter.append("g").attr("class", "tl-el");
          g.append("rect");
          g.append("text")
            .attr("font-size", 9)
            .attr("fill", "#c3c2b7")
            .attr("pointer-events", "none");
          return g;
        })
        .attr("class", (d) =>
          cn(
            "tl-el",
            res.has(d.id) && "resaltado",
            hayResaltados && !res.has(d.id) && "atenuado",
          ),
        )
        .on("mouseenter mousemove", (ev: MouseEvent, d) =>
          setTooltip({
            titulo: d.nombre,
            sub: `${fmt(d.inicio)} → ${d.estado === "active" ? "hoy (activa)" : fmt(d.fin)}`,
            color: COLOR_TIPO.Condicion,
            x: ev.clientX,
            y: ev.clientY,
          }),
        )
        .on("mouseleave", () => setTooltip(null));

      gCond
        .select<SVGRectElement>("rect")
        .attr("x", (d) => escala(d.inicio))
        .attr("y", (d) => yCond(d.fila))
        .attr("width", (d) => Math.max(2, escala(d.fin) - escala(d.inicio)))
        .attr("height", altoBarra)
        .attr("rx", 2)
        .attr("fill", COLOR_TIPO.Condicion)
        .attr("fill-opacity", (d) => (INACTIVO(d.estado) ? 0.18 : 0.9))
        .attr("stroke", COLOR_TIPO.Condicion)
        .attr("stroke-width", 1);

      gCond.select<SVGTextElement>("text").each(function (d) {
        const ancho = escala(d.fin) - escala(d.inicio);
        const texto =
          ancho > 60
            ? d.nombre.length > (ancho - 8) / 5.2
              ? d.nombre.slice(0, Math.floor((ancho - 8) / 5.2) - 1) + "…"
              : d.nombre
            : "";
        d3.select(this)
          .attr("x", escala(d.inicio) + 4)
          .attr("y", yCond(d.fila) + altoBarra - 1.5)
          .text(texto);
      });

      // --- prescripciones (barras activas / ticks completed) ---
      const nFilasRx = Math.max(1, ...datos.prescripciones.map((r) => r.fila + 1));
      const altoFilaRx = Math.min(14, Math.max(5, (ALTO_RX - 8) / nFilasRx));
      const yRxFila = (fila: number) => yRx + 4 + fila * altoFilaRx;

      capas.rx
        .selectAll<SVGRectElement, DatoBarra>("rect")
        .data(datos.prescripciones, (d) => d.id)
        .join("rect")
        .attr("class", (d) =>
          cn(
            "tl-el",
            res.has(d.id) && "resaltado",
            hayResaltados && !res.has(d.id) && "atenuado",
          ),
        )
        .attr("x", (d) => escala(d.inicio))
        .attr("y", (d) => yRxFila(d.fila))
        .attr("width", (d) =>
          d.puntual ? 3 : Math.max(3, escala(d.fin) - escala(d.inicio)),
        )
        .attr("height", Math.max(4, Math.min(8, altoFilaRx - 2)))
        .attr("rx", 1.5)
        .attr("fill", COLOR_TIPO.Prescripcion)
        .attr("fill-opacity", (d) => (d.puntual ? 0.25 : 0.9))
        .attr("stroke", COLOR_TIPO.Prescripcion)
        .attr("stroke-width", 1)
        .on("mouseenter mousemove", (ev: MouseEvent, d) =>
          setTooltip({
            titulo: d.nombre,
            sub:
              d.estado === "active"
                ? `${fmt(d.inicio)} → hoy (activa)`
                : `${fmt(d.inicio)} · ${d.estado} (fin no registrado en Synthea)`,
            color: COLOR_TIPO.Prescripcion,
            x: ev.clientX,
            y: ev.clientY,
          }),
        )
        .on("mouseleave", () => setTooltip(null));

      // --- encuentros (puntos clicables) ---
      capas.enc
        .selectAll<SVGCircleElement, (typeof datos.encuentros)[0]>("circle")
        .data(datos.encuentros, (d) => d.id)
        .join("circle")
        .attr("class", (d) =>
          cn(
            "tl-el",
            "punto-enc",
            res.has(d.id) && "resaltado",
            hayResaltados && !res.has(d.id) && "atenuado",
          ),
        )
        .attr("cx", (d) => escala(d.inicio))
        .attr("cy", yEnc + ALTO_ENCUENTROS / 2)
        .attr("r", 3.5)
        .attr("fill", COLOR_TIPO.Encuentro)
        .attr("fill-opacity", 0.85)
        .on("click", (_ev, d) => void useEstado.getState().expandirNodo(d.id))
        .on("mouseenter mousemove", (ev: MouseEvent, d) =>
          setTooltip({
            titulo: `Encuentro (${d.tipo ?? "clínico"})`,
            sub: `${fmt(d.inicio)}${d.motivo ? ` · ${d.motivo}` : ""} · click para expandir`,
            color: COLOR_TIPO.Encuentro,
            x: ev.clientX,
            y: ev.clientY,
          }),
        )
        .on("mouseleave", () => setTooltip(null));

      // --- densidad mensual apilada ---
      const escalaY = d3
        .scaleLinear()
        .domain([0, datos.maxMes])
        .range([0, ALTO_DENSIDAD - 6]);
      const unMes = 30 * 24 * 3600 * 1000;
      capas.bins
        .selectAll<SVGRectElement, DatoBin>("rect")
        .data(datos.bins, (d) => d.clave)
        .join("rect")
        .attr("x", (d) => escala(d.mes))
        .attr("width", (d) => Math.max(1, escala(d.mes + unMes) - escala(d.mes) - 0.5))
        .attr("y", (d) => yEje - 1 - escalaY(d.y1))
        .attr("height", (d) => Math.max(0.5, escalaY(d.y1) - escalaY(d.y0)))
        .attr("fill", (d) => COLOR_TIPO[d.tipo] ?? COLOR_TIPO.Concepto)
        .attr("fill-opacity", 0.75)
        .on("mouseenter mousemove", (ev: MouseEvent, d) =>
          setTooltip({
            titulo: `${d.y1 - d.y0} × ${d.tipo}`,
            sub: new Date(d.mes).toISOString().slice(0, 7),
            color: COLOR_TIPO[d.tipo] ?? COLOR_TIPO.Concepto,
            x: ev.clientX,
            y: ev.clientY,
          }),
        )
        .on("mouseleave", () => setTooltip(null));

      // --- marcas de evidencia sobre puntuales (nodos ∩ resaltados) ---
      const marcas = hayResaltados
        ? nodos.filter(
            (n) =>
              res.has(n.id) &&
              n.fecha &&
              TIPOS_BIN.includes(n.tipo),
          )
        : [];
      capas.marcas
        .selectAll<SVGPathElement, (typeof marcas)[0]>("path")
        .data(marcas, (d) => d.id)
        .join("path")
        .attr("class", "tl-el resaltado")
        .attr("d", d3.symbol(d3.symbolTriangle, 42))
        .attr(
          "transform",
          (d) => `translate(${escala(Date.parse(d.fecha!))},${yBins - 5}) rotate(180)`,
        )
        .attr("fill", (d) => COLOR_TIPO[d.tipo] ?? "#fff")
        .attr("stroke", "#ffffff")
        .attr("stroke-width", 1);

      // --- etiquetas del gutter ---
      const etiquetas = [
        { y: 6 + Math.min(hCond, nFilasCond * altoFilaCond) / 2, texto: "Condiciones", color: COLOR_TIPO.Condicion },
        { y: yRx + ALTO_RX / 2, texto: "Prescripciones", color: COLOR_TIPO.Prescripcion },
        { y: yEnc + ALTO_ENCUENTROS / 2, texto: "Encuentros", color: COLOR_TIPO.Encuentro },
        { y: yBins + ALTO_DENSIDAD / 2, texto: "Eventos/mes", color: COLOR_TIPO.Observacion },
      ];
      const gEt = capas.etiquetas
        .selectAll<SVGGElement, (typeof etiquetas)[0]>("g")
        .data(etiquetas)
        .join((enter) => {
          const g = enter.append("g");
          g.append("rect");
          g.append("circle");
          g.append("text");
          return g;
        });
      gEt.select("rect")
        .attr("x", 0)
        .attr("y", (d) => d.y - 9)
        .attr("width", GUTTER - 6)
        .attr("height", 18)
        .attr("fill", SUPERFICIE)
        .attr("fill-opacity", 0.85);
      gEt.select("circle")
        .attr("cx", 8)
        .attr("cy", (d) => d.y)
        .attr("r", 3)
        .attr("fill", (d) => d.color);
      gEt.select("text")
        .attr("x", 16)
        .attr("y", (d) => d.y + 3)
        .attr("font-size", 10)
        .attr("fill", "#c3c2b7")
        .text((d) => d.texto);

      // --- brush: extent + reposicionamiento programático tras zoom/resize ---
      if (brushRef.current) {
        brushRef.current.extent([
          [GUTTER, yEje],
          [w - MARGEN_DER, h],
        ]);
        brushProgRef.current = true;
        capas.brush.call(brushRef.current as never);
        const rango = rangoRef.current;
        if (rango) {
          const x0 = Math.max(GUTTER, escala(new Date(rango[0])));
          const x1 = Math.min(w - MARGEN_DER, escala(new Date(rango[1])));
          if (x1 > x0) {
            capas.brush.call(brushRef.current.move as never, [x0, x1] as never);
          }
        } else {
          capas.brush.call(brushRef.current.move as never, null as never);
        }
        brushProgRef.current = false;
        capas.brush.selectAll(".selection")
          .attr("fill", "#ffffff")
          .attr("fill-opacity", 0.12)
          .attr("stroke", "rgba(255,255,255,0.4)");
      }
      dibujarOverlay();
    };
    redibujarRef.current();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // datos nuevos → preparar + redibujar (y reset del zoom al cambiar paciente)
  useEffect(() => {
    hoyRef.current = Date.now();
    datosRef.current = intervalos ? prepararDatos(intervalos, hoyRef.current) : null;
    transformRef.current = d3.zoomIdentity;
    rangoRef.current = null;
    if (svgRef.current) {
      d3.select(svgRef.current).call(
        d3.zoom<SVGSVGElement, unknown>().transform as never,
        d3.zoomIdentity as never,
      );
      if (!intervalos) {
        // limpiar solo las capas de contenido (nunca el grupo del brush)
        const capas = capasRef.current;
        for (const clave of ["hairlines", "bins", "cond", "rx", "enc", "marcas", "overlay", "eje", "etiquetas"]) {
          capas[clave]?.selectAll("*").remove();
        }
      }
    }
    redibujarRef.current();
  }, [intervalos]);

  // evidencia o rango externos → repintar clases/overlay
  useEffect(() => {
    rangoRef.current = rangoTiempo;
    redibujarRef.current();
  }, [resaltados, rangoTiempo, timelineAbierta]);

  const limpiarRango = () => {
    rangoRef.current = null;
    useEstado.getState().fijarRangoTiempo(null);
  };

  return (
    <div
      className={cn(
        "flex shrink-0 flex-col border-t border-border bg-background transition-[height] duration-200",
        timelineAbierta ? "h-[42%]" : "h-8",
      )}
    >
      <div className="flex h-8 shrink-0 items-center gap-2 px-3">
        <CalendarRange className="size-3.5 text-primary" />
        <span className="text-xs font-semibold">Línea de tiempo</span>
        {rangoTiempo && (
          <Badge variant="secondary" className="gap-1 py-0 text-[10px]">
            {fmt(rangoTiempo[0])} – {fmt(rangoTiempo[1])}
            <button onClick={limpiarRango} title="Quitar filtro temporal" className="hover:text-foreground">
              <X className="size-3" />
            </button>
          </Badge>
        )}
        {timelineAbierta && (
          <span className="text-[10px] text-muted-foreground">
            rueda = zoom · arrastra el eje = filtrar el grafo por fechas
          </span>
        )}
        <button
          onClick={alternarTimeline}
          className="ml-auto rounded p-1 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          title={timelineAbierta ? "Plegar" : "Desplegar"}
        >
          {timelineAbierta ? <ChevronDown className="size-4" /> : <ChevronUp className="size-4" />}
        </button>
      </div>

      <div ref={contRef} className={cn("relative min-h-0 flex-1", !timelineAbierta && "hidden")}>
        <svg ref={svgRef} className="h-full w-full" />
        {pacienteId && !intervalos && (
          <div className="absolute inset-0 flex items-center justify-center">
            <Loader2 className="size-5 animate-spin text-muted-foreground" />
          </div>
        )}
        {!pacienteId && (
          <div className="absolute inset-0 flex items-center justify-center text-xs text-muted-foreground">
            Selecciona un paciente para ver su historia clínica en el tiempo
          </div>
        )}
        {tooltip && (
          <div
            className="pointer-events-none fixed z-50 max-w-xs rounded-md border border-border bg-popover p-2.5 text-popover-foreground shadow-lg"
            style={{ left: tooltip.x + 12, top: tooltip.y - 48 }}
          >
            <div className="flex items-center gap-1.5">
              <span className="size-2 rounded-full" style={{ background: tooltip.color }} />
              <span className="text-xs font-medium">{tooltip.titulo}</span>
            </div>
            <p className="mt-0.5 text-[11px] text-muted-foreground">{tooltip.sub}</p>
          </div>
        )}
      </div>
    </div>
  );
}

function fmt(ts: number): string {
  return new Date(ts).toISOString().slice(0, 10);
}
