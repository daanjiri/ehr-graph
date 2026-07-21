import { Activity } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { SelectorPaciente } from "@/componentes/SelectorPaciente";
import { GrafoPaciente } from "@/componentes/GrafoPaciente";
import { Leyenda } from "@/componentes/Leyenda";
import { PanelChat } from "@/componentes/PanelChat";
import { VistaTemporal } from "@/componentes/VistaTemporal";

export default function App() {
  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-3 border-b border-border bg-background px-4 py-2.5">
        <Activity className="size-5 text-primary" />
        <h1 className="text-sm font-semibold tracking-tight">
          ehr-graph <span className="font-normal text-muted-foreground">· explorador clínico</span>
        </h1>
        <Badge variant="outline">datos sintéticos (Synthea)</Badge>
        <div className="ml-auto">
          <SelectorPaciente />
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        <main className="flex min-w-0 flex-1 flex-col bg-card">
          <div className="relative min-h-0 flex-1">
            <GrafoPaciente />
            <Leyenda />
          </div>
          <VistaTemporal />
        </main>
        <aside className="w-[400px] shrink-0 border-l border-border bg-background">
          <PanelChat />
        </aside>
      </div>
    </div>
  );
}
