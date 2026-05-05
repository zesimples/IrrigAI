"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { useFarmDashboard } from "@/hooks/useFarmDashboard";
import { AppHeader } from "@/components/ui/AppHeader";
import { BottomNav } from "@/components/ui/BottomNav";
import { ChatButton } from "@/components/chat/ChatButton";
import { Button } from "@/components/ui/button";
import { farmsApi } from "@/lib/api";
import { RefreshCw } from "lucide-react";
import { Lede } from "@/components/dashboard/editorial/Lede";
import { NumericStrip } from "@/components/dashboard/editorial/NumericStrip";
import { SectorGrid } from "@/components/dashboard/editorial/SectorGrid";
import type { ProviderSyncStatus } from "@/types";

interface Props {
  params: { farmId: string };
}

function relativeTime(isoStr: string): string {
  const diff = Math.floor((Date.now() - new Date(isoStr).getTime()) / 1000);
  if (diff < 60) return "agora mesmo";
  if (diff < 3600) return `há ${Math.floor(diff / 60)} min`;
  if (diff < 86400) return `há ${Math.floor(diff / 3600)} h`;
  return `há ${Math.floor(diff / 86400)} d`;
}

function SyncStatusBar({ entries }: { entries: ProviderSyncStatus[] }) {
  if (entries.length === 0) return null;

  return (
    <div className="px-4 sm:px-8 lg:px-11 py-2 border-b border-rule-soft flex flex-wrap gap-x-5 gap-y-1">
      {entries.map((e) => {
        const hasError = e.consecutive_failures > 0;
        const label = e.provider.replace(":probes", " · sonda").replace(":weather", " · clima");
        return (
          <span key={e.provider} className="flex items-center gap-1.5">
            <span className={`h-1.5 w-1.5 rounded-full shrink-0 ${hasError ? "bg-terra" : "bg-olive"}`} />
            <span className="font-mono text-[10px] tracking-[0.06em] text-ink-3">
              {label}
              {hasError
                ? ` — erro ${e.last_error_at ? relativeTime(e.last_error_at) : ""}`
                : e.last_success_at
                  ? ` · ${relativeTime(e.last_success_at)}`
                  : " · nunca sincronizado"}
            </span>
          </span>
        );
      })}
    </div>
  );
}

function editionSubline(dateStr: string): string {
  const d = new Date(dateStr);
  const days = ["Dom", "Seg", "Ter", "Qua", "Qui", "Sex", "Sáb"];
  const months = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"];
  const dayName = days[d.getDay()];
  const month = months[d.getMonth()];
  const year = d.getFullYear();
  const roman = ["I", "II", "III", "IV", "V", "VI"][Math.max(0, year - 2024)] ?? String(year - 2023);
  const startOfYear = new Date(year, 0, 0);
  const issue = Math.floor((d.getTime() - startOfYear.getTime()) / 86_400_000);
  return `Edição de ${dayName} · ${d.getDate()} ${month} · Ano ${roman}, N.º ${issue}`;
}

