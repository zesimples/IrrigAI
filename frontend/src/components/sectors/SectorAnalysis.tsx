"use client";

import { useEffect, useState } from "react";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import { chatApi, sectorsApi, catalogApi } from "@/lib/api";
import { CROP_STAGES } from "@/lib/cropConfig";
import type { SoilPreset } from "@/types";

const SOIL_CONDITION_OPTIONS = [
  { value: "", label: "Não avaliado" },
  { value: "very_dry", label: "Muito seco — solo a fender" },
  { value: "dry", label: "Seco — pouco húmido na mão" },
  { value: "adequate", label: "Adequado — húmido mas solto" },
  { value: "moist", label: "Húmido — compacta com pressão" },
  { value: "wet", label: "Encharcado — água visível" },
];

interface Props {
  sectorId: string;
  cropType: string;
  currentStage: string | null;
  currentSoilPresetId?: string | null;
  onStageUpdated?: () => void;
}

export function SectorAnalysis({ sectorId, cropType, currentStage, currentSoilPresetId, onStageUpdated }: Props) {
  const stageOptions = CROP_STAGES[cropType] ?? CROP_STAGES["olive"];

  const [stage, setStage] = useState(currentStage ?? "");
  const [soilCondition, setSoilCondition] = useState("");
  const [notes, setNotes] = useState("");
  const [loading, setLoading] = useState(false);
  const [updatingStage, setUpdatingStage] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Soil preset state
  const [soilPresets, setSoilPresets] = useState<SoilPreset[]>([]);
  const [selectedSoilId, setSelectedSoilId] = useState(currentSoilPresetId ?? "");
  const [savingSoil, setSavingSoil] = useState(false);
  const [soilSaved, setSoilSaved] = useState(false);

  useEffect(() => { setStage(currentStage ?? ""); }, [currentStage]);
  useEffect(() => { setSelectedSoilId(currentSoilPresetId ?? ""); }, [currentSoilPresetId]);

  useEffect(() => {
    catalogApi.soilPresets().then(setSoilPresets).catch(() => {});
  }, []);

  const soilOptions = [
    { value: "", label: "Solo do talhão (padrão)" },
    ...soilPresets.map((p) => ({
      value: p.id,
      label: `${p.name_pt} — CC ${(p.field_capacity * 100).toFixed(0)}% · CMP ${(p.wilting_point * 100).toFixed(0)}%`,
    })),
  ];

  const soilChanged = selectedSoilId !== (currentSoilPresetId ?? "");

  async function handleSaveSoil() {
    setSavingSoil(true);
    setSoilSaved(false);
    try {
      const preset = soilPresets.find((p) => p.id === selectedSoilId);
      await sectorsApi.updateCropProfile(sectorId, {
        soil_preset_id: selectedSoilId || null,
        field_capacity: preset?.field_capacity ?? null,
        wilting_point: preset?.wilting_point ?? null,
      });
      setSoilSaved(true);
      setTimeout(() => setSoilSaved(false), 2500);
    } finally {
      setSavingSoil(false);
    }
  }

  async function handleUpdateStage() {
    if (!stage) return;
    setUpdatingStage(true);
    try {
      await sectorsApi.update(sectorId, { current_phenological_stage: stage });
      onStageUpdated?.();
    } finally {
      setUpdatingStage(false);
    }
  }

  async function handleAnalyse() {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const soilLabel = SOIL_CONDITION_OPTIONS.find(o => o.value === soilCondition)?.label ?? "";
      const userNotes = [
        soilCondition ? `Estado visual do solo: ${soilLabel}` : "",
        notes.trim() ? `Observações: ${notes.trim()}` : "",
      ].filter(Boolean).join("\n") || undefined;
      const res = await chatApi.explainSector(sectorId, userNotes);
      setResult(res.explanation);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Erro ao contactar o assistente.");
    } finally {
      setLoading(false);
    }
  }

  const stageChanged = stage !== (currentStage ?? "");

  return (
    <Card>
      <CardHeader>
        <CardTitle>Análise com assistente IA</CardTitle>
      </CardHeader>
      <CardBody className="space-y-4">
        <p className="text-sm leading-6 text-slate-500">
          Preencha as observações de campo e peça uma análise ao assistente. Os dados dos sensores e da meteorologia são incluídos automaticamente.
        </p>

        {/* Soil type */}
        <div>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
            <div className="flex-1">
              <Select
                label="Tipo de solo"
                value={selectedSoilId}
                onChange={(e) => { setSelectedSoilId(e.target.value); setSoilSaved(false); }}
                options={soilOptions}
                hint="Define capacidade de campo (CC) e coeficiente de murchamento permanente (CMP) usados no cálculo."
              />
            </div>
            {soilChanged && (
              <Button
                size="sm"
                variant="secondary"
                onClick={handleSaveSoil}
                loading={savingSoil}
                className="w-full sm:w-auto"
              >
                Guardar
              </Button>
            )}
            {soilSaved && !soilChanged && (
              <span className="text-[12px] text-irrigai-green font-medium">Guardado ✓</span>
            )}
          </div>
          {selectedSoilId && (() => {
            const p = soilPresets.find(x => x.id === selectedSoilId);
            if (!p) return null;
            return (
              <p className="mt-1.5 text-[11px] text-irrigai-text-muted">
                TAW ≈ <strong>{p.taw_mm_per_m}</strong> mm/m profundidade radicular
              </p>
            );
          })()}
        </div>

        {/* Phenological stage */}
        <div>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
            <div className="flex-1">
              <Select
                label="Fase fenológica actual"
                value={stage}
                onChange={(e) => setStage(e.target.value)}
                options={stageOptions}
                placeholder="Seleccione a fase…"
                hint="Actualize apenas se a fase real no campo tiver mudado."
              />
            </div>
            {stageChanged && (
              <Button
                size="sm"
                variant="secondary"
                onClick={handleUpdateStage}
                loading={updatingStage}
                className="w-full sm:w-auto"
              >
                Guardar
              </Button>
            )}
          </div>
        </div>

        {/* Visual soil assessment */}
        <Select
          label="Estado visual do solo (observação de campo)"
          value={soilCondition}
          onChange={(e) => setSoilCondition(e.target.value)}
          options={SOIL_CONDITION_OPTIONS}
          hint="Útil quando a percepção visual do solo não bate certo com a telemetria."
        />

        {/* Free-text observations */}
        <div>
          <label htmlFor="sector-observations" className="mb-1 block text-sm font-semibold text-slate-800">
            Observações adicionais
          </label>
          <textarea
            id="sector-observations"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={3}
            placeholder="Ex: Folhas com sinais de stress hídrico na manhã. Rega manual feita ontem à tarde…"
            className="w-full rounded-lg border border-black/[0.1] bg-white px-3.5 py-2.5 text-[13px] focus:border-irrigai-green focus:outline-none focus:ring-1 focus:ring-irrigai-green/30"
          />
        </div>

        <Button onClick={handleAnalyse} loading={loading} className="w-full">
          Pedir análise ao assistente IA
        </Button>

        {error && (
          <div className="rounded-lg border border-irrigai-red/20 bg-irrigai-red-bg px-4 py-3 text-[13px] text-irrigai-red-dark">
            {error}
          </div>
        )}

        {result && (
          <div className="rounded-lg border border-irrigai-green/20 bg-irrigai-green-bg px-4 py-4">
            <p className="mb-2 text-[11px] font-medium uppercase tracking-[0.05em] text-irrigai-green-dark">
              Análise do assistente
            </p>
            <p className="whitespace-pre-wrap text-[13px] leading-6 text-irrigai-text">{result}</p>
          </div>
        )}
      </CardBody>
    </Card>
  );
}
