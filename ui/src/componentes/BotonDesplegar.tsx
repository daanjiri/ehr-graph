// Botón del header: despliega todo el grafo EHR del paciente o lo compacta al
// núcleo clínico inicial. Selectores atómicos para no re-renderizar App.

import { Loader2, Minimize2, Waypoints } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useEstado } from "@/estado";

export function BotonDesplegar() {
  const pacienteId = useEstado((s) => s.pacienteId);
  const grafoCompleto = useEstado((s) => s.grafoCompleto);
  const cargandoGrafo = useEstado((s) => s.cargandoGrafo);
  const nNodos = useEstado((s) => s.nodos.length);
  const alternarGrafoCompleto = useEstado((s) => s.alternarGrafoCompleto);

  const deshabilitado = !pacienteId || cargandoGrafo;

  return (
    <Button
      variant="outline"
      size="sm"
      disabled={deshabilitado}
      onClick={() => void alternarGrafoCompleto()}
      title={
        grafoCompleto
          ? "Volver al núcleo clínico"
          : "Cargar todos los eventos del paciente"
      }
    >
      {cargandoGrafo ? (
        <Loader2 className="animate-spin" />
      ) : grafoCompleto ? (
        <Minimize2 />
      ) : (
        <Waypoints />
      )}
      {grafoCompleto ? `Compactar · ${nNodos} nodos` : "Desplegar todo"}
    </Button>
  );
}
