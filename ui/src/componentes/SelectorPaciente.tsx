// Selector de paciente (select nativo con estilo shadcn).

import { useEffect } from "react";
import { useEstado } from "@/estado";

export function SelectorPaciente() {
  const pacientes = useEstado((s) => s.pacientes);
  const pacienteId = useEstado((s) => s.pacienteId);
  const cargarPacientes = useEstado((s) => s.cargarPacientes);
  const seleccionarPaciente = useEstado((s) => s.seleccionarPaciente);

  useEffect(() => {
    void cargarPacientes();
  }, [cargarPacientes]);

  return (
    <select
      value={pacienteId ?? ""}
      onChange={(e) => e.target.value && void seleccionarPaciente(e.target.value)}
      className="h-9 w-72 cursor-pointer rounded-md border border-input bg-card px-3 text-sm text-foreground shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
    >
      <option value="" disabled>
        Selecciona un paciente…
      </option>
      {pacientes.map((p) => (
        <option key={p.id} value={p.id}>
          {p.nombre} {p.fallecido ? "✝" : ""} ({p.fecha_nacimiento?.slice(0, 10)})
        </option>
      ))}
    </select>
  );
}