export default function FarmDashboardPage({ params }: Props) {
  const { farmId } = params;
  const { data, loading, error, refetch } = useFarmDashboard(farmId);
  const router = useRouter();
  const [generating, setGenerating] = useState(false);
  const [generateError, setGenerateError] = useState<string | null>(null);

  async function generateAll() {
    setGenerating(true);
    setGenerateError(null);
    try {
      await farmsApi.generateRecommendations(farmId);
      await refetch();
    } catch (e) {
      setGenerateError(e instanceof Error ? e.message : "Erro ao gerar recomendações.");
    } finally {
      setGenerating(false);
    }
  }

  // ── Loading ──────────────────────────────────────────────────────────────────
  if (loading) {
    return (
      <div className="min-h-screen bg-paper">
        <AppHeader crumbs={[{ label: "…" }]} />
        <div className="animate-pulse space-y-0">
          <div className="h-48 border-b border-rule bg-paper-in" />
          <div className="flex border-b border-rule-soft">
            {[...Array(5)].map((_, i) => (
              <div key={i} className="flex-1 h-16 border-l border-rule-soft bg-paper-in first:border-l-0" />
            ))}
          </div>
          <div className="grid grid-cols-3 border-t border-l border-rule mt-5 mx-4 sm:mx-8 lg:mx-11">
            {[...Array(6)].map((_, i) => (
              <div key={i} className="h-44 border-r border-b border-rule bg-card" />
            ))}
          </div>
        </div>
      </div>
    );
  }

  // ── Error ────────────────────────────────────────────────────────────────────
  if (error || !data) {
    return (
      <div className="flex min-h-screen flex-col bg-paper">
        <AppHeader crumbs={[{ label: "Exploração" }]} />
        <div className="flex flex-1 items-center justify-center gap-4 px-4">
          <p className="text-[14px] text-ink-2">{error ?? "Não foi possível carregar a exploração."}</p>
          <div className="flex gap-2">
            <Button variant="secondary" size="sm" onClick={() => refetch()}>
              <RefreshCw className="h-3.5 w-3.5" /> Recarregar
            </Button>
            <Button variant="ghost" size="sm" onClick={() => router.push("/")}>← Início</Button>
          </div>
        </div>
      </div>
    );
  }

  const toIrrigate = data.sectors_summary.filter((s) => s.action === "irrigate").length;
  const noAction = data.sectors_summary.filter((s) => s.action !== "irrigate").length;

  return (
    <div className="min-h-screen bg-paper pb-20 sm:pb-8">
      <AppHeader
        crumbs={[{ label: data.farm.name }]}
        farmDate={editionSubline(data.date)}
        right={
          <button
            onClick={generateAll}
            disabled={generating}
            aria-busy={generating}
            className="inline-flex items-center gap-2 rounded-full border border-rule bg-ink px-4 py-2 text-[13px] font-medium text-paper hover:opacity-85 disabled:opacity-50 transition-opacity"
          >
            <span className="h-1.5 w-1.5 rounded-full bg-terra" />
            {generating ? "A gerar…" : "Gerar plano de rega"}
          </button>
        }
      />

      {generateError && (
        <div className="mx-4 mt-3 sm:mx-8 lg:mx-11 rounded-md border border-terra/30 bg-terra-bg px-4 py-3 text-[13px] text-terra flex items-center justify-between">
          <span>{generateError}</span>
          <button onClick={() => setGenerateError(null)} className="ml-3 text-terra/60 hover:text-terra">×</button>
        </div>
      )}

      {/* Lede + Boletim + Numeric strip */}
      <Lede
        farmName={data.farm.name}
        region={data.farm.region}
        sectors={data.sectors_summary}
        weather={data.weather_today}
      />

      {/* Numeric strip is inside Lede's wrapper padding area */}
      <div className="px-4 sm:px-8 lg:px-11 border-b border-rule">
        <NumericStrip
          totalSectors={data.sectors_summary.length}
          toIrrigate={toIrrigate}
          noAction={noAction}
          forecastRain48h={data.weather_today.forecast_rain_next_48h_mm}
        />
      </div>

      <SyncStatusBar entries={data.sync_status ?? []} />

      {/* Sector grid with tabs */}
      {data.sectors_summary.length > 0 ? (
        <SectorGrid sectors={data.sectors_summary} farmId={farmId} />
      ) : (
        <div className="mx-4 mt-8 sm:mx-8 rounded-md border border-dashed border-rule px-6 py-12 text-center">
          <p className="font-serif text-[18px] text-ink-2">Sem sectores configurados.</p>
          <p className="mt-2 text-[13px] text-ink-3">Configure um sector para começar a gerar recomendações.</p>
          <button
            onClick={() => router.push("/onboarding")}
            className="mt-5 rounded-full border border-rule px-5 py-2 text-[13px] text-ink-2 hover:bg-paper-in transition-colors"
          >
            Configurar agora
          </button>
        </div>
      )}

      <BottomNav farmId={farmId} />
      <ChatButton farmId={farmId} />
    </div>
  );
}
