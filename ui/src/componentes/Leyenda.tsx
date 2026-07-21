// Leyenda con orden fijo (nunca ciclado) + toggles de visibilidad por tipo.

import { useEstado } from "@/estado";
import { claveLeyenda, COLOR_TIPO, TIPOS_LEYENDA } from "@/paleta";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { Eye, EyeOff } from "lucide-react";

const NOMBRES: Record<string, string> = {
  Condicion: "Condición",
  Prescripcion: "Prescripción",
  Farmaco: "Fármaco",
  Encuentro: "Encuentro",
  Procedimiento: "Procedimiento",
  Observacion: "Observación",
  Inmunizacion: "Inmunización",
  Alergia: "Alergia",
  Concepto: "Concepto",
};

export function Leyenda() {
  const nodos = useEstado((s) => s.nodos);
  const tiposOcultos = useEstado((s) => s.tiposOcultos);
  const alternarTipo = useEstado((s) => s.alternarTipo);

  if (!nodos.length) return null;

  const conteo = new Map<string, number>();
  for (const n of nodos) {
    const clave = claveLeyenda(n.tipo);
    conteo.set(clave, (conteo.get(clave) ?? 0) + 1);
  }

  return (
    <Card className="absolute bottom-4 left-4 z-10 w-52 bg-card/90 p-3 backdrop-blur">
      <p className="mb-2 text-xs font-semibold text-secondary-foreground">Tipos de nodo</p>
      <ul className="space-y-1">
        {TIPOS_LEYENDA.filter((t) => conteo.has(t)).map((tipo) => {
          const oculto = tiposOcultos.has(tipo);
          return (
            <li key={tipo}>
              <button
                onClick={() => alternarTipo(tipo)}
                className={cn(
                  "flex w-full items-center gap-2 rounded px-1.5 py-0.5 text-xs transition-colors hover:bg-accent",
                  oculto && "opacity-40",
                )}
                title={oculto ? "Mostrar" : "Ocultar"}
              >
                <span
                  className={cn(
                    "inline-block size-2.5 shrink-0",
                    tipo === "Concepto" ? "rotate-45 rounded-[2px]" : "rounded-full",
                  )}
                  style={{ background: COLOR_TIPO[tipo] }}
                />
                <span className="flex-1 text-left text-secondary-foreground">
                  {NOMBRES[tipo] ?? tipo}
                </span>
                <span className="tabular-nums text-muted-foreground">
                  {conteo.get(tipo)}
                </span>
                {oculto ? (
                  <EyeOff className="size-3 text-muted-foreground" />
                ) : (
                  <Eye className="size-3 text-muted-foreground/50" />
                )}
              </button>
            </li>
          );
        })}
      </ul>
      <div className="mt-2 space-y-1 border-t border-border pt-2 text-[10px] text-muted-foreground">
        <p className="flex items-center gap-2">
          <svg width="22" height="6">
            <line x1="0" y1="3" x2="22" y2="3" stroke="#c3c2b7" strokeWidth="1.5" />
          </svg>
          causal (TRATA / INDICADO_POR)
        </p>
        <p className="flex items-center gap-2">
          <svg width="22" height="6">
            <line x1="0" y1="3" x2="22" y2="3" stroke="#d03b3b" strokeWidth="2" strokeDasharray="4 3" />
          </svg>
          interacción farmacológica
        </p>
        <p className="flex items-center gap-2">
          <svg width="22" height="6">
            <line x1="0" y1="3" x2="22" y2="3" stroke="#5a5a56" strokeWidth="1" />
          </svg>
          estructural · hueco = resuelto / finalizado
        </p>
      </div>
    </Card>
  );
}
