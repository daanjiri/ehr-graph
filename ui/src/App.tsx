import { Activity } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { BotonDesplegar } from "@/componentes/BotonDesplegar";
import { SelectorPaciente } from "@/componentes/SelectorPaciente";
import { GrafoPaciente } from "@/componentes/GrafoPaciente";
import { Leyenda } from "@/componentes/Leyenda";
import { PanelChat } from "@/componentes/PanelChat";
import { VistaTemporal } from "@/componentes/VistaTemporal";
import { useEstado } from "@/estado";

export default function App() {
  const chatAbierto = useEstado((s) => s.chatAbierto);
  const alternarChat = useEstado((s) => s.alternarChat);

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-3 border-b border-border bg-background px-4 py-2.5">
        <Activity className="size-5 text-primary" />
        <h1 className="text-sm font-semibold tracking-tight">
          ehr-graph <span className="font-normal text-muted-foreground">· explorador clínico</span>
        </h1>
        <Badge variant="outline">datos sintéticos (Synthea)</Badge>
        <span className="hidden text-xs text-muted-foreground xl:inline">
          Demo educativa · no constituye consejo médico
        </span>
        <div className="ml-auto flex items-center gap-2">
          <BotonDesplegar />
          <SelectorPaciente />
        </div>
      </header>

      <div className="relative flex min-h-0 flex-1 overflow-hidden">
        <main className="flex min-w-0 flex-1 flex-col bg-card">
          <div className="relative min-h-0 flex-1">
            <GrafoPaciente />
            <Leyenda />
          </div>
          <VistaTemporal />
        </main>
        {chatAbierto && (
          <button
            className="absolute inset-0 z-20 bg-black/45 backdrop-blur-[1px] lg:hidden"
            onClick={alternarChat}
            aria-label="Cerrar el asistente"
          />
        )}
        <aside
          className={
            chatAbierto
              ? "absolute inset-y-0 right-0 z-30 w-[min(400px,calc(100vw-44px))] shrink-0 border-l border-border bg-background shadow-2xl transition-[width] duration-200 lg:static lg:z-auto lg:w-[clamp(340px,30vw,420px)] lg:shadow-none"
              : "relative z-10 w-11 shrink-0 border-l border-border bg-background transition-[width] duration-200"
          }
        >
          <PanelChat colapsado={!chatAbierto} />
        </aside>
      </div>
    </div>
  );
}
