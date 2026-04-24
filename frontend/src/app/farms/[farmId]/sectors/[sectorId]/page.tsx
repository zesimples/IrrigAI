"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useSectorStatus } from "@/hooks/useSectorDetail";
import { RecommendationDetail, RecHeader, ACTION_CONFIG } from "@/components/sectors/RecommendationDetail";
import { ProbeReadingsInline } from "@/components/probes/ProbeReadingsInline";
import { Button } from "@/components/ui/button";
import { AppHeader } from "@/components/ui/AppHeader";
import { BottomNav } from "@/components/ui/BottomNav";
import { recommendationsApi, sectorsApi } from "@/lib/api";
import { ChatButton } from "@/components/chat/ChatButton";
import { ActiveOverrides } from "@/components/overrides/ActiveOverrides";
import { SectorAnalysis } from "@/components/sectors/SectorAnalysis";
import { StressProjectionCard } from "@/components/sectors/StressProjectionCard";
import { AutoCalibrationCard } from "@/components/sectors/AutoCalibrationCard";
import { GDDStatusCard } from "@/components/sectors/GDDStatusCard";
import { IrrigationSystemForm } from "@/components/sectors/IrrigationSystemForm";
import { RefreshCw, Zap } from "lucide-react";
import type { RecommendationDetail as Rec, SectorCropProfile, StressProjection } from "@/types";
import { CROP_LABELS, STAGE_LABELS } from "@/lib/cropConfig";

interface Props {
  params: { farmId: string; sectorId: string };
}

const DEPLETION_COLOR = (pct: number) =>
  pct > 60 ? "text-irrigai-red" : pct > 40 ? "text-irrigai-amber" : "text-irrigai-green";
const DEPLETION_BAR = (pct: number) =>
  pct > 60 ? "bg-irrigai-red" : pct > 40 ? "bg-irrigai-amber" : "bg-irrigai-green";

