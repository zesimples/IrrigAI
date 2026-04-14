"use client";

import { cn } from "@/lib/utils";
import { useSoilPresets } from "@/hooks/useCatalog";
import type { SoilPreset } from "@/types";

interface SoilSelectorProps {
  value: string | null;
  onChange: (preset: SoilPreset | null) => void;
}

export function SoilSelector({ value, onChange }: SoilSelectorProps) {
  const { presets, loading } = useSoilPresets();

  if (loading) {
    return <div className="h-32 animate-pulse rounded-2xl bg-slate-100" />;
  }

  if (presets.length === 0) {
    return (
      <div className="rounded-2xl border border-dashed border-slate-300 bg-slate-50 px-4 py-5 text-sm text-slate-600">
        Não existem texturas de solo disponíveis para selecção.
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div>
        <p className="text-sm font-semibold text-slate-800">Textura do solo</p>
        <p className="text-xs text-slate-500">
          Escolha a opção mais próxima para pré-preencher capacidade de campo e água disponível.
        </p>
      </div>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        {presets.map((p) => (
          <button
            key={p.id}
            type="button"
            onClick={() => onChange(value === p.id ? null : p)}
            aria-pressed={value === p.id}
            aria-label={`Seleccionar solo ${p.name_pt}`}
            className={cn(
              "rounded-2xl border-2 bg-white p-3 text-left shadow-sm transition-colors focus-visible:ring-offset-white",
              value === p.id
                ? "border-emerald-600 bg-emerald-50"
                : "border-slate-200 hover:border-slate-300 hover:bg-slate-50",
            )}
          >
            <p className="text-sm font-semibold text-slate-900">{p.name_pt}</p>
            <p className="mt-1 text-xs text-slate-500">
              CC {(p.field_capacity * 100).toFixed(0)}% · PMP {(p.wilting_point * 100).toFixed(0)}%
            </p>
            <p className="mt-1 text-xs font-medium text-emerald-800">
              {p.taw_mm_per_m.toFixed(0)} mm/m água disponível
            </p>
          </button>
        ))}
      </div>
    </div>
  );
}
