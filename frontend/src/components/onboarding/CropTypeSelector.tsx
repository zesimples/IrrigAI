"use client";

import { cn } from "@/lib/utils";
import { useCropProfileTemplates } from "@/hooks/useCatalog";
import type { CropProfileTemplate } from "@/types";

const CROP_ICONS: Record<string, string> = {
  olive: "🫒",
  almond: "🌰",
  maize: "🌽",
  tomato: "🍅",
  vineyard: "🍇",
};

interface CropTypeSelectorProps {
  value: string | null;
  onChange: (template: CropProfileTemplate) => void;
}

export function CropTypeSelector({ value, onChange }: CropTypeSelectorProps) {
  const { templates, loading } = useCropProfileTemplates();

  if (loading) {
    return <div className="h-40 animate-pulse rounded-2xl bg-slate-100" />;
  }

  if (templates.length === 0) {
    return (
      <div className="rounded-2xl border border-dashed border-slate-300 bg-slate-50 px-4 py-5 text-sm text-slate-600">
        Não existem perfis de cultura disponíveis neste momento.
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div>
        <p className="text-sm font-semibold text-slate-800">Tipo de cultura</p>
        <p className="text-xs text-slate-500">
          O perfil define fases fenológicas, MAD e coeficientes culturais usados pelo motor de recomendação.
        </p>
      </div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        {templates.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => onChange(t)}
            aria-pressed={value === t.crop_type}
            aria-label={`Seleccionar cultura ${t.name_pt}`}
            className={cn(
              "flex flex-col items-center rounded-2xl border-2 bg-white p-4 text-center shadow-sm transition-colors focus-visible:ring-offset-white",
              value === t.crop_type
                ? "border-emerald-600 bg-emerald-50"
                : "border-slate-200 hover:border-slate-300 hover:bg-slate-50",
            )}
          >
            <span className="text-3xl">{CROP_ICONS[t.crop_type] ?? "🌿"}</span>
            <p className="mt-2 text-sm font-semibold text-slate-900">{t.name_pt}</p>
            <p className="mt-1 text-xs text-slate-500">
              MAD {(t.mad * 100).toFixed(0)}% · Kc médio{" "}
              {t.stages.length > 0
                ? (
                    t.stages.reduce((s, st) => s + (st as { kc: number }).kc, 0) /
                    t.stages.length
                  ).toFixed(2)
                : "—"}
            </p>
          </button>
        ))}
      </div>
    </div>
  );
}