export default function SectorDetailPage({ params }: Props) {
  const { farmId, sectorId } = params;
  const router = useRouter();
  const { data: status, loading, error, refetch } = useSectorStatus(sectorId);
  const [rec, setRec] = useState<Rec | null>(null);
  const [recLoading, setRecLoading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [cropProfile, setCropProfile] = useState<SectorCropProfile | null>(null);
  const [sectorDetail, setSectorDetail] = useState<import("@/types").SectorDetail | null>(null);
  const [activeTab, setActiveTab] = useState<"monit" | "rega" | "fenologia">("monit");
  const [liveStress, setLiveStress] = useState<StressProjection | null>(null);

  useEffect(() => {
    sectorsApi.cropProfile(sectorId).then(setCropProfile).catch(() => {});
    sectorsApi.get(sectorId).then(setSectorDetail).catch(() => {});
    sectorsApi.stressProjection(sectorId).then(setLiveStress).catch(() => {});
  }, [sectorId]);

  useEffect(() => {
    if (status?.latest_recommendation_id) {
      setRecLoading(true);
      recommendationsApi
        .get(status.latest_recommendation_id)
        .then(setRec)
        .finally(() => setRecLoading(false));
    }
  }, [status?.latest_recommendation_id]);

  async function generate() {
    setGenerating(true);
    try {
      const r = await sectorsApi.generateRecommendation(sectorId);
      const detail = await recommendationsApi.get(r.id);
      setRec(detail);
      await refetch();
      sectorsApi.stressProjection(sectorId).then(setLiveStress).catch(() => {});
    } finally {
      setGenerating(false);
    }
  }

  // ── Loading ──────────────────────────────────────────────────────────────────
  if (loading) {
    return (
      <div className="min-h-screen bg-white">
        <AppHeader crumbs={[{ label: "Exploração", href: `/farms/${farmId}` }, { label: "…" }]} />
        <div className="mx-auto max-w-3xl px-4 py-5 sm:px-6 space-y-4 animate-pulse">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {[...Array(4)].map((_, i) => (
              <div key={i} className="h-20 rounded-xl bg-irrigai-surface" />
            ))}
          </div>
          <div className="h-36 rounded-xl bg-irrigai-surface" />
          <div className="h-48 rounded-xl bg-irrigai-surface" />
        </div>
      </div>
    );
  }

  // ── Error ────────────────────────────────────────────────────────────────────
  if (error || !status) {
    return (
      <div className="flex min-h-screen flex-col">
        <AppHeader crumbs={[{ label: "Exploração", href: `/farms/${farmId}` }, { label: "Sector" }]} />
        <div className="flex flex-1 items-center justify-center px-4">
          <div className="max-w-sm space-y-4 text-center">
            <p className="text-[14px] text-irrigai-text-muted">
              {error ?? "Sector não encontrado."}
            </p>
            <div className="flex justify-center gap-2">
              <Button variant="secondary" size="sm" onClick={() => refetch()}>
                <RefreshCw className="h-3.5 w-3.5" />
                Recarregar
              </Button>
              <Button variant="ghost" size="sm" onClick={() => router.push(`/farms/${farmId}`)}>
                ← Dashboard
              </Button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // ── Derived ──────────────────────────────────────────────────────────────────
  const depletionPct = status.depletion_pct ?? 0;
  const stageName = STAGE_LABELS[status.current_stage ?? ""] ?? status.current_stage ?? "Fase não definida";
  const cropLabel = CROP_LABELS[status.crop_type ?? ""] ?? status.crop_type ?? "";

  // ── Render ───────────────────────────────────────────────────────────────────
  return (
    <div className="min-h-screen bg-white pb-20 sm:pb-8">
      <AppHeader
        crumbs={[
          { label: "Exploração", href: `/farms/${farmId}` },
          { label: cropLabel, href: `/farms/${farmId}?crop=${status.crop_type}` },
          { label: status.sector_name },
        ]}
        right={
          <Button variant="brand" size="sm" onClick={generate} loading={generating}>
            <Zap className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">Gerar recomendação</span>
          </Button>
        }
      />

      <main className="mx-auto max-w-3xl px-4 py-5 sm:px-6 animate-fade-in-up">
        {/* Page title */}
        <div className="mb-4">
          <h1 className="font-display text-[20px] font-[500] text-irrigai-text tracking-[-0.02em]">
            {status.sector_name}
          </h1>
          <p className="mt-0.5 text-[12px] text-irrigai-text-muted">
            {cropLabel} · {stageName}
          </p>
        </div>

        {/* Tab switcher */}
        <div className="flex gap-0 border-b border-black/[0.08] -mx-4 px-4 sm:-mx-6 sm:px-6 mb-4">
          {([
            { id: "monit", label: "Monitorização" },
            { id: "rega", label: "Sistema de rega" },
            { id: "fenologia", label: "Fenologia" },
          ] as const).map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`px-3 py-2.5 text-[13px] font-medium border-b-2 -mb-px transition-colors ${
                activeTab === tab.id
                  ? "border-irrigai-green text-irrigai-green"
                  : "border-transparent text-irrigai-text-muted hover:text-irrigai-text"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* ── Monitorização tab ──────────────────────────────────────────────── */}
        {activeTab === "monit" && <div className="space-y-4">

        {/* Status cards */}
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {/* Depletion */}
          <StatCard label="Depleção">
            <p className={`font-display text-[24px] font-[500] leading-none tabular-nums ${DEPLETION_COLOR(depletionPct)}`}>
              {status.depletion_pct != null ? `${status.depletion_pct.toFixed(0)}%` : "—"}
            </p>
            <p className="mt-1 text-[11px] text-irrigai-text-muted">da TAW</p>
            {status.depletion_pct != null && (
              <div className="mt-2 h-1 w-full overflow-hidden rounded-full bg-black/[0.06]">
                <div
                  className={`h-1 rounded-full ${DEPLETION_BAR(depletionPct)}`}
                  style={{ width: `${Math.min(depletionPct, 100)}%` }}
                />
              </div>
            )}
          </StatCard>

          {/* Last irrigation */}
          <StatCard label="Última rega">
            <p className="text-[13px] font-medium text-irrigai-text">
              {status.last_irrigated_at
                ? new Date(status.last_irrigated_at).toLocaleDateString("pt-PT", {
                    day: "numeric",
                    month: "short",
                  })
                : "—"}
            </p>
            {status.last_applied_mm && (
              <p className="mt-1 text-[11px] text-irrigai-text-muted">
                {status.last_applied_mm.toFixed(1)} mm
              </p>
            )}
          </StatCard>

          {/* Alerts */}
          <StatCard label="Alertas">
            {status.active_alerts_critical > 0 ? (
              <p className="text-[13px] font-medium text-irrigai-red">
                {status.active_alerts_critical} crítico
              </p>
            ) : status.active_alerts_warning > 0 ? (
              <p className="text-[13px] font-medium text-irrigai-amber">
                {status.active_alerts_warning} aviso
              </p>
            ) : (
              <p className="text-[13px] font-medium text-irrigai-green">Nenhum</p>
            )}
          </StatCard>

          {/* Probe freshness */}
          <StatCard label="Sonda">
            <p
              className={`text-[13px] font-medium ${
                status.data_freshness_hours == null
                  ? "text-irrigai-text-hint"
                  : status.data_freshness_hours < 2
                    ? "text-irrigai-green"
                    : status.data_freshness_hours < 6
                      ? "text-irrigai-amber"
                      : "text-irrigai-red"
              }`}
            >
              {status.data_freshness_hours != null
                ? status.data_freshness_hours < 1
                  ? "< 1h"
                  : `${status.data_freshness_hours.toFixed(0)}h`
                : "Sem dados"}
            </p>
            <p className="mt-1 text-[11px] text-irrigai-text-muted">
              {status.data_freshness_hours == null
                ? "aguardar ingestão"
                : status.data_freshness_hours < 2
                  ? "actualizado"
                  : "verificar sonda"}
            </p>
          </StatCard>
        </div>

        {/* Active overrides */}
        <ActiveOverrides sectorId={sectorId} />

        {/* Recommendation header — shown above probes */}
        {rec && (
          <div className="rounded-xl border border-black/[0.08] bg-white overflow-hidden">
            <RecHeader
              rec={rec}
              action={ACTION_CONFIG[rec.action]}
              confPct={Math.round(rec.confidence_score * 100)}
            />
          </div>
        )}

        {/* Probe charts */}
        {status.probes.length > 0 && (
          <p className="text-[11px] font-medium uppercase tracking-[0.05em] text-irrigai-text-hint -mb-2">
            Informação da Sonda
          </p>
        )}
        {status.probes.map((p) => (
          <ProbeReadingsInline
            key={p.probe_id}
            probeId={p.probe_id}
            externalId={p.external_id}
            healthStatus={p.health_status}
            lastReadingAt={p.last_reading_at}
            href={`/farms/${farmId}/sectors/${sectorId}/probes/${p.probe_id}`}
            sectorId={sectorId}
            onSaved={async () => {
              await Promise.all([
                refetch(),
                sectorsApi.cropProfile(sectorId).then(setCropProfile).catch(() => {}),
              ]);
              await generate();
            }}
          />
        ))}

        {/* 48-72h stress projection */}
        {liveStress && (
          <StressProjectionCard
            projection={liveStress}
            onAcceptRecommendation={rec ? async () => {
              if (rec) {
                await recommendationsApi.accept(rec.id);
                await refetch();
              }
            } : undefined}
          />
        )}

        {/* Recommendation body */}
        {recLoading ? (
          <div className="h-48 animate-pulse rounded-xl bg-irrigai-surface" />
        ) : rec ? (
          <RecommendationDetail rec={rec} onUpdate={refetch} hideHeader />
        ) : (
          <div className="rounded-xl border border-dashed border-black/[0.1] px-6 py-10 text-center">
            <p className="text-[13px] font-medium text-irrigai-text-muted mb-1">
              Sem recomendação gerada
            </p>
            <p className="text-[12px] text-irrigai-text-hint mb-5">
              O motor analisa sensores, meteorologia e fase da cultura.
            </p>
            <Button variant="brand" size="sm" onClick={generate} loading={generating}>
              <Zap className="h-3.5 w-3.5" />
              Gerar recomendação
            </Button>
          </div>
        )}

        {/* Auto-calibration soil validation */}
        <AutoCalibrationCard
          sectorId={sectorId}
          onAccepted={async () => {
            await refetch();
            await generate();
          }}
        />

        {/* AI Analysis */}
        <SectorAnalysis
          sectorId={sectorId}
          cropType={status.crop_type ?? "olive"}
          currentStage={status.current_stage ?? null}
          currentSoilPresetId={cropProfile?.soil_preset_id}
          currentRainfallEffectiveness={sectorDetail?.rainfall_effectiveness ?? null}
          onSaved={async () => {
            await Promise.all([
              refetch(),
              sectorsApi.cropProfile(sectorId).then(setCropProfile).catch(() => {}),
              sectorsApi.get(sectorId).then(setSectorDetail).catch(() => {}),
            ]);
            await generate();
          }}
        />

        </div>}

        {/* ── Sistema de rega tab ───────────────────────────────────────────── */}
        {activeTab === "rega" && (
          <div className="space-y-2">
            <p className="text-[12px] text-irrigai-text-muted leading-relaxed">
              Estas definições afectam directamente a dose bruta e a duração calculada nas recomendações.
              Depois de guardar, gere uma nova recomendação para ver o impacto.
            </p>
            <IrrigationSystemForm
              sectorId={sectorId}
              current={sectorDetail?.irrigation_system ?? null}
              onSaved={async () => {
                await sectorsApi.get(sectorId).then(setSectorDetail).catch(() => {});
              }}
            />
          </div>
        )}

        {/* ── Fenologia tab ─────────────────────────────────────────────────── */}
        {activeTab === "fenologia" && (
          <GDDStatusCard
            sectorId={sectorId}
            cropType={status.crop_type ?? "olive"}
            sowingDate={sectorDetail?.sowing_date ?? null}
            currentStage={status.current_stage ?? null}
            onStageConfirmed={async () => {
              await refetch();
              await generate();
            }}
            onSetupSaved={async () => {
              await Promise.all([
                refetch(),
                sectorsApi.get(sectorId).then(setSectorDetail).catch(() => {}),
              ]);
              await generate();
            }}
          />
        )}

      </main>

      <BottomNav farmId={farmId} />
      <ChatButton farmId={farmId} sectorId={sectorId} />
    </div>
  );
}

function StatCard({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-black/[0.08] bg-white px-4 py-3.5">
      <p className="mb-2 text-[11px] font-medium uppercase tracking-[0.05em] text-irrigai-text-hint">
        {label}
      </p>
      {children}
    </div>
  );
}
