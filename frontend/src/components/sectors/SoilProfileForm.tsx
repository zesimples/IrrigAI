"use client";

import { useEffect, useState } from "react";
import { catalogApi, sectorsApi } from "@/lib/api";
import type { SoilPreset } from "@/types";
import { CheckCircle } from "lucide-react";

// ─── Editorial sub-components (self-contained) ────────────────────────────────

function FieldWrapper({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <p className="font-serif text-[14.5px] font-semibold tracking-[-0.005em] text-ink mb-1.5">
        {label}
      </p>
      {children}
      {hint && (
        <p className="mt-1.5 text-[11.5px] text-ink-3 leading-[1.45]">{hint}</p>
      )}
    </div>
  );
}

function EditorialSelect({
  value,
  onChange,
  options,
  placeholder,
}: {
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
  placeholder?: string;
}) {
  return (
    <div className="relative">
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full appearance-none bg-paper border border-rule rounded-md py-2.5 pl-3 pr-9 text-[13px] text-ink focus:outline-none focus:ring-1 focus:ring-terra/40 cursor-pointer"
        style={{ WebkitAppearance: "none" }}
      >
        {placeholder && (
          <option value="" disabled>
            {placeholder}
          </option>
        )}
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
      <span className="pointer-events-none absolute right-3.5 top-1/2 -translate-y-1/2 font-serif italic text-[14px] text-ink-3">
        ▾
      </span>
    </div>
  );
}

