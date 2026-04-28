"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useSectorStatus } from "@/hooks/useSectorDetail";
import { ProbeReadingsInline } from "@/components/probes/ProbeReadingsInline";
import { AppHeader } from "@/components/ui/AppHeader";
import { BottomNav } from "@/components/ui/BottomNav";
import { ChatButton } from "@/components/chat/ChatButton";
import { ActiveOverrides } from "@/components/overrides/ActiveOverrides";
import { OverrideModal } from "@/components/overrides/OverrideModal";
import { SectorAnalysis } from "@/components/sectors/SectorAnalysis";
import { AutoCalibrationCard } from "@/components/sectors/AutoCalibrationCard";
import { GDDStatusCard } from "@/components/sectors/GDDStatusCard";
import { IrrigationSystemForm } from "@/components/sectors/IrrigationSystemForm";
import { SoilProfileForm } from "@/components/sectors/SoilProfileForm";
import { VerdictPill } from "@/components/dashboard/editorial/VerdictPill";
import { KpiCell } from "@/components/dashboard/editorial/KpiCell";
import { ReasonList } from "@/components/dashboard/editorial/ReasonList";
import { StressForecastEditorial } from "@/components/dashboard/editorial/StressForecastEditorial";
import { DecisionPanelEditorial } from "@/components/dashboard/editorial/DecisionPanelEditorial";
import { SidebarCard } from "@/components/dashboard/editorial/SidebarCard";
import { ImproveReliabilityCard } from "@/components/dashboard/editorial/ImproveReliabilityCard";
import { recommendationsApi, sectorsApi } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { RefreshCw, Zap } from "lucide-react";
import Link from "next/link";
import type { RecommendationDetail as Rec, SectorCropProfile, StressProjection } from "@/types";
import type { Confidence } from "@/components/dashboard/editorial/ConfidenceDots";
import { CROP_LABELS, STAGE_LABELS } from "@/lib/cropConfig";

// Map ConfidenceLevel to Confidence (editorial)
function toConfidence(level: string | null, probeHealth?: string): Confidence {
  if (probeHealth === "no_probes" || probeHealth === "no_readings") return "sem-sonda";
  if (level === "high") return "alta";
  if (level === "medium") return "media";
  if (level === "low") return "baixa";
  return "sem-sonda";
}

type TabId = "monit" | "rega" | "solo" | "fenologia";

interface Props {
  params: { farmId: string; sectorId: string };
}

function buildAiLede(
  rec: Rec | null,
  projection: StressProjection | null,
): { before: string; emphasis: string | null; emphasisColor: "olive" | "terra"; after: string } {
  if (!rec) {
    return { before: "Sem recomendação gerada. Gere uma recomendação para ver a análise.", emphasis: null, emphasisColor: "olive", after: "" };
  }

  const snap = rec.inputs_snapshot;
  const depletionMm = snap?.depletion_mm as number | null ?? null;
  const tawMm = snap?.taw_mm as number | null ?? null;
  const depletionPct = depletionMm != null && tawMm ? Math.round(depletionMm / tawMm * 100) : null;
  const moisturePct = depletionPct != null ? 100 - depletionPct : null;
  const marginMm = depletionMm != null && tawMm != null ? Math.round(Math.max(0, tawMm * 0.55 - depletionMm)) : null;
  const stressLabel = projection?.urgency === "none" || !projection
    ? "Sem risco de stress nas próximas 72 h."
    : projection.urgency === "high"
    ? "Risco alto de stress nas próximas 72 h."
    : "Risco moderado nas próximas 72 h.";

  if (rec.action === "irrigate") {
    const depth = rec.irrigation_depth_mm;
    return {
      before: "A depleção atingiu ",
      emphasis: depletionPct != null ? `${depletionPct}% da água disponível` : "nível crítico",
      emphasisColor: "terra",
      after: depth ? `. Regar ${depth.toFixed(0)} mm para repor reservas.` : ". Regar para repor reservas.",
    };
  }

  if (moisturePct != null) {
    const after = marginMm != null && marginMm > 0
      ? `; faltam ${marginMm} mm para o ponto de rega. ${stressLabel}`
      : `. ${stressLabel}`;
    return {
      before: "O solo ainda guarda ",
      emphasis: `${moisturePct}% da água disponível`,
      emphasisColor: "olive",
      after,
    };
  }

  return { before: rec.reasons[0]?.message_pt ?? "Análise disponível abaixo.", emphasis: null, emphasisColor: "olive", after: "" };
}

