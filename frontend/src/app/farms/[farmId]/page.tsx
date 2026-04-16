"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useFarmDashboard } from "@/hooks/useFarmDashboard";
import { SectorCard } from "@/components/dashboard/SectorCard";
import { WeatherWidget } from "@/components/dashboard/WeatherWidget";
import { AlertsBanner } from "@/components/dashboard/AlertsBanner";
import { Button } from "@/components/ui/button";
import { AppHeader } from "@/components/ui/AppHeader";
import { BottomNav } from "@/components/ui/BottomNav";
import { ChatButton } from "@/components/chat/ChatButton";
import { farmsApi } from "@/lib/api";
import { useState, useMemo } from "react";
import type { SectorSummary } from "@/types";
import { RefreshCw, Zap } from "lucide-react";
import { CROP_LABELS } from "@/lib/cropConfig";

interface Props {
  params: { farmId: string };
}

// Variety label within a crop tab, e.g. "Cobrançosa" from "T01 - Cobrançosa"
function varietyKey(s: SectorSummary): string {
  const parts = s.sector_name.split(" - ");
  return parts.length > 1 ? parts.slice(1).join(" - ") : "";
}

export default function FarmDashboardPage({ params }: Props) {
  const { farmId } = params;
  const { data, loading, error, refetch } = useFarmDashboard(farmId);
  const router = useRouter();
  const searchParams = useSearchParams();
  const [generating, setGenerating] = useState(false);
  const [activeTab, setActiveTab] = useState<string | null>(
    searchParams.get("crop")
  );

  const cropTabs = useMemo(() => {
    if (!data) return [];
    const seen = new Set<string>();
    const order: string[] = [];
    for (const s of data.sectors_summary) {
      const ct = s.crop_type ?? "other";
      if (!seen.has(ct)) { seen.add(ct); order.push(ct); }
    }
    return order;
  }, [data]);

  const currentTab = activeTab && cropTabs.includes(activeTab) ? activeTab : cropTabs[0] ?? null;

  const tabSectors = useMemo(
    () => data?.sectors_summary.filter((s) => (s.crop_type ?? "other") === currentTab) ?? [],
    [data, currentTab],
  );

  const varietyGroups = useMemo(
    () =>
      tabSectors.reduce<Record<string, SectorSummary[]>>((acc, s) => {
        const key = varietyKey(s) || (CROP_LABELS[s.crop_type ?? ""] ?? "Geral");
        if (!acc[key]) acc[key] = [];
        acc[key].push(s);
        return acc;
      }, {}),
    [tabSectors],
  );

  async function generateAll() {
    setGenerating(true);
    try {
      await farmsApi.generateRecommendations(farmId);
      await refetch();
    } finally {
      setGenerating(false);
    }
  }

  // ── Loading ──────────────────────────────────────────────────────────────────
  if (loading) {
    return (
      <div className="min-h-screen bg-white">
        <div className="mx-auto max-w-3xl px-4 pt-6 sm:px-6 animate-pulse space-y-5">
          <div className="h-8 w-56 rounded bg-irrigai-surface" />
          <div className="h-3 w-32 rounded bg-irrigai-surface" />
          <div className="h-12 w-full rounded-xl bg-irrigai-surface" />
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            {[...Array(6)].map((_, i) => (
              <div key={i} className="h-32 rounded-xl bg-irrigai-surface" />
            ))}
          </div>
        </div>
      </div>
    );
  }

  // ── Error ────────────────────────────────────────────────────────────────────
  if (error || !data) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-4 px-4">
        <p className="text-[14px] text-irrigai-text-muted">
          {error ?? "Não foi possível carregar a exploração."}
        </p>
        <div className="flex gap-2">
          <Button variant="secondary" size="sm" onClick={() => refetch()}>
            <RefreshCw className="h-3.5 w-3.5" />
            Recarregar
          </Button>
          <Button variant="ghost" size="sm" onClick={() => router.push("/")}>
            ← Início
          </Button>
        </div>
      </div>
    );
  }

  // ── Derived ──────────────────────────────────────────────────────────────────
  const formattedDate = new Date(data.date).toLocaleDateString("pt-PT", {
    weekday: "long",
    day: "numeric",
    month: "long",
  });
  const dateLabel = formattedDate.charAt(0).toUpperCase() + formattedDate.slice(1);

  // ── Render ───────────────────────────────────────────────────────────────────
  return (
    <div className="min-h-screen bg-white pb-20 sm:pb-8">
      <AppHeader
        crumbs={[{ label: data.farm.name }]}
        farmDate={`${dateLabel}${data.farm.region ? ` · ${data.farm.region}` : ""}`}
        right={
          <Button variant="brand" size="sm" onClick={generateAll} loading={generating}>
            <Zap className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">Gerar</span>
          </Button>
        }
      />

      <main className="mx-auto max-w-3xl space-y-5 px-4 py-5 sm:px-6 animate-fade-in-up">
        {/* Alerts */}
        <AlertsBanner counts={data.active_alerts_count} farmId={farmId} />

        {/* Weather strip */}
        <WeatherWidget weather={data.weather_today} />

        {/* Missing data prompts */}
        {data.missing_data_prompts.length > 0 && (
          <div className="rounded-xl bg-irrigai-surface p-4">
            <p className="mb-2 text-[12px] font-medium text-irrigai-text-muted">
              Para melhorar as recomendações
            </p>
            <div className="space-y-1.5">
              {data.missing_data_prompts.map((msg, i) => (
                <div key={i} className="flex items-start gap-2 text-[12px] text-irrigai-text py-1">
                  <svg width="13" height="13" viewBox="0 0 13 13" fill="none" className="mt-0.5 shrink-0">
                    <circle cx="6.5" cy="6.5" r="5.5" stroke="#EF9F27" strokeWidth="1" />
                    <line x1="6.5" y1="3.5" x2="6.5" y2="7.5" stroke="#EF9F27" strokeWidth="1" />
                    <circle cx="6.5" cy="9.5" r="0.5" fill="#EF9F27" />
                  </svg>
                  <span>{msg}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Sectors */}
        {data.sectors_summary.length > 0 ? (
          <div className="space-y-4">
            {/* Tab bar — only render if more than one crop type */}
            {cropTabs.length > 1 && (
              <div className="flex gap-1 rounded-xl bg-irrigai-surface p-1">
                {cropTabs.map((ct) => {
                  const label = CROP_LABELS[ct] ?? ct;
                  const count = data.sectors_summary.filter((s) => (s.crop_type ?? "other") === ct).length;
                  const isActive = ct === currentTab;
                  return (
                    <button
                      key={ct}
                      onClick={() => setActiveTab(ct)}
                      className={`flex flex-1 items-center justify-center gap-1.5 rounded-lg px-3 py-2 text-[13px] font-medium transition-all ${
                        isActive
                          ? "bg-white text-irrigai-text shadow-sm"
                          : "text-irrigai-text-muted hover:text-irrigai-text"
                      }`}
                    >
                      {label}
                      <span
                        className={`rounded-full px-1.5 py-0.5 text-[10px] tabular-nums ${
                          isActive
                            ? "bg-irrigai-surface text-irrigai-text-muted"
                            : "bg-black/[0.06] text-irrigai-text-hint"
                        }`}
                      >
                        {count}
                      </span>
                    </button>
                  );
                })}
              </div>
            )}

            {/* Variety groups within the active tab */}
            <div className="space-y-6">
              {Object.entries(varietyGroups).map(([variety, sectors]) => (
                <section key={variety}>
                  <div className="mb-3 flex items-center justify-between">
                    <p className="text-[11px] font-medium uppercase tracking-[0.06em] text-irrigai-text-hint">
                      {variety}
                    </p>
                    <p className="text-[11px] text-irrigai-text-hint">
                      {sectors.length} sector{sectors.length !== 1 ? "es" : ""}
                    </p>
                  </div>
                  <div className="grid gap-3 grid-cols-1 sm:grid-cols-2">
                    {sectors.map((s) => (
                      <SectorCard key={s.sector_id} sector={s} farmId={farmId} />
                    ))}
                  </div>
                </section>
              ))}
            </div>
          </div>
        ) : (
          <div className="rounded-xl border border-dashed border-black/[0.1] px-6 py-12 text-center">
            <p className="text-[14px] font-medium text-irrigai-text-muted">
              Sem sectores disponíveis.
            </p>
          </div>
        )}
      </main>

      <BottomNav farmId={farmId} />
      <ChatButton farmId={farmId} />
    </div>
  );
}
