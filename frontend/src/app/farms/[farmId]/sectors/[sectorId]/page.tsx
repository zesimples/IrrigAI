"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useSectorStatus } from "@/hooks/useSectorDetail";
import { RecommendationDetail } from "@/components/sectors/RecommendationDetail";
import { Button } from "@/components/ui/button";
import { AppHeader } from "@/components/ui/AppHeader";
import { BottomNav } from "@/components/ui/BottomNav";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";
import { recommendationsApi, sectorsApi } from "@/lib/api";
import { ChatButton } from "@/components/chat/ChatButton";
import { ActiveOverrides } from "@/components/overrides/ActiveOverrides";
import { SectorAnalysis } from "@/components/sectors/SectorAnalysis";
import { RefreshCw, Zap, ChevronRight } from "lucide-react";
import type { RecommendationDetail as Rec, SectorCropProfile } from "@/types";
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

  useEffect(() => {
    sectorsApi.cropProfile(sectorId).then(setCropProfile).catch(() => {});
    sectorsApi.get(sectorId).then(setSectorDetail).catch(() => {});
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
          { label: status.sector_name },
        ]}
        right={
          <Button variant="brand" size="sm" onClick={generate} loading={generating}>
            <Zap className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">Gerar recomendação</span>
          </Button>
        }
      />

      <main className="mx-auto max-w-3xl space-y-4 px-4 py-5 sm:px-6 animate-fade-in-up">
        {/* Page title */}
        <div>
          <h1 className="font-display text-[20px] font-[500] text-irrigai-text tracking-[-0.02em]">
            {status.sector_name}
          </h1>
          <p className="mt-0.5 text-[12px] text-irrigai-text-muted">
            {cropLabel} · {stageName}
          </p>
        </div>

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

        {/* Recommendation */}
        {recLoading ? (
          <div className="h-48 animate-pulse rounded-xl bg-irrigai-surface" />
        ) : rec ? (
          <RecommendationDetail rec={rec} onUpdate={refetch} />
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

        {/* AI Analysis */}
        <SectorAnalysis
          sectorId={sectorId}
          cropType={status.crop_type ?? "olive"}
          currentStage={status.current_stage ?? null}
          currentSoilPresetId={cropProfile?.soil_preset_id}
          currentRainfallEffectiveness={sectorDetail?.rainfall_effectiveness ?? null}
          onSaved={async () => {
            // Re-fetch sector data so saved values reflect in the UI immediately
            await Promise.all([
              refetch(),
              sectorsApi.cropProfile(sectorId).then(setCropProfile).catch(() => {}),
              sectorsApi.get(sectorId).then(setSectorDetail).catch(() => {}),
            ]);
            // Auto-generate recommendation with the updated parameters
            await generate();
          }}
        />

        {/* Probes */}
        {status.probes.length > 0 ? (
          <Card>
            <CardHeader>
              <CardTitle>Sondas ({status.probes.length})</CardTitle>
            </CardHeader>
            <CardBody className="p-0">
              {status.probes.map((p) => (
                <Link
                  key={p.probe_id}
                  href={`/farms/${farmId}/sectors/${sectorId}/probes/${p.probe_id}`}
                  className="group flex items-center justify-between gap-3 px-4 py-3.5 border-b border-black/[0.05] last:border-0 hover:bg-irrigai-surface transition-colors"
                >
                  <div>
                    <p className="font-mono text-[13px] font-medium text-irrigai-text">
                      {p.external_id}
                    </p>
                    <p className="mt-0.5 text-[11px] text-irrigai-text-muted">
                      {p.last_reading_at
                        ? `Última leitura: ${new Date(p.last_reading_at).toLocaleString("pt-PT", {
                            day: "numeric",
                            month: "short",
                            hour: "2-digit",
                            minute: "2-digit",
                          })}`
                        : "Sem leituras ainda"}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <span
                      className={`inline-block h-1.5 w-1.5 rounded-full ${
                        p.health_status === "ok"
                          ? "bg-irrigai-green"
                          : p.health_status === "degraded"
                            ? "bg-irrigai-amber"
                            : "bg-irrigai-red"
                      }`}
                    />
                    <span className="text-[11px] text-irrigai-text-muted">
                      {p.health_status === "ok" ? "OK" : p.health_status}
                    </span>
                    <ChevronRight className="h-4 w-4 text-irrigai-text-hint group-hover:text-irrigai-text transition-colors" />
                  </div>
                </Link>
              ))}
            </CardBody>
          </Card>
        ) : (
          <Card>
            <CardBody className="py-8 text-center">
              <p className="text-[13px] text-irrigai-text-muted">
                Este sector ainda não tem sondas associadas.
              </p>
            </CardBody>
          </Card>
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