function sectorDisplayId(name: string): string {
  return name.split(" - ")[0].trim().toUpperCase();
}

export default function SectorDetailPage({ params }: Props) {
  const { farmId, sectorId } = params;
  const router = useRouter();
  const { data: status, loading, error, refetch } = useSectorStatus(sectorId);
  const [rec, setRec] = useState<Rec | null>(null);
  const [recLoading, setRecLoading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [cropProfile, setCropProfile] = useState<SectorCropProfile | null>(null);
  const [sectorDetail, setSectorDetail] = useState<import("@/types").SectorDetail | null>(null);
  const [activeTab, setActiveTab] = useState<TabId>("monit");
  const [liveStress, setLiveStress] = useState<StressProjection | null>(null);
  const [showOverrideModal, setShowOverrideModal] = useState(false);
  const [showAnalysis, setShowAnalysis] = useState(false);
  const [probeOpenTrigger, setProbeOpenTrigger] = useState(0);
  const probeRef = useRef<HTMLDivElement>(null);

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
      <div className="min-h-screen bg-paper">
        <AppHeader crumbs={[{ label: "Exploração", href: `/farms/${farmId}` }, { label: "…" }]} />
        <div className="animate-pulse">
          <div className="h-36 border-b border-rule bg-paper-in" />
          <div className="h-12 border-b border-rule bg-paper" />
          <div className="px-4 pt-6 sm:px-8 lg:px-11 space-y-4">
            <div className="h-20 border border-rule-soft rounded-lg bg-card" />
            <div className="h-48 border border-rule-soft rounded-lg bg-card" />
          </div>
        </div>
      </div>
    );
  }

  // ── Error ────────────────────────────────────────────────────────────────────
  if (error || !status) {
    return (
      <div className="flex min-h-screen flex-col bg-paper">
        <AppHeader crumbs={[{ label: "Exploração", href: `/farms/${farmId}` }, { label: "Sector" }]} />
        <div className="flex flex-1 items-center justify-center gap-4 px-4">
          <p className="text-[14px] text-ink-2">{error ?? "Sector não encontrado."}</p>
          <div className="flex gap-2">
            <Button variant="secondary" size="sm" onClick={() => refetch()}>
              <RefreshCw className="h-3.5 w-3.5" /> Recarregar
            </Button>
            <Button variant="ghost" size="sm" onClick={() => router.push(`/farms/${farmId}`)}>← Dashboard</Button>
          </div>
        </div>
      </div>
    );
  }

  // ── Derived ──────────────────────────────────────────────────────────────────
  const stageName = STAGE_LABELS[status.current_stage ?? ""] ?? status.current_stage ?? "Fase não definida";
  const cropLabel = CROP_LABELS[status.crop_type ?? ""] ?? status.crop_type ?? "";
  const sectorDisplayName = sectorDisplayId(status.sector_name);

  const snap = rec?.inputs_snapshot;
  const depletionMm = snap?.depletion_mm as number | null ?? null;
  const tawMm = snap?.taw_mm as number | null ?? null;
  const et0 = snap?.et0_mm as number | null ?? null;
  const kc = snap?.kc as number | null ?? null;
  const etc = et0 != null && kc != null ? et0 * kc : null;
  const depletionPctFromSnap = depletionMm != null && tawMm ? depletionMm / tawMm * 100 : null;
  const depletionPct = status.depletion_pct ?? depletionPctFromSnap;
  const moistureValue = depletionPct != null ? Math.max(0, Math.min(1, 1 - depletionPct / 100)) : null;
  const marginMm = depletionMm != null && tawMm != null ? Math.max(0, tawMm * 0.55 - depletionMm) : null;

  const confidence = toConfidence(
    status.latest_confidence_level,
    status.probes.length === 0 ? "no_probes" : undefined,
  );
  const confidencePct = status.latest_confidence_score != null ? Math.round(status.latest_confidence_score * 100) : 0;
  const showImproveCard = confidence === "baixa" || confidence === "media";

  const projection = liveStress ?? rec?.stress_projection ?? null;
  const aiLede = buildAiLede(rec, projection);

  const firstProbe = status.probes[0] ?? null;
  const probeHealthColor =
    firstProbe == null ? "bg-ink-3"
    : firstProbe.health_status === "ok" ? "bg-olive"
    : firstProbe.health_status === "warning" ? "bg-[#c9a34a]"
    : "bg-terra";

  const tabs: { id: TabId; label: string }[] = [
    { id: "monit", label: "Monitorização" },
    { id: "rega", label: "Sistema de rega" },
    { id: "solo", label: "Solo" },
    { id: "fenologia", label: "Fenologia" },
  ];

  return (
    <div className="min-h-screen bg-paper pb-20 sm:pb-8">
      <AppHeader
        crumbs={[
          { label: "Exploração", href: `/farms/${farmId}` },
          { label: cropLabel, href: `/farms/${farmId}?crop=${status.crop_type}` },
          { label: status.sector_name },
        ]}
        right={
          <button
            onClick={generate}
            disabled={generating}
            aria-busy={generating}
            className="inline-flex items-center gap-2 rounded-full border border-rule bg-ink px-4 py-2 text-[13px] font-medium text-paper hover:opacity-85 disabled:opacity-50 transition-opacity"
          >
            <Zap className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">{generating ? "A gerar…" : "Gerar recomendação"}</span>
          </button>
        }
      />

      {/* Hero block */}
      <section className="border-b border-rule px-4 pt-[26px] pb-[18px] sm:px-8 lg:px-11">
        <div className="flex items-start justify-between gap-8">
          {/* Left: ID + verdict + timestamp */}
          <div className="flex-1 min-w-0">
            <p className="font-mono text-[10px] tracking-[0.16em] uppercase text-ink-3 mb-2">
              {status.sector_name} · {cropLabel} · {stageName}
            </p>
            <div className="flex items-baseline gap-3.5 flex-wrap">
              <h1 className="font-serif text-[40px] sm:text-[46px] font-medium tracking-[-0.025em] leading-none text-ink">
                {sectorDisplayName}
              </h1>
              {status.latest_action && (
                <VerdictPill
                  verdict={status.latest_action === "irrigate" ? "regar" : "nao"}
                  size="lg"
                />
              )}
              {status.recommendation_generated_at && (
                <span className="font-mono text-[11px] text-ink-3 tracking-[0.04em]">
                  gerada{" "}
                  {new Date(status.recommendation_generated_at).toLocaleString("pt-PT", {
                    day: "2-digit",
                    month: "2-digit",
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                </span>
              )}
            </div>
          </div>

          {/* Right: AI lede */}
          <aside className="hidden lg:block max-w-[480px] border-l border-rule-soft pl-8">
            <p className="font-mono text-[10px] tracking-[0.16em] uppercase text-terra mb-1.5">
              Recomendação da IA
            </p>
            <p
              className="font-serif text-[20px] font-normal leading-[1.35] tracking-[-0.01em] text-ink"
              style={{ textWrap: "balance" } as React.CSSProperties}
            >
              {aiLede.before}
              {aiLede.emphasis && (
                <em
                  className={`font-instrument not-italic ${
                    aiLede.emphasisColor === "terra" ? "text-terra" : "text-olive"
                  }`}
                >
                  {aiLede.emphasis}
                </em>
              )}
              <span className="text-ink-2">{aiLede.after}</span>
            </p>
          </aside>
        </div>
      </section>

      {/* Tabs */}
      <div className="px-4 border-b border-rule sm:px-8 lg:px-11 flex gap-7">
        {tabs.map((t) => (
          <button
            key={t.id}
            role="tab"
            aria-selected={activeTab === t.id}
            onClick={() => setActiveTab(t.id)}
            className={`pt-3.5 pb-3 -mb-px border-b-2 font-serif tracking-[-0.01em] transition-colors ${
              activeTab === t.id
                ? "border-terra text-ink text-[17px] font-semibold"
                : "border-transparent text-ink-3 text-[16px] font-normal hover:text-ink-2"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* ── Monitorização tab ──────────────────────────────────────────────────── */}
      {activeTab === "monit" && (
        <div className="px-4 pt-6 pb-8 sm:px-8 lg:px-11">
          <div className="grid grid-cols-1 lg:grid-cols-[1fr_360px] gap-7 items-start">
            {/* Main column */}
            <div>
              {/* Active overrides */}
              <div className="mb-5">
                <ActiveOverrides sectorId={sectorId} />
              </div>

              {/* KPI strip */}
              <div className="grid grid-cols-2 sm:grid-cols-4 border-t border-b border-rule-soft mb-[22px]">
                <KpiCell
                  first
                  label="Depleção"
                  value={depletionPct != null ? `${depletionPct.toFixed(0)}%` : "—"}
                  sub="da TAW"
                  tint={depletionPct != null && depletionPct > 60 ? "terra" : depletionPct != null && depletionPct > 40 ? "amber" : "olive"}
                  bar={moistureValue ?? undefined}
                />
                <KpiCell
                  label="Água em falta"
                  value={depletionMm != null ? depletionMm.toFixed(1) : "—"}
                  unit={depletionMm != null ? "mm" : undefined}
                  sub="até reabastecer"
                />
                <KpiCell
                  label="ET₀ hoje"
                  value={et0 != null ? et0.toFixed(2) : "—"}
                  unit={et0 != null ? "mm/dia" : undefined}
                  sub={etc != null ? `consumo ≈ ${etc.toFixed(1)}` : undefined}
                />
                <KpiCell
                  label="Margem rega"
                  value={marginMm != null ? marginMm.toFixed(1) : "—"}
                  unit={marginMm != null ? "mm" : undefined}
                  sub="para o ponto de rega"
                />
              </div>

              {/* Reasons */}
              {recLoading ? (
                <div className="h-48 animate-pulse rounded-lg bg-card border border-rule-soft mb-[22px]" />
              ) : rec && rec.reasons.length > 0 ? (
                <ReasonList
                  reasons={rec.reasons}
                  confidence={toConfidence(rec.confidence_level)}
                  confidencePct={Math.round(rec.confidence_score * 100)}
                />
              ) : !rec && !recLoading ? (
                <div className="border border-dashed border-rule rounded-lg px-6 py-10 text-center mb-[22px]">
                  <p className="font-serif text-[18px] text-ink-2 mb-1">Sem recomendação gerada</p>
                  <p className="text-[13px] text-ink-3 mb-5">
                    O motor analisa sensores, meteorologia e fase da cultura.
                  </p>
                  <button
                    onClick={generate}
                    disabled={generating}
                    className="inline-flex items-center gap-2 rounded-full bg-ink text-paper px-5 py-2.5 text-[13px] font-medium hover:opacity-85 disabled:opacity-50 transition-opacity"
                  >
                    <Zap className="h-3.5 w-3.5" />
                    {generating ? "A gerar…" : "Gerar recomendação"}
                  </button>
                </div>
              ) : null}

              {/* Stress forecast */}
              {projection && <StressForecastEditorial projection={projection} />}

              {/* Probe charts */}
              {status.probes.length > 0 && (
                <div className="mt-2" ref={probeRef}>
                  {status.probes.map((p) => (
                    <ProbeReadingsInline
                      key={p.probe_id}
                      probeId={p.probe_id}
                      externalId={p.external_id}
                      healthStatus={p.health_status}
                      lastReadingAt={p.last_reading_at}
                      href={`/farms/${farmId}/sectors/${sectorId}/probes/${p.probe_id}`}
                      sectorId={sectorId}
                      openTrigger={probeOpenTrigger}
                      onSaved={async () => {
                        await Promise.all([
                          refetch(),
                          sectorsApi.cropProfile(sectorId).then(setCropProfile).catch(() => {}),
                        ]);
                        await generate();
                      }}
                    />
                  ))}
                </div>
              )}

              {/* Decision panel */}
              {rec && (
                <DecisionPanelEditorial
                  rec={rec}
                  onUpdate={refetch}
                  onOverride={() => setShowOverrideModal(true)}
                />
              )}

              {/* Auto-calibration */}
              <AutoCalibrationCard
                sectorId={sectorId}
                onAccepted={async () => {
                  await refetch();
                  await generate();
                }}
              />

              {/* AI analysis — revealed by "Falar com a IA" sidebar card */}
              {showAnalysis && (
                <SectorAnalysis
                  sectorId={sectorId}
                  et0Mm={(rec?.inputs_snapshot?.et0_mm as number | null) ?? null}
                  probeExternalId={status.probes[0]?.external_id ?? null}
                />
              )}
            </div>

            {/* Sidebar */}
            <aside className="flex flex-col gap-4 lg:sticky lg:top-[72px]">
              {/* Estado hoje */}
              <SidebarCard title="Estado · hoje">
                <div className="divide-y divide-rule-soft">
                  {[
                    {
                      label: "Última rega",
                      value: status.last_irrigated_at
                        ? new Date(status.last_irrigated_at).toLocaleDateString("pt-PT", { day: "numeric", month: "short" })
                        : "—",
                      color: status.last_irrigated_at ? "text-ink" : "text-ink-3",
                    },
                    {
                      label: "Alertas",
                      value: status.active_alerts_critical > 0
                        ? `${status.active_alerts_critical} crítico`
                        : status.active_alerts_warning > 0
                        ? `${status.active_alerts_warning} aviso`
                        : "Nenhum",
                      color: status.active_alerts_critical > 0
                        ? "text-terra"
                        : status.active_alerts_warning > 0
                        ? "text-[#c9a34a]"
                        : "text-olive",
                    },
                    {
                      label: "ET₀",
                      value: et0 != null ? `${et0.toFixed(2)} mm/dia` : "—",
                      color: "text-ink",
                    },
                    {
                      label: "Água total",
                      value: tawMm != null ? `${tawMm.toFixed(0)} mm` : "—",
                      color: "text-ink",
                    },
                    {
                      label: "Em falta",
                      value: depletionMm != null ? `${depletionMm.toFixed(0)} mm` : "—",
                      color: depletionMm != null && tawMm != null && depletionMm / tawMm > 0.6
                        ? "text-terra"
                        : depletionMm != null && tawMm != null && depletionMm / tawMm > 0.35
                        ? "text-[#c9a34a]"
                        : "text-ink",
                    },
                  ].map(({ label, value, color }) => (
                    <div key={label} className="flex items-baseline justify-between py-2.5">
                      <span className="text-[12px] text-ink-3">{label}</span>
                      <span className={`font-serif text-[14.5px] font-medium ${color}`}>{value}</span>
                    </div>
                  ))}
                </div>
              </SidebarCard>

              {/* Sonda */}
              {firstProbe && (
                <SidebarCard
                  title="Sonda"
                  action={
                    <Link
                      href={`/farms/${farmId}/sectors/${sectorId}/probes/${firstProbe.probe_id}`}
                      className="font-serif italic text-[11px] text-ink-2 hover:text-ink transition-colors"
                    >
                      Histórico ↗
                    </Link>
                  }
                >
                  <button
                    type="button"
                    className="w-full text-left hover:opacity-80 transition-opacity"
                    onClick={() => {
                      setProbeOpenTrigger((n) => n + 1);
                      setTimeout(() => probeRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 60);
                    }}
                  >
                    <div className="flex items-center gap-2.5 mb-2">
                      <span
                        className={`h-[7px] w-[7px] rounded-full ${probeHealthColor}`}
                        style={{ boxShadow: `0 0 0 3px #f3f1e8` }}
                      />
                      <span className="font-mono text-[13px] text-ink font-medium">
                        {firstProbe.external_id}
                      </span>
                    </div>
                    <p className="font-serif italic text-[12px] text-ink-3">
                      {firstProbe.health_status === "ok"
                        ? "Online — dados actualizados."
                        : firstProbe.health_status === "warning"
                        ? "Online — a aguardar ingestão. Os cálculos usam estimativa."
                        : "Sem dados — verificar ligação."}
                      {status.data_freshness_hours != null && ` Última leitura há ${
                        status.data_freshness_hours < 1 ? "< 1h" : `${status.data_freshness_hours.toFixed(0)}h`
                      }.`}
                    </p>
                  </button>
                </SidebarCard>
              )}

              {/* Improve reliability */}
              {showImproveCard && (
                <ImproveReliabilityCard
                  onDefineSoil={() => setActiveTab("solo")}
                  onConfirmStage={() => setActiveTab("fenologia")}
                />
              )}

              {/* Falar com a IA */}
              <button
                onClick={() => setShowAnalysis((v) => !v)}
                className={`w-full text-left rounded-lg p-[14px_18px] flex gap-3 items-start transition-colors ${
                  showAnalysis
                    ? "bg-ink text-paper border border-ink"
                    : "bg-paper border border-dashed border-rule hover:bg-paper-in"
                }`}
              >
                <div className={`h-8 w-8 rounded-full flex items-center justify-center font-serif italic text-[14px] shrink-0 ${showAnalysis ? "bg-paper text-ink" : "bg-ink text-paper"}`}>
                  i
                </div>
                <div>
                  <p className={`font-serif text-[14px] font-semibold mb-0.5 ${showAnalysis ? "text-paper" : "text-ink"}`}>
                    {showAnalysis ? "Fechar análise IA" : "Falar com a IA"}
                  </p>
                  <p className={`text-[11.5px] leading-[1.4] ${showAnalysis ? "text-paper/70" : "text-ink-2"}`}>
                    {showAnalysis
                      ? "Clique para fechar o painel de análise."
                      : "Pergunte porque é que o modelo decidiu assim, ou peça uma análise com observações de campo."}
                  </p>
                </div>
              </button>
            </aside>
          </div>
        </div>
      )}

      {/* ── Sistema de rega tab ───────────────────────────────────────────────── */}
      {activeTab === "rega" && (
        <div className="px-4 pt-6 pb-8 sm:px-8 lg:px-11 max-w-3xl space-y-5">
          <p className="text-[13px] text-ink-2 leading-relaxed">
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

      {/* ── Solo tab ─────────────────────────────────────────────────────────── */}
      {activeTab === "solo" && (
        <div className="px-4 pt-6 pb-8 sm:px-8 lg:px-11 max-w-2xl space-y-5">
          <p className="text-[13px] text-ink-2 leading-relaxed">
            O tipo de solo define a água total disponível (TAW) e o ponto de murchamento.
            A correcção da chuva ajusta a eficácia da precipitação com base nas características do terreno.
            Depois de guardar, uma nova recomendação é gerada automaticamente.
          </p>
          <SoilProfileForm
            sectorId={sectorId}
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
        </div>
      )}

      {/* ── Fenologia tab ─────────────────────────────────────────────────────── */}
      {activeTab === "fenologia" && (
        <div className="px-4 pt-6 pb-8 sm:px-8 lg:px-11 max-w-3xl">
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
        </div>
      )}

      {/* Override modal */}
      {rec && showOverrideModal && (
        <OverrideModal
          rec={rec}
          onClose={() => setShowOverrideModal(false)}
          onSuccess={async () => {
            setShowOverrideModal(false);
            await refetch();
          }}
        />
      )}

      <BottomNav farmId={farmId} />
      <ChatButton farmId={farmId} sectorId={sectorId} />
    </div>
  );
}
