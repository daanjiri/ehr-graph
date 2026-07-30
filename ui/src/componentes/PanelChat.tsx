// Panel de chat con streaming: los deltas rellenan el mensaje en curso y las
// trazas de herramientas aparecen inline en orden cronológico. Click en una
// traza re-resalta su evidencia en el grafo.

import { useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useEstado } from "@/estado";
import type { Mensaje, Traza } from "@/tipos";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import {
  CircleAlert,
  Loader2,
  PanelRightClose,
  PanelRightOpen,
  Send,
  Sparkles,
  Square,
  Wrench,
} from "lucide-react";

const NOMBRE_TOOL: Record<string, string> = {
  buscar_semantico: "búsqueda semántica",
  timeline: "cronología",
  expandir_contexto: "expandir contexto",
  cadena_causal: "cadena causal",
  medicacion_activa: "medicación activa",
  listar_pacientes: "listar pacientes",
};

function ChipTraza({ traza }: { traza: Traza }) {
  const vincularEvidencia = useEstado((s) => s.vincularEvidencia);
  const clicable = !traza.pendiente && (traza.nodoIds?.length ?? 0) > 0;
  return (
    <button
      disabled={!clicable}
      onClick={() => traza.nodoIds && void vincularEvidencia(traza.nodoIds)}
      title={clicable ? "Resaltar esta evidencia en el grafo" : undefined}
      className={cn(
        "my-1 inline-flex items-center gap-1.5 rounded-full border border-border bg-secondary/60 px-2.5 py-1 text-xs text-secondary-foreground",
        clicable && "cursor-pointer transition-colors hover:border-ring hover:bg-secondary",
      )}
    >
      {traza.pendiente ? (
        <Loader2 className="size-3 animate-spin text-primary" />
      ) : traza.error ? (
        <CircleAlert className="size-3 text-destructive" />
      ) : (
        <Wrench className="size-3 text-muted-foreground" />
      )}
      <span className="font-medium">{NOMBRE_TOOL[traza.nombre] ?? traza.nombre}</span>
      {!traza.pendiente && !traza.error && (
        <span className="text-muted-foreground">
          → {traza.nResultados} {traza.nResultados === 1 ? "resultado" : "resultados"}
        </span>
      )}
    </button>
  );
}

function Burbuja({ mensaje }: { mensaje: Mensaje }) {
  const esUsuario = mensaje.rol === "usuario";
  return (
    <div className={cn("flex", esUsuario ? "justify-end" : "justify-start")}>
      <div
        className={cn(
          "max-w-[92%] rounded-lg px-3 py-2 text-sm leading-relaxed",
          esUsuario
            ? "bg-primary text-primary-foreground"
            : "bg-secondary/50 text-card-foreground",
          mensaje.error && "border border-destructive/50",
        )}
      >
        {mensaje.partes.map((parte, i) =>
          parte.tipo === "texto" ? (
            esUsuario ? (
              <p key={i} className="whitespace-pre-wrap">
                {parte.texto}
              </p>
            ) : (
              <div key={i} className="md">
                <Markdown remarkPlugins={[remarkGfm]}>{parte.texto}</Markdown>
              </div>
            )
          ) : (
            <div key={i}>
              <ChipTraza traza={parte.traza} />
            </div>
          ),
        )}
        {mensaje.enCurso && mensaje.partes.length === 0 && (
          <Loader2 className="size-4 animate-spin text-muted-foreground" />
        )}
      </div>
    </div>
  );
}

export function PanelChat({ colapsado = false }: { colapsado?: boolean }) {
  const mensajes = useEstado((s) => s.mensajes);
  const streamActivo = useEstado((s) => s.streamActivo);
  const pacienteId = useEstado((s) => s.pacienteId);
  const enviarMensaje = useEstado((s) => s.enviarMensaje);
  const abortarStream = useEstado((s) => s.abortarStream);
  const alternarChat = useEstado((s) => s.alternarChat);

  const [texto, setTexto] = useState("");
  const finRef = useRef<HTMLDivElement>(null);
  const cerrarRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    finRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [mensajes]);

  useEffect(() => {
    if (colapsado) return;
    if (window.matchMedia("(max-width: 1023px)").matches) {
      requestAnimationFrame(() => cerrarRef.current?.focus());
    }
    const cerrarConEscape = (ev: KeyboardEvent) => {
      if (ev.key === "Escape" && window.matchMedia("(max-width: 1023px)").matches) {
        alternarChat();
      }
    };
    window.addEventListener("keydown", cerrarConEscape);
    return () => window.removeEventListener("keydown", cerrarConEscape);
  }, [colapsado, alternarChat]);

  const enviar = () => {
    if (!texto.trim() || streamActivo) return;
    void enviarMensaje(texto.trim());
    setTexto("");
  };

  if (colapsado) {
    return (
      <button
        onClick={alternarChat}
        className="flex h-full w-full flex-col items-center gap-3 py-3 text-muted-foreground transition-colors hover:bg-accent/50 hover:text-foreground"
        title="Abrir asistente clínico"
        aria-label="Abrir asistente clínico"
        aria-expanded={false}
      >
        <PanelRightOpen className="size-4" />
        <Sparkles className="size-4 text-primary" />
        <span className="text-[11px] font-medium [writing-mode:vertical-rl]">Asistente</span>
        {streamActivo && <span className="mt-auto size-2 animate-pulse rounded-full bg-primary" />}
      </button>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2 border-b border-border px-4 py-3">
        <Sparkles className="size-4 text-primary" />
        <h2 className="text-sm font-semibold">Asistente clínico</h2>
        <Badge variant="outline" className="ml-auto">
          GraphRAG
        </Badge>
        <button
          ref={cerrarRef}
          onClick={alternarChat}
          className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          title="Colapsar asistente"
          aria-label="Colapsar asistente clínico"
          aria-expanded={true}
        >
          <PanelRightClose className="size-4" />
        </button>
      </div>

      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4">
        {mensajes.length === 0 && (
          <div className="mt-8 space-y-2 text-center text-sm text-muted-foreground">
            <p className="font-medium text-secondary-foreground">
              {pacienteId
                ? "Pregunta sobre este paciente"
                : "Selecciona un paciente para empezar"}
            </p>
            {pacienteId && (
              <ul className="space-y-1 text-xs">
                <li>«¿Qué medicación toma y para qué?»</li>
                <li>«¿Qué condiciones activas tiene?»</li>
                <li>«¿Cuándo fue su última consulta?»</li>
              </ul>
            )}
            <p className="pt-2 text-[10px]">
              Responde solo con datos del grafo. La evidencia usada se resalta en la
              visualización.
            </p>
          </div>
        )}
        {mensajes.map((m, i) => (
          <Burbuja key={i} mensaje={m} />
        ))}
        <div ref={finRef} />
      </div>

      <div className="flex gap-2 border-t border-border p-3">
        <Input
          value={texto}
          onChange={(e) => setTexto(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && enviar()}
          maxLength={500}
          placeholder={pacienteId ? "Escribe tu pregunta…" : "Selecciona un paciente primero"}
          disabled={!pacienteId || streamActivo}
        />
        {streamActivo ? (
          <Button variant="outline" size="icon" onClick={abortarStream} title="Detener">
            <Square className="size-3.5" />
          </Button>
        ) : (
          <Button size="icon" onClick={enviar} disabled={!pacienteId || !texto.trim()}>
            <Send className="size-4" />
          </Button>
        )}
      </div>
    </div>
  );
}
