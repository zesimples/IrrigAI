"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { sectorsApi } from "@/lib/api";
import type { IrrigationSystemOut } from "@/types";
import { CheckCircle } from "lucide-react";

const SYSTEM_TYPES = [
  { value: "drip", label: "Gota-a-gota" },
  { value: "sprinkler", label: "Aspersão" },
  { value: "center_pivot", label: "Pivot central" },
  { value: "flood", label: "Gravidade / Inundação" },
];

interface Props {
  sectorId: string;
  current: IrrigationSystemOut | null;
  onSaved?: () => void;
}

export function IrrigationSystemForm({ sectorId, current, onSaved }: Props) {
  const [systemType, setSystemType] = useState<"drip" | "sprinkler" | "center_pivot" | "flood">(
    (current?.system_type as "drip" | "sprinkler" | "center_pivot" | "flood") ?? "drip"
  );
  const [emitterFlow, setEmitterFlow] = useState(current?.emitter_flow_lph?.toString() ?? "");
  const [emitterSpacing, setEmitterSpacing] = useState(current?.emitter_spacing_m?.toString() ?? "");
  const [appRate, setAppRate] = useState(current?.application_rate_mm_h?.toString() ?? "");
  const [efficiency, setEfficiency] = useState(current?.efficiency?.toString() ?? "0.90");
  const [du, setDu] = useState(current?.distribution_uniformity?.toString() ?? "0.90");
  const [maxRuntime, setMaxRuntime] = useState(current?.max_runtime_hours?.toString() ?? "");
  const [minMm, setMinMm] = useState(current?.min_irrigation_mm?.toString() ?? "");
  const [maxMm, setMaxMm] = useState(current?.max_irrigation_mm?.toString() ?? "");

  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  // Sync if parent passes updated data
  useEffect(() => {
    if (!current) return;
    setSystemType((current.system_type as "drip" | "sprinkler" | "center_pivot" | "flood") ?? "drip");
    setEmitterFlow(current.emitter_flow_lph?.toString() ?? "");
    setEmitterSpacing(current.emitter_spacing_m?.toString() ?? "");
    setAppRate(current.application_rate_mm_h?.toString() ?? "");
    setEfficiency(current.efficiency?.toString() ?? "0.90");
    setDu(current.distribution_uniformity?.toString() ?? "0.90");
    setMaxRuntime(current.max_runtime_hours?.toString() ?? "");
    setMinMm(current.min_irrigation_mm?.toString() ?? "");
    setMaxMm(current.max_irrigation_mm?.toString() ?? "");
  }, [current]);

  async function handleSave() {
    const effVal = parseFloat(efficiency);
    const duVal = parseFloat(du);
    if (isNaN(effVal) || effVal <= 0 || effVal > 1) {
      setError("A eficiência deve ser um valor entre 0 e 1.");
      return;
    }
    if (isNaN(duVal) || duVal <= 0 || duVal > 1) {
      setError("A uniformidade de distribuição deve ser um valor entre 0 e 1.");
      return;
    }
    if (emitterFlow && parseFloat(emitterFlow) <= 0) {
      setError("O caudal do gotejador deve ser positivo.");
      return;
    }
    if (appRate && parseFloat(appRate) <= 0) {
      setError("A taxa de aplicação deve ser positiva.");
      return;
    }

    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      await sectorsApi.createIrrigationSystem(sectorId, {
        system_type: systemType as "drip" | "center_pivot" | "sprinkler" | "flood",
        emitter_flow_lph: emitterFlow ? parseFloat(emitterFlow) : undefined,
        emitter_spacing_m: emitterSpacing ? parseFloat(emitterSpacing) : undefined,
        application_rate_mm_h: appRate ? parseFloat(appRate) : undefined,
        efficiency: effVal,
        distribution_uniformity: duVal,
        max_runtime_hours: maxRuntime ? parseFloat(maxRuntime) : undefined,
        min_irrigation_mm: minMm ? parseFloat(minMm) : undefined,
        max_irrigation_mm: maxMm ? parseFloat(maxMm) : undefined,
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
      onSaved?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao guardar sistema de rega.");
    } finally {
      setSaving(false);
    }
  }

  const isDrip = systemType === "drip";
  const hasPressurised = systemType === "sprinkler" || systemType === "center_pivot";

  return (
    <div className="space-y-5">
      {/* Type */}
      <Select
        label="Tipo de sistema"
        value={systemType}
        onChange={(e) => setSystemType(e.target.value as "drip" | "sprinkler" | "center_pivot" | "flood")}
        options={SYSTEM_TYPES}
        hint="O tipo de sistema define como a água é distribuída no campo."
      />

      {/* Drip-specific */}
      {isDrip && (
        <div className="grid grid-cols-2 gap-3">
          <Input
            label="Caudal do gotejador (l/h)"
            type="number"
            value={emitterFlow}
            onChange={(e) => setEmitterFlow(e.target.value)}
            placeholder="ex. 2.0"
            step="0.1"
            min="0"
            hint="Caudal nominal por gotejador."
          />
          <Input
            label="Espaçamento entre gotejadores (m)"
            type="number"
            value={emitterSpacing}
            onChange={(e) => setEmitterSpacing(e.target.value)}
            placeholder="ex. 0.50"
            step="0.05"
            min="0"
            hint="Distância entre gotejadores na linha."
          />
        </div>
      )}

      {/* Application rate — computed from drip config or entered directly */}
      <Input
        label={isDrip ? "Taxa de aplicação (mm/h) — opcional se gotejadores configurados" : "Taxa de aplicação (mm/h)"}
        type="number"
        value={appRate}
        onChange={(e) => setAppRate(e.target.value)}
        placeholder="ex. 3.0"
        step="0.1"
        min="0"
        hint={
          isDrip
            ? "Sobrepõe o cálculo automático a partir do gotejador. Deixe em branco para calcular."
            : hasPressurised
              ? "Taxa de precipitação do aspersor ou pivot (mm/h)."
              : "Taxa de avanço da frente de água (mm/h)."
        }
      />

      {/* Efficiency & DU */}
      <div className="grid grid-cols-2 gap-3">
        <Input
          label="Eficiência (0–1)"
          type="number"
          value={efficiency}
          onChange={(e) => setEfficiency(e.target.value)}
          placeholder="0.90"
          step="0.01"
          min="0.01"
          max="1"
          hint="Fracção da água que chega à zona radicular."
        />
        <Input
          label="Uniformidade DU (0–1)"
          type="number"
          value={du}
          onChange={(e) => setDu(e.target.value)}
          placeholder="0.90"
          step="0.01"
          min="0.01"
          max="1"
          hint="Uniformidade de distribuição no campo."
        />
      </div>

      {/* Constraints — collapsible feel via section header */}
      <div className="space-y-3 rounded-xl border border-black/[0.07] bg-irrigai-surface p-4">
        <p className="text-[12px] font-medium uppercase tracking-[0.05em] text-irrigai-text-hint">
          Limites operacionais (opcional)
        </p>
        <div className="grid grid-cols-3 gap-3">
          <Input
            label="Tempo máx. (h)"
            type="number"
            value={maxRuntime}
            onChange={(e) => setMaxRuntime(e.target.value)}
            placeholder="ex. 8"
            step="0.5"
            min="0"
          />
          <Input
            label="Dose mín. (mm)"
            type="number"
            value={minMm}
            onChange={(e) => setMinMm(e.target.value)}
            placeholder="ex. 4"
            step="0.5"
            min="0"
          />
          <Input
            label="Dose máx. (mm)"
            type="number"
            value={maxMm}
            onChange={(e) => setMaxMm(e.target.value)}
            placeholder="ex. 30"
            step="0.5"
            min="0"
          />
        </div>
      </div>

      {error && (
        <p className="text-[13px] font-medium text-irrigai-red">{error}</p>
      )}

      <div className="flex items-center gap-3">
        <Button onClick={handleSave} loading={saving}>
          Guardar configuração
        </Button>
        {saved && (
          <span className="flex items-center gap-1.5 text-[13px] font-medium text-irrigai-green">
            <CheckCircle className="h-4 w-4" />
            Guardado
          </span>
        )}
      </div>

      {current && (
        <div className="rounded-xl border border-black/[0.07] bg-white px-4 py-3 space-y-1">
          <p className="text-[11px] font-medium uppercase tracking-[0.05em] text-irrigai-text-hint mb-2">
            Configuração actual
          </p>
          <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-[12px]">
            <Row label="Tipo" value={SYSTEM_TYPES.find(t => t.value === current.system_type)?.label ?? current.system_type} />
            <Row label="Eficiência" value={`${(current.efficiency * 100).toFixed(0)}%`} />
            <Row label="DU" value={`${(current.distribution_uniformity * 100).toFixed(0)}%`} />
            {current.application_rate_mm_h != null && (
              <Row label="Taxa aplic." value={`${current.application_rate_mm_h} mm/h`} />
            )}
            {current.emitter_flow_lph != null && (
              <Row label="Caudal gotej." value={`${current.emitter_flow_lph} l/h`} />
            )}
            {current.max_runtime_hours != null && (
              <Row label="Tempo máx." value={`${current.max_runtime_hours} h`} />
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
      <span className="text-irrigai-text-muted">{label}</span>
      <span className="font-medium text-irrigai-text">{value}</span>
    </div>
  );
}