function RainCorrectionSlider({
  value,
  onChange,
}: {
  value: number;
  onChange: (v: number) => void;
}) {
  const pct = (value / 2) * 100;
  const tintClass =
    value < 0.85 ? "text-[#c9a34a]" : value > 1.15 ? "text-olive" : "text-ink-2";
  const tintFill =
    value < 0.85 ? "#c9a34a" : value > 1.15 ? "#6b8f4e" : "#5a5048";
  const label =
    value < 0.85 ? "Pouca infiltração" : value > 1.15 ? "Boa infiltração" : "Padrão";

  return (
    <div>
      <div className="flex items-baseline justify-between mb-1.5">
        <span className={`font-serif text-[24px] font-medium tracking-[-0.02em] ${tintClass}`}>
          ×{value.toFixed(2)}
        </span>
        <span className="font-mono text-[10px] tracking-[0.08em] uppercase text-ink-3">
          {label}
        </span>
      </div>
      <div className="relative h-1.5 bg-[#e9e4dc] rounded-full overflow-hidden">
        <div className="absolute left-[45%] right-[45%] top-0 bottom-0 bg-olive/18" />
        <div
          className="absolute left-0 top-0 bottom-0 rounded-full"
          style={{ width: `${pct}%`, background: tintFill, opacity: 0.85 }}
        />
      </div>
      <input
        type="range"
        min={0}
        max={2}
        step={0.05}
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        className="w-full mt-1.5"
        style={{ accentColor: tintFill }}
      />
      <div className="flex justify-between font-mono text-[9.5px] text-ink-3 tracking-[0.04em] mt-0.5">
        <span>×0.0</span>
        <span>×1.0 ref</span>
        <span>×2.0</span>
      </div>
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

interface Props {
  sectorId: string;
  currentSoilPresetId?: string | null;
  currentRainfallEffectiveness?: number | null;
  onSaved?: () => void | Promise<void>;
}

export function SoilProfileForm({
  sectorId,
  currentSoilPresetId,
  currentRainfallEffectiveness,
  onSaved,
}: Props) {
  const [soilPresets, setSoilPresets] = useState<SoilPreset[]>([]);
  const [selectedSoilId, setSelectedSoilId] = useState(currentSoilPresetId ?? "");
  const [rainfallValue, setRainfallValue] = useState(currentRainfallEffectiveness ?? 1.0);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { catalogApi.soilPresets().then(setSoilPresets).catch(() => {}); }, []);
  useEffect(() => { setSelectedSoilId(currentSoilPresetId ?? ""); }, [currentSoilPresetId]);
  useEffect(() => { setRainfallValue(currentRainfallEffectiveness ?? 1.0); }, [currentRainfallEffectiveness]);

  const soilOptions = [
    { value: "", label: "Solo do talhão (padrão)" },
    ...soilPresets.map((p) => ({
      value: p.id,
      label: `${p.name_pt} — CC ${(p.field_capacity * 100).toFixed(0)}% · CMP ${(p.wilting_point * 100).toFixed(0)}%`,
    })),
  ];

  const currentPreset = soilPresets.find((p) => p.id === selectedSoilId);
  const taw = currentPreset?.taw_mm_per_m ?? null;

  const soilChanged = selectedSoilId !== (currentSoilPresetId ?? "");
  const rainfallChanged = Math.abs(rainfallValue - (currentRainfallEffectiveness ?? 1.0)) > 0.001;
  const hasChanges = soilChanged || rainfallChanged;

  async function handleSave() {
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      if (soilChanged) {
        await sectorsApi.updateCropProfile(sectorId, {
          soil_preset_id: selectedSoilId || null,
          field_capacity: currentPreset?.field_capacity ?? null,
          wilting_point: currentPreset?.wilting_point ?? null,
        });
      }
      if (rainfallChanged) {
        await sectorsApi.update(sectorId, { rainfall_effectiveness: rainfallValue });
      }
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
      await onSaved?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao guardar perfil de solo.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-7">
      <FieldWrapper
        label="Tipo de solo"
        hint="Define capacidade de campo (CC) e coeficiente de murchamento permanente (CMP)."
      >
        <EditorialSelect
          value={selectedSoilId}
          onChange={setSelectedSoilId}
          options={soilOptions}
        />
        {taw != null && (
          <div className="mt-2 flex items-baseline gap-1.5">
            <span className="font-mono text-[10px] tracking-[0.08em] uppercase text-ink-3">
              TAW estimada
            </span>
            <span className="font-serif text-[18px] font-medium text-olive tracking-[-0.01em]">
              {taw}
            </span>
            <span className="font-mono text-[10.5px] text-ink-3">mm / m de raiz</span>
          </div>
        )}
      </FieldWrapper>

      <FieldWrapper
        label="Correcção de eficácia da chuva"
        hint="<1.0 em declive ou solo compactado · >1.0 em terreno plano e bem coberto."
      >
        <RainCorrectionSlider value={rainfallValue} onChange={setRainfallValue} />
      </FieldWrapper>

      {error && (
        <p className="text-[13px] font-medium text-terra">{error}</p>
      )}

      <div className="flex items-center gap-3 pt-1">
        <button
          type="button"
          onClick={handleSave}
          disabled={saving || !hasChanges}
          className="inline-flex items-center gap-2 rounded-md bg-ink text-paper px-5 py-2.5 text-[13px] font-semibold hover:opacity-85 disabled:opacity-40 transition-opacity"
        >
          {saving ? "A guardar…" : "Guardar"}
        </button>
        {saved && (
          <span className="flex items-center gap-1.5 text-[13px] font-medium text-olive">
            <CheckCircle className="h-4 w-4" />
            Guardado — nova recomendação gerada
          </span>
        )}
      </div>

      {/* Current config summary */}
      {(currentPreset || currentRainfallEffectiveness != null) && (
        <div className="rounded-lg border border-rule-soft bg-card px-4 py-3 space-y-1">
          <p className="font-mono text-[10px] uppercase tracking-[0.1em] text-ink-3 mb-2">
            Configuração actual
          </p>
          <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-[12px]">
            {currentPreset && (
              <>
                <Row label="Solo" value={currentPreset.name_pt} />
                <Row label="TAW" value={`${currentPreset.taw_mm_per_m} mm/m`} />
                <Row label="CC" value={`${(currentPreset.field_capacity * 100).toFixed(0)}%`} />
                <Row label="CMP" value={`${(currentPreset.wilting_point * 100).toFixed(0)}%`} />
              </>
            )}
            {currentRainfallEffectiveness != null && (
              <Row
                label="Eficácia da chuva"
                value={`×${currentRainfallEffectiveness.toFixed(2)}`}
              />
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <span className="text-ink-3">{label}</span>
      <span className="font-serif text-[13px] font-medium text-ink">{value}</span>
    </div>
  );
}
