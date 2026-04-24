"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { OnboardingProgress } from "@/components/onboarding/OnboardingProgress";
import { SoilSelector } from "@/components/onboarding/SoilSelector";
import { CropTypeSelector } from "@/components/onboarding/CropTypeSelector";
import { PhenologicalTimeline } from "@/components/onboarding/PhenologicalTimeline";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Logo } from "@/components/ui/Logo";
import { farmsApi, plotsApi, sectorsApi } from "@/lib/api";
import type { CropProfileTemplate, CropStage, Farm, Plot, Sector, SoilPreset } from "@/types";

const TIMEZONES = [
  { value: "Europe/Lisbon", label: "Lisboa (UTC+0/+1)" },
  { value: "Europe/Madrid", label: "Madrid (UTC+1/+2)" },
  { value: "America/Sao_Paulo", label: "São Paulo (UTC-3)" },
];

const IRRIGATION_TYPES = [
  { value: "drip", label: "Gota-a-gota" },
  { value: "sprinkler", label: "Aspersão" },
  { value: "center_pivot", label: "Pivot central" },
  { value: "flood", label: "Gravidade / Inundação" },
];

export default function OnboardingPage() {
  const router = useRouter();
  const [step, setStep] = useState(1);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Step 1 — Farm
  const [farmName, setFarmName] = useState("");
  const [region, setRegion] = useState("");
  const [timezone, setTimezone] = useState("Europe/Lisbon");

  // Step 2 — Plot & Soil
  const [plotName, setPlotName] = useState("");
  const [soilPreset, setSoilPreset] = useState<SoilPreset | null>(null);

  // Step 3 — Sector & Crop
  const [sectorName, setSectorName] = useState("");
  const [cropTemplate, setCropTemplate] = useState<CropProfileTemplate | null>(null);
  const [currentStage, setCurrentStage] = useState<CropStage | null>(null);
  const [plantingYear, setPlantingYear] = useState("");

  // Step 4 — Irrigation system
  const [irrigationType, setIrrigationType] = useState("drip");
  const [emitterFlow, setEmitterFlow] = useState("");
  const [appRateMmH, setAppRateMmH] = useState("");
  const [efficiency, setEfficiency] = useState("0.90");
  const [distributionUniformity, setDistributionUniformity] = useState("0.90");

  // Created entities (used across steps)
  const [createdFarm, setCreatedFarm] = useState<Farm | null>(null);
  const [createdPlot, setCreatedPlot] = useState<Plot | null>(null);
  const [createdSector, setCreatedSector] = useState<Sector | null>(null);

  function nextStep() {
    setError(null);
    setStep((s) => s + 1);
  }

  async function saveFarm() {
    if (!farmName.trim()) {
      setError("O nome da exploração é obrigatório.");
      return;
    }
    setSaving(true);
    try {
      const farm = await farmsApi.create({
        name: farmName.trim(),
        region: region || undefined,
        timezone,
      });
      setCreatedFarm(farm);
      nextStep();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao criar exploração");
    } finally {
      setSaving(false);
    }
  }

  async function savePlot() {
    if (!plotName.trim()) {
      setError("O nome do talhão é obrigatório.");
      return;
    }
    if (!createdFarm) return;
    setSaving(true);
    try {
      const plot = await plotsApi.create(createdFarm.id, {
        name: plotName.trim(),
        soil_preset_id: soilPreset?.id,
        field_capacity: soilPreset?.field_capacity,
        wilting_point: soilPreset?.wilting_point,
        soil_texture: soilPreset?.texture,
      });
      setCreatedPlot(plot);
      nextStep();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao criar talhão");
    } finally {
      setSaving(false);
    }
  }

  async function saveSector() {
    if (!sectorName.trim() || !cropTemplate || !createdPlot) {
      setError("Preencha o nome do sector e seleccione a cultura.");
      return;
    }
    setSaving(true);
    try {
      const sector = await sectorsApi.create(createdPlot.id, {
        name: sectorName.trim(),
        crop_type: cropTemplate.crop_type,
        planting_year: plantingYear ? parseInt(plantingYear, 10) : undefined,
        current_phenological_stage: currentStage?.name,
      });
      // Apply crop profile from template
      await sectorsApi.resetCropProfile(sector.id, cropTemplate.id);
      setCreatedSector(sector);
      nextStep();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao criar sector");
    } finally {
      setSaving(false);
    }
  }

  async function saveIrrigationAndFinish() {
    if (!createdFarm || !createdSector) return;

    const effVal = parseFloat(efficiency);
    const duVal = parseFloat(distributionUniformity);
    if (isNaN(effVal) || effVal <= 0 || effVal > 1) {
      setError("A eficiência deve ser um valor entre 0 e 1 (ex: 0.90).");
      return;
    }
    if (isNaN(duVal) || duVal <= 0 || duVal > 1) {
      setError("A uniformidade de distribuição deve ser um valor entre 0 e 1 (ex: 0.90).");
      return;
    }
    if (emitterFlow) {
      const v = parseFloat(emitterFlow);
      if (isNaN(v) || v <= 0) {
        setError("O caudal do gotejador deve ser um número positivo.");
        return;
      }
    }
    if (appRateMmH) {
      const v = parseFloat(appRateMmH);
      if (isNaN(v) || v <= 0) {
        setError("A taxa de aplicação deve ser um número positivo.");
        return;
      }
    }

    setSaving(true);
    try {
      await sectorsApi.createIrrigationSystem(createdSector.id, {
        system_type: irrigationType as "drip" | "center_pivot" | "sprinkler" | "flood",
        emitter_flow_lph: emitterFlow ? parseFloat(emitterFlow) : undefined,
        application_rate_mm_h: appRateMmH ? parseFloat(appRateMmH) : undefined,
        efficiency: effVal,
        distribution_uniformity: duVal,
      });
      router.push(`/farms/${createdFarm.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao guardar sistema de rega");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="min-h-screen">
      {/* Minimal header */}
      <header className="border-b border-slate-200/80 bg-white/95 shadow-[0_1px_3px_rgba(0,0,0,0.05)] backdrop-blur-sm">
        <div className="mx-auto flex h-14 max-w-2xl items-center justify-between px-4 sm:px-6">
          <Link href="/" className="flex items-center gap-2 rounded-lg p-0.5 transition-opacity hover:opacity-75" aria-label="Voltar ao início">
            <Logo size={28} />
            <span className="text-base font-bold tracking-tight text-slate-900">IrrigAI</span>
          </Link>
          <Link
            href="/"
            className="inline-flex items-center gap-1.5 text-sm font-medium text-slate-500 transition-colors hover:text-slate-900"
          >
            <ArrowLeft className="h-4 w-4" />
            Início
          </Link>
        </div>
      </header>

      <div className="px-4 py-8 sm:px-6 sm:py-10">
      <div className="mx-auto max-w-2xl">
        <div className="mb-6 rounded-[2rem] border border-emerald-100 bg-white/90 px-6 py-7 text-center shadow-sm">
          <p className="text-xs font-semibold uppercase tracking-[0.25em] text-emerald-700">
            Configuração guiada
          </p>
          <h1 className="mt-2 text-3xl font-bold tracking-tight text-slate-950">Configure a sua exploração</h1>
          <p className="mt-2 text-sm leading-6 text-slate-600">
            Complete os quatro passos para criar a exploração, o talhão, o sector e o sistema de rega.
          </p>
        </div>

        <OnboardingProgress currentStep={step} />

        {error && (
          <div
            aria-live="polite"
            className="mb-4 rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
          >
            {error}
          </div>
        )}

        <div className="rounded-[2rem] border border-slate-200 bg-white/95 p-6 shadow-sm sm:p-7">
          {/* Step 1: Farm */}
          {step === 1 && (
            <div className="space-y-5">
              <div className="space-y-1">
                <h2 className="text-xl font-semibold tracking-tight text-slate-950">Dados da exploração</h2>
                <p className="text-sm text-slate-500">
                  Defina a identificação principal da exploração e o fuso horário usado para relatórios e recomendações.
                </p>
              </div>
              <Input
                label="Nome da exploração *"
                value={farmName}
                onChange={(e) => setFarmName(e.target.value)}
                placeholder="ex. Herdade do Monte Novo"
                hint="Nome visível no dashboard principal."
              />
              <Input
                label="Região"
                value={region}
                onChange={(e) => setRegion(e.target.value)}
                placeholder="ex. Alentejo"
                hint="Opcional, mas útil para contexto operacional e validação manual."
              />
              <Select
                label="Fuso horário"
                value={timezone}
                onChange={(e) => setTimezone(e.target.value)}
                options={TIMEZONES}
                hint="Escolha o fuso local da exploração para alinhar datas e horas."
              />
              <div className="flex justify-end pt-2">
                <Button onClick={saveFarm} loading={saving} className="w-full sm:w-auto">
                  Seguinte →
                </Button>
              </div>
            </div>
          )}

          {/* Step 2: Plot & Soil */}
          {step === 2 && (
            <div className="space-y-5">
              <div className="space-y-1">
                <h2 className="text-xl font-semibold tracking-tight text-slate-950">Talhão e tipo de solo</h2>
                <p className="text-sm text-slate-500">
                  Associe o primeiro talhão e seleccione uma textura de solo para carregar parâmetros agronómicos iniciais.
                </p>
              </div>
              <Input
                label="Nome do talhão *"
                value={plotName}
                onChange={(e) => setPlotName(e.target.value)}
                placeholder="ex. Talhão Norte"
                hint="Use um nome operativo fácil de reconhecer no campo."
              />
              <SoilSelector
                value={soilPreset?.id ?? null}
                onChange={setSoilPreset}
              />
              {soilPreset && (
                <div className="rounded-2xl border border-emerald-100 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
                  Solo seleccionado: <strong>{soilPreset.name_pt}</strong> —{" "}
                  {soilPreset.taw_mm_per_m.toFixed(0)} mm/m de água disponível
                </div>
              )}
              <div className="flex flex-col-reverse justify-between gap-3 pt-2 sm:flex-row">
                <Button variant="ghost" onClick={() => setStep(1)} className="w-full sm:w-auto">
                  ← Anterior
                </Button>
                <Button onClick={savePlot} loading={saving} className="w-full sm:w-auto">
                  Seguinte →
                </Button>
              </div>
            </div>
          )}

          {/* Step 3: Sector & Crop */}
          {step === 3 && (
            <div className="space-y-5">
              <div className="space-y-1">
                <h2 className="text-xl font-semibold tracking-tight text-slate-950">Sector e cultura</h2>
                <p className="text-sm text-slate-500">
                  Dê contexto agronómico ao sector para que o perfil de cultura e a fase fenológica fiquem prontos para análise.
                </p>
              </div>
              <Input
                label="Nome do sector *"
                value={sectorName}
                onChange={(e) => setSectorName(e.target.value)}
                placeholder="ex. Olivais Sul"
                hint="Este nome aparece nos cartões de sector e nos alertas."
              />
              <Input
                label="Ano de plantação"
                type="number"
                value={plantingYear}
                onChange={(e) => setPlantingYear(e.target.value)}
                placeholder="ex. 2015"
                inputMode="numeric"
                hint="Opcional. Útil para relatórios e contexto técnico."
              />
              <CropTypeSelector
                value={cropTemplate?.crop_type ?? null}
                onChange={setCropTemplate}
              />
              {cropTemplate && (
                <PhenologicalTimeline
                  stages={cropTemplate.stages}
                  currentStage={currentStage?.name}
                  onSelect={setCurrentStage}
                />
              )}
              <div className="flex flex-col-reverse justify-between gap-3 pt-2 sm:flex-row">
                <Button variant="ghost" onClick={() => setStep(2)} className="w-full sm:w-auto">
                  ← Anterior
                </Button>
                <Button onClick={saveSector} loading={saving} className="w-full sm:w-auto">
                  Seguinte →
                </Button>
              </div>
            </div>
          )}

          {/* Step 4: Irrigation system */}
          {step === 4 && (
            <div className="space-y-5">
              <div className="space-y-1">
                <h2 className="text-xl font-semibold tracking-tight text-slate-950">Sistema de rega</h2>
                <p className="text-sm text-slate-500">
                  Introduza apenas os parâmetros essenciais para a primeira geração de recomendações. Pode afiná-los depois.
                </p>
              </div>
              <Select
                label="Tipo de sistema"
                value={irrigationType}
                onChange={(e) => setIrrigationType(e.target.value)}
                options={IRRIGATION_TYPES}
                hint="Escolha o sistema que representa melhor o sector criado."
              />
              {(irrigationType === "drip") && (
                <Input
                  label="Caudal do gotejador (l/h)"
                  type="number"
                  value={emitterFlow}
                  onChange={(e) => setEmitterFlow(e.target.value)}
                  placeholder="ex. 2.0"
                  step="0.1"
                  inputMode="decimal"
                  hint="Opcional. Melhora a estimativa de duração da rega."
                />
              )}
              {(irrigationType === "sprinkler" || irrigationType === "center_pivot") && (
                <Input
                  label="Taxa de aplicação (mm/h)"
                  type="number"
                  value={appRateMmH}
                  onChange={(e) => setAppRateMmH(e.target.value)}
                  placeholder="ex. 5.0"
                  step="0.5"
                  inputMode="decimal"
                  hint="Opcional. Usado para calcular a duração da aplicação."
                />
              )}
              <Input
                label="Eficiência do sistema (0–1)"
                type="number"
                value={efficiency}
                onChange={(e) => setEfficiency(e.target.value)}
                placeholder="0.90"
                step="0.01"
                min="0"
                max="1"
                hint="Fracção da água aplicada que chega à zona radicular. Tipicamente 0.85–0.95 para gota-a-gota."
              />
              <Input
                label="Uniformidade de distribuição — DU (0–1)"
                type="number"
                value={distributionUniformity}
                onChange={(e) => setDistributionUniformity(e.target.value)}
                placeholder="0.90"
                step="0.01"
                min="0"
                max="1"
                hint="Uniformidade com que a água é distribuída no campo. Gota-a-gota novo ≈ 0.90–0.95; sistema mais antigo ≈ 0.75–0.85."
              />
              <div className="flex flex-col-reverse justify-between gap-3 pt-2 sm:flex-row">
                <Button variant="ghost" onClick={() => setStep(3)} className="w-full sm:w-auto">
                  ← Anterior
                </Button>
                <Button onClick={saveIrrigationAndFinish} loading={saving} className="w-full sm:w-auto">
                  Concluir configuração
                </Button>
              </div>
            </div>
          )}
        </div>
      </div>
      </div>
    </div>
  );
}
