"use client";

import { cn } from "@/lib/utils";
import type { CropStage } from "@/types";

interface PhenologicalTimelineProps {
  stages: CropStage[];
  currentStage?: string | null;
  onSelect?: (stage: CropStage) => void;
}

function doyToLabel(doy: number): string {
  const date = new Date(2024, 0, doy); // non-leap year base
  return date.toLocaleDateString("pt-PT", { day: "numeric", month: "short" });
}

export function PhenologicalTimeline({
  stages,
  currentStage,
  onSelect,
}: PhenologicalTimelineProps) {
  if (!stages || stages.length === 0) {
    return <p className="text-sm text-slate-500">Sem fases fenológicas disponíveis.</p>;
  }

  const totalDays = 365;

  return (
    <div className="space-y-3">
      <div>
        <p className="text-sm font-semibold text-slate-800">Fase fenológica actual</p>
        <p className="text-xs text-slate-500">
          Seleccione a fase que melhor descreve o estado do sector. Isto afecta o Kc e a recomendação final.
        </p>
      </div>

      {/* Visual timeline bar */}
      <div className="relative h-8 overflow-hidden rounded-full bg-slate-100">
        {stages.map((s) => {
          const left = ((s.start_doy - 1) / totalDays) * 100;
          const width = ((s.end_doy - s.start_doy + 1) / totalDays) * 100;
          const active = currentStage === s.name;
          return (
            <button
              key={s.name}
              type="button"
              title={`${s.name_pt ?? s.name}: ${doyToLabel(s.start_doy)} – ${doyToLabel(s.end_doy)}, Kc ${s.kc}`}
              aria-label={`Seleccionar fase ${s.name_pt ?? s.name}`}
              style={{ left: `${left}%`, width: `${width}%` }}
              className={cn(
                "absolute top-0 h-full border-r border-white/60 transition-opacity focus-visible:z-10",
                active ? "opacity-100" : "opacity-70 hover:opacity-90",
              )}
              onClick={() => onSelect?.(s)}
            >
              <div
                className={cn(
                  "h-full",
                  active ? "bg-emerald-600" : "bg-emerald-300",
                )}
              />
            </button>
          );
        })}
      </div>

      {/* Stage cards */}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        {stages.map((s) => {
          const active = currentStage === s.name;
          return (
            <button
              key={s.name}
              type="button"
              onClick={() => onSelect?.(s)}
              aria-pressed={active}
              className={cn(
                "rounded-xl border-2 p-3 text-left transition-colors focus-visible:ring-offset-white",
                active
                  ? "border-emerald-600 bg-emerald-50"
                  : "border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50",
              )}
            >
              <p className="truncate text-xs font-semibold text-slate-900">
                {s.name_pt ?? s.name}
              </p>
              <p className="mt-1 text-xs text-slate-500">
                {doyToLabel(s.start_doy)} – {doyToLabel(s.end_doy)}
              </p>
              <p className="mt-1 text-xs font-semibold text-emerald-800">Kc {s.kc}</p>
            </button>
          );
        })}
      </div>
    </div>
  );
}
