"use client";

import { useEffect, useState } from "react";
import { gddApi, sectorsApi } from "@/lib/api";
import { CROP_STAGES } from "@/lib/cropConfig";
import type { GDDStatus } from "@/types";

interface Props {
  sectorId: string;
  cropType: string;
  sowingDate: string | null;
  currentStage: string | null;
  onStageConfirmed?: () => void;
  onSetupSaved?: () => void;
}

export function GDDStatusCard({
  sectorId,
  cropType,
  sowingDate,
  currentStage,
  onStageConfirmed,
  onSetupSaved,
}: Props) {
  const [status, setStatus] = useState<GDDStatus | null>(null);
  const [loadState, setLoadState] = useState<"loading" | "ok" | "incomplete" | "unavailable">("loading");
  const [confirming, setConfirming] = useState(false);

  // Setup / manual form state
  const [setupSowingDate, setSetupSowingDate] = useState(sowingDate ?? "");
  const [manualStage, setManualStage] = useState(currentStage ?? "");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [stageSaved, setStageSaved] = useState(false);

  const stageOptions = CROP_STAGES[cropType] ?? CROP_STAGES["olive"];

  useEffect(() => {
    setSetupSowingDate(sowingDate ?? "");
  }, [sowingDate]);

  useEffect(() => {
    setManualStage(currentStage ?? "");
  }, [currentStage]);

  useEffect(() => {
    loadGDD();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sectorId]);

  async function loadGDD() {
    setLoadState("loading");
    try {
      const s = await gddApi.getSector(sectorId);
      setStatus(s);
      // Low confidence = missing weather history → can't trust auto-suggestions
      setLoadState(s.confidence === "low" ? "incomplete" : "ok");
    } catch {
      setStatus(null);
      setLoadState("unavailable");
    }
  }

  async function handleConfirm(stage?: string) {
    setConfirming(true);
    try {
      await gddApi.confirm(sectorId, stage);
      if (status) {
        setStatus({
          ...status,
          current_stage: stage ?? status.suggested_stage ?? status.current_stage,
          stage_changed: false,
        });
      }
      onStageConfirmed?.();
    } finally {
      setConfirming(false);
    }
  }

  async function handleSaveManualStage() {
    if (!manualStage) return;
    setSaving(true);
    setSaveError(null);
    setStageSaved(false);
    try {
      await sectorsApi.update(sectorId, { current_phenological_stage: manualStage });
      setStageSaved(true);
      setTimeout(() => setStageSaved(false), 2500);
      onSetupSaved?.();
    } catch {
      setSaveError("Erro ao guardar. Tente novamente.");
    } finally {
      setSaving(false);
    }
  }

  async function handleSaveSowingDate() {
    if (!setupSowingDate) return;
    setSaving(true);
    setSaveError(null);
    try {
      await sectorsApi.update(sectorId, { sowing_date: setupSowingDate });
      onSetupSaved?.();
      await loadGDD();
    } catch {
      setSaveError("Erro ao guardar. Tente novamente.");
    } finally {
      setSaving(false);
    }
  }

  // ── Loading ─────────────────────────────────────────────────────────────────
  if (loadState === "loading") {
    return (
      <div className="rounded-xl border border-black/[0.08] bg-white px-4 py-3.5 animate-pulse">
        <div className="h-3 w-28 rounded bg-irrigai-surface mb-3" />
        <div className="h-7 w-16 rounded bg-irrigai-surface" />
      </div>
    );
  }

  // ── Incomplete weather data: show manual stage entry ─────────────────────────
  if (loadState === "incomplete") {
    const missingDays = status?.missing_weather_days ?? 0;
    const stageChanged = manualStage !== (currentStage ?? "");

    return (
      <div className="rounded-xl border border-black/[0.08] bg-white px-4 py-4 space-y-3">
        <p className="text-[11px] font-medium uppercase tracking-[0.05em] text-irrigai-text-hint">
          GDD Fenológico
        </p>

        <div className="rounded-lg bg-irrigai-amber/10 border border-irrigai-amber/30 px-3 py-2.5">
          <p className="text-[12px] text-irrigai-text">
            Dados meteorológicos insuficientes ({missingDays} dias em falta). O modelo não consegue
            determinar automaticamente a fase fenológica.
          </p>
        </div>

        <div>
          <label className="mb-1 block text-[12px] font-medium text-irrigai-text">
            Fase fenológica actual
          </label>
          <select
            value={manualStage}
            onChange={(e) => { setManualStage(e.target.value); setStageSaved(false); }}
            className="w-full rounded-lg border border-black/[0.1] bg-white px-3.5 py-2.5 text-[13px] focus:border-irrigai-green focus:outline-none focus:ring-1 focus:ring-irrigai-green/30"
          >
            <option value="">Seleccione a fase…</option>
            {stageOptions.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
          <p className="mt-1 text-[11px] text-irrigai-text-hint">
            Confirme a fase observada no campo. Será usada pelo motor de recomendação enquanto os dados
            meteorológicos estiverem incompletos.
          </p>
        </div>

        {saveError && <p className="text-[12px] text-irrigai-red">{saveError}</p>}

        <div className="flex items-center gap-3">
          <button
            onClick={handleSaveManualStage}
            disabled={!manualStage || !stageChanged || saving}
            className="flex-1 rounded-lg bg-irrigai-green px-3 py-2.5 text-[12px] font-medium text-white hover:bg-irrigai-green/90 disabled:opacity-50 transition-colors"
          >
            {saving ? "A guardar…" : "Confirmar fase"}
          </button>
          {stageSaved && (
            <span className="text-[12px] text-irrigai-green font-medium">Guardado ✓</span>
          )}
        </div>
      </div>
    );
  }

  // ── GDD unavailable (no profile / no sowing date): show setup form ───────────
  if (loadState === "unavailable") {
    const isMaize = cropType === "maize";

    return (
      <div className="rounded-xl border border-black/[0.08] bg-white px-4 py-4 space-y-3">
        <p className="text-[11px] font-medium uppercase tracking-[0.05em] text-irrigai-text-hint">
          GDD Fenológico
        </p>

        {isMaize ? (
          <>
            <p className="text-[13px] text-irrigai-text-muted">
              Para activar o modelo fenológico por GDD, indique a data de sementeira.
            </p>
            <div>
              <label className="mb-1 block text-[12px] font-medium text-irrigai-text">
                Data de sementeira
              </label>
              <input
                type="date"
                value={setupSowingDate}
                onChange={(e) => setSetupSowingDate(e.target.value)}
                max={new Date().toISOString().split("T")[0]}
                className="w-full rounded-lg border border-black/[0.1] bg-white px-3.5 py-2.5 text-[13px] focus:border-irrigai-green focus:outline-none focus:ring-1 focus:ring-irrigai-green/30"
              />
            </div>
            {saveError && <p className="text-[12px] text-irrigai-red">{saveError}</p>}
            <button
              onClick={handleSaveSowingDate}
              disabled={!setupSowingDate || saving}
              className="w-full rounded-lg bg-irrigai-green px-3 py-2.5 text-[12px] font-medium text-white hover:bg-irrigai-green/90 disabled:opacity-50 transition-colors"
            >
              {saving ? "A guardar…" : "Guardar e activar GDD"}
            </button>
          </>
        ) : (
          <p className="text-[13px] text-irrigai-text-muted">
            Modelo fenológico por GDD não disponível. O perfil de cultura precisa de ter limiares GDD
            configurados por fase.
          </p>
        )}
      </div>
    );
  }

  // ── GDD available with high confidence ──────────────────────────────────────
  if (!status) return null;

  const showSuggestion = status.stage_changed && status.suggested_stage;

  return (
    <div className="rounded-xl border border-black/[0.08] bg-white px-4 py-3.5">
      <div className="flex items-center justify-between mb-2">
        <p className="text-[11px] font-medium uppercase tracking-[0.05em] text-irrigai-text-hint">
          GDD Fenológico
        </p>
      </div>

      {/* GDD progress */}
      <div className="flex items-baseline gap-2 mb-2">
        <span className="font-display text-[20px] font-[500] text-irrigai-text tabular-nums">
          {status.accumulated_gdd.toFixed(0)}
        </span>
        <span className="text-[12px] text-irrigai-text-muted">
          GDD desde{" "}
          {new Date(status.reference_date).toLocaleDateString("pt-PT", {
            day: "numeric",
            month: "short",
          })}
          {" (Tbase "}
          {status.tbase_c}°C)
        </span>
      </div>

      {/* Stage progress bar */}
      {status.next_stage && status.gdd_to_next_stage != null && (
        <div className="mb-3">
          <div className="h-1.5 w-full rounded-full bg-black/[0.06] overflow-hidden">
            <div
              className="h-1.5 rounded-full bg-irrigai-green transition-all"
              style={{
                width: `${Math.min(
                  100,
                  100 -
                    (status.gdd_to_next_stage /
                      (status.gdd_to_next_stage + status.accumulated_gdd)) *
                      100
                )}%`,
              }}
            />
          </div>
          <p className="mt-1 text-[11px] text-irrigai-text-hint">
            {status.gdd_to_next_stage.toFixed(0)} GDD para{" "}
            {status.next_stage_name_pt ?? status.next_stage}
          </p>
        </div>
      )}

      {/* Stage suggestion */}
      {showSuggestion ? (
        <div className="rounded-lg bg-irrigai-amber/10 border border-irrigai-amber/30 px-3 py-2.5 mb-2">
          <p className="text-[12px] text-irrigai-text mb-2">{status.suggestion_pt}</p>
          <div className="flex gap-2">
            <button
              onClick={() => handleConfirm()}
              disabled={confirming}
              className="flex-1 rounded-lg bg-irrigai-green px-2.5 py-1.5 text-[11px] font-medium text-white hover:bg-irrigai-green/90 disabled:opacity-50 transition-colors"
            >
              {confirming
                ? "A confirmar…"
                : `Confirmar ${status.suggested_stage_name_pt ?? status.suggested_stage}`}
            </button>
            <button
              onClick={() => handleConfirm(status.current_stage ?? undefined)}
              disabled={confirming}
              className="rounded-lg border border-black/[0.08] px-2.5 py-1.5 text-[11px] font-medium text-irrigai-text-muted hover:bg-black/[0.04] disabled:opacity-50 transition-colors"
            >
              Manter atual
            </button>
          </div>
        </div>
      ) : status.current_stage ? (
        <p className="text-[12px] text-irrigai-text-muted">
          Fase atual confirmada
          {status.days_in_current_stage != null &&
            ` · há ${status.days_in_current_stage} dias`}
        </p>
      ) : null}
    </div>
  );
}
