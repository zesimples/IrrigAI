"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { farmsApi, clearToken } from "@/lib/api";
import { Logo } from "@/components/ui/Logo";
import { CROP_LABELS } from "@/lib/cropConfig";
import type { Farm, DashboardResponse } from "@/types";

// ─── Helpers ──────────────────────────────────────────────────────────────────

function getGreeting(): string {
  const h = new Date().getHours();
  if (h < 12) return "Bom dia.";
  if (h < 19) return "Boa tarde.";
  return "Boa noite.";
}

function formatDatePT(): string {
  return new Date().toLocaleDateString("pt-PT", {
    day: "numeric",
    month: "long",
    weekday: "long",
  });
}

function formatTimePT(): string {
  return new Date().toLocaleTimeString("pt-PT", { hour: "2-digit", minute: "2-digit" });
}

function timeAgo(isoStr: string | null): string | null {
  if (!isoStr) return null;
  const mins = Math.round((Date.now() - new Date(isoStr).getTime()) / 60_000);
  if (mins < 1) return "agora mesmo";
  if (mins < 60) return `há ${mins} min`;
  const h = Math.floor(mins / 60);
  return `há ${h} h`;
}

// ─── Derived farm data ────────────────────────────────────────────────────────

interface FarmData {
  farm: Farm;
  dashboard: DashboardResponse | null;
  irrigateCount: number;
  totalSectors: number;
  verdict: "regar" | "parcial" | "ok";
  verdictLabel: string;
  verdictWhy: string;
  moisture: number | null;
  lastSync: string | null;
  et0: number | null;
  cultures: string[];
}

function deriveFarmData(farm: Farm, dashboard: DashboardResponse | null): FarmData {
  if (!dashboard) {
    return {
      farm, dashboard: null,
      irrigateCount: 0, totalSectors: 0,
      verdict: "ok", verdictLabel: "A carregar…", verdictWhy: "",
      moisture: null, lastSync: null, et0: null, cultures: [],
    };
  }

  const ss = dashboard.sectors_summary;
  const irrigateCount = ss.filter((s) => s.action === "irrigate").length;
  const totalSectors = ss.length;

  const verdict: "regar" | "parcial" | "ok" =
    irrigateCount === 0 ? "ok" :
    irrigateCount >= Math.ceil(totalSectors / 2) ? "regar" :
    "parcial";

  const verdictLabel =
    irrigateCount === 0 ? "Tudo em ordem" : `Regar ${irrigateCount} sector${irrigateCount !== 1 ? "es" : ""}`;

  const et0 = dashboard.weather_today?.et0_mm ?? null;
  const verdictWhy = et0 != null
    ? `ET₀ ${et0.toFixed(1)} mm hoje`
    : "";

  const depletions = ss.map((s) => s.depletion_pct).filter((d): d is number => d != null);
  const moisture = depletions.length > 0
    ? 1 - depletions.reduce((a, b) => a + b, 0) / depletions.length / 100
    : null;

  const syncTimes = ss.map((s) => s.recommendation_generated_at).filter(Boolean) as string[];
  const lastSync = syncTimes.length > 0
    ? timeAgo(syncTimes.sort().reverse()[0])
    : null;

  const uniqueCrops = [...new Set(ss.map((s) => s.crop_type).filter(Boolean))];
  const cultures = uniqueCrops.map((c) => CROP_LABELS[c] ?? c);

  return { farm, dashboard, irrigateCount, totalSectors, verdict, verdictLabel, verdictWhy, moisture, lastSync, et0, cultures };
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function MoistureBar({ pct }: { pct: number }) {
  const w = Math.round(pct * 100);
  return (
    <div className="relative h-[5px] bg-[#e9e4dc] rounded-full overflow-hidden">
      <div className="absolute left-[45%] right-[25%] top-0 bottom-0 bg-olive/20" />
      <div
        className="absolute left-0 top-0 bottom-0 rounded-full bg-ink-2"
        style={{ width: `${w}%`, opacity: 0.8 }}
      />
      <div
        className="absolute top-[-2px] bottom-[-2px] w-[1.5px] bg-ink"
        style={{ left: `${w}%` }}
      />
    </div>
  );
}

const VERDICT_COLORS = {
  regar:   { accent: "#b84a2a", border: "rgba(184,74,42,0.33)", dot: "bg-terra",        text: "text-[#7a2f1a]" },
  parcial: { accent: "#c9a34a", border: "rgba(201,163,74,0.33)", dot: "bg-[#c9a34a]",  text: "text-[#7a5e1c]" },
  ok:      { accent: "#6b8f4e", border: "rgba(107,143,78,0.33)",  dot: "bg-olive",       text: "text-[#3d5b22]" },
};

function FarmCard({ fd, idx }: { fd: FarmData; idx: number }) {
  const vc = VERDICT_COLORS[fd.verdict];
  const moisturePct = fd.moisture != null ? Math.round(fd.moisture * 100) : null;

  return (
    <Link
      href={`/farms/${fd.farm.id}`}
      className="group block relative bg-card border border-rule rounded-[10px] p-[22px_24px] transition-shadow hover:shadow-[0_4px_18px_rgba(42,37,32,0.08)] no-underline"
    >
      {/* drop-cap accent */}
      <span
        className="absolute left-0 rounded-r-[2px] transition-[width] group-hover:w-1"
        style={{ top: 18, bottom: 18, width: 3, background: vc.accent }}
      />

      {/* Top row */}
      <div className="flex justify-between items-start gap-6">
        <div className="flex-1 min-w-0">
          {/* Index + region */}
          <div className="flex items-baseline gap-2 mb-1.5">
            <span className="font-mono text-[10.5px] tracking-[0.12em] text-ink-3">
              N.º {String(idx).padStart(2, "0")}
            </span>
            <span className="font-mono text-[10px] text-ink-3">·</span>
            <span className="font-serif italic text-[13px] text-ink-3 truncate">
              {fd.farm.region ?? "—"}
            </span>
          </div>

          {/* Name */}
          <p className="font-serif text-[24px] font-medium tracking-[-0.02em] leading-[1.15] text-ink" style={{ textWrap: "balance" } as React.CSSProperties}>
            {fd.farm.name}
          </p>

          {/* Cultures + stats */}
          <div className="flex items-center gap-2 mt-2 flex-wrap">
            {fd.cultures.map((c) => (
              <span key={c} className="font-serif italic text-[13px] text-ink-2 pr-2.5 border-r border-rule last:border-r-0 last:pr-0">
                {c}
              </span>
            ))}
            <span className="font-mono text-[11px] text-ink-3">
              {fd.totalSectors} sector{fd.totalSectors !== 1 ? "es" : ""}
            </span>
          </div>
        </div>

        {/* Verdict pill */}
        <div className="shrink-0 text-right">
          <div
            className="inline-flex items-center gap-1.5 rounded-full bg-paper px-2.5 py-[5px]"
            style={{ border: `1px solid ${vc.border}` }}
          >
            <span className={`h-[6px] w-[6px] rounded-full ${vc.dot}`} />
            <span className={`font-serif text-[13px] font-semibold ${vc.text}`}>
              {fd.verdictLabel}
            </span>
          </div>
          {fd.verdictWhy && (
            <p className="font-serif italic text-[12px] text-ink-3 mt-1.5">
              {fd.verdictWhy}
            </p>
          )}
        </div>
      </div>

      {/* Bottom row — moisture + sync */}
      <div className="grid gap-6 mt-[18px] pt-3.5 border-t border-rule-soft" style={{ gridTemplateColumns: "1fr auto" }}>
        <div>
          <div className="flex items-baseline justify-between mb-1.5">
            <span className="font-mono text-[9.5px] tracking-[0.12em] uppercase text-ink-3">
              Reserva média de água
            </span>
            {moisturePct != null && (
              <span className="font-serif text-[14px] font-semibold text-ink">
                {moisturePct}<span className="font-mono text-[10px] font-normal text-ink-3">%</span>
              </span>
            )}
          </div>
          {fd.moisture != null
            ? <MoistureBar pct={fd.moisture} />
            : <div className="h-[5px] rounded-full bg-[#e9e4dc]" />
          }
        </div>
        <div className="flex items-center gap-3.5 font-mono text-[10px] text-ink-3 tracking-[0.06em] self-end pb-[1px]">
          {fd.lastSync && (
            <span className="flex items-center gap-1.5">
              <span className="h-[5px] w-[5px] rounded-full bg-olive" />
              sync {fd.lastSync}
            </span>
          )}
          <span className="font-serif not-italic text-[13px] text-ink-2 transition-transform group-hover:translate-x-1">
            entrar →
          </span>
        </div>
      </div>
    </Link>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function Home() {
  const router = useRouter();
  const [farmData, setFarmData] = useState<FarmData[] | null>(null);
  const [clock, setClock] = useState({ time: formatTimePT(), date: formatDatePT() });

  // Refresh clock every minute
  useEffect(() => {
    const id = setInterval(() => setClock({ time: formatTimePT(), date: formatDatePT() }), 60_000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    farmsApi.list().then(async (list) => {
      if (list.length === 0) { router.replace("/onboarding"); return; }
      if (list.length === 1) { router.replace(`/farms/${list[0].id}`); return; }

      // Load all dashboards in parallel; failures yield null
      const dashboards = await Promise.all(
        list.map((f) => farmsApi.dashboard(f.id).catch(() => null))
      );
      setFarmData(list.map((f, i) => deriveFarmData(f, dashboards[i])));
    }).catch(() => {});
  }, [router]);

  // ── Loading ────────────────────────────────────────────────────────────────
  if (!farmData) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-paper">
        <div className="flex flex-col items-center gap-4 text-center">
          <Logo size={44} />
          <div>
            <p className="font-serif text-[16px] font-medium text-ink tracking-[-0.01em]">IrrigAI</p>
            <p className="font-mono text-[11px] text-ink-3 mt-1">A carregar…</p>
          </div>
          <div className="h-[2px] w-20 overflow-hidden rounded-full bg-rule">
            <div className="h-full w-1/2 animate-[loading_1.5s_ease-in-out_infinite] rounded-full bg-olive" />
          </div>
        </div>
      </div>
    );
  }

  // ── Derived briefing KPIs ──────────────────────────────────────────────────
  const totalIrrigate = farmData.reduce((s, fd) => s + fd.irrigateCount, 0);
  const et0Values = farmData.map((fd) => fd.et0).filter((v): v is number => v != null);
  const avgEt0 = et0Values.length > 0 ? et0Values.reduce((a, b) => a + b, 0) / et0Values.length : null;
  const farmsNeedingAction = farmData.filter((fd) => fd.irrigateCount > 0).length;

  const greeting = getGreeting();

  const ledeCount = totalIrrigate;
  const ledeFarms = farmsNeedingAction;

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <div className="min-h-screen bg-paper grid md:grid-cols-[1.05fr_1fr]">

      {/* ── LEFT — editorial masthead ──────────────────────────────────────── */}
      <aside className="relative bg-card border-b md:border-b-0 md:border-r border-rule flex flex-col justify-between overflow-hidden px-10 pt-12 pb-8 md:px-14 md:pt-14 md:pb-10">
        {/* Watermark */}
        <div className="pointer-events-none absolute -top-8 -right-8 opacity-[0.06]">
          <Logo size={280} />
        </div>

        <div className="relative">
          {/* Masthead */}
          <div className="flex justify-between items-start pb-[18px] border-b border-ink">
            <div className="flex items-center gap-3">
              <Logo size={36} />
              <div>
                <div className="font-instrument text-[30px] font-normal leading-none tracking-[-0.01em] text-ink">
                  IrrigAI
                </div>
                <div className="font-mono text-[9.5px] text-ink-3 tracking-[0.18em] uppercase mt-[3px]">
                  Boletim de rega
                </div>
              </div>
            </div>
            <div className="text-right font-mono text-[10px] text-ink-3 tracking-[0.12em] uppercase">
              <div>{clock.date}</div>
              <div className="mt-1 text-ink-2">{clock.time}</div>
            </div>
          </div>

          {/* Headline */}
          <h1
            className="font-serif text-[clamp(42px,5vw,64px)] font-medium leading-[1.02] tracking-[-0.035em] text-ink mt-10"
            style={{ textWrap: "balance" } as React.CSSProperties}
          >
            <em className="font-instrument not-italic text-ink-2">{greeting}</em>
          </h1>

          {/* Lede */}
          <p className="font-serif italic text-[clamp(16px,1.8vw,21px)] leading-[1.45] text-ink-2 mt-5 max-w-[520px] tracking-[-0.01em]">
            {ledeCount === 0 ? (
              <>Todas as suas explorações estão <strong className="not-italic font-semibold text-olive">em ordem</strong> esta manhã.</>
            ) : ledeFarms === 1 ? (
              <>Uma das suas explorações precisa de atenção —{" "}
                <strong className="not-italic font-semibold text-terra">{ledeCount} sector{ledeCount !== 1 ? "es" : ""}</strong>{" "}
                recomendam rega antes do meio-dia.</>
            ) : (
              <>{ledeFarms} das suas explorações precisam de atenção —{" "}
                <strong className="not-italic font-semibold text-terra">{ledeCount} sector{ledeCount !== 1 ? "es" : ""}</strong>{" "}
                no total recomendam rega antes do meio-dia.</>
            )}
          </p>

          {/* KPI strip */}
          <div className="flex flex-wrap gap-x-7 gap-y-4 mt-9 pt-[18px] border-t border-rule-soft">
            {[
              { label: "ET₀ médio hoje", value: avgEt0 != null ? avgEt0.toFixed(1) : "—", unit: avgEt0 != null ? "mm" : null },
              { label: "Explorações",    value: String(farmData.length),                    unit: null },
              { label: "A regar hoje",   value: String(ledeCount),                          unit: ledeCount > 0 ? "sectores" : null },
            ].map(({ label, value, unit }) => (
              <div key={label} className="shrink-0">
                <div className="font-mono text-[9.5px] text-ink-3 tracking-[0.12em] uppercase mb-1">{label}</div>
                <div className="flex items-baseline gap-1">
                  <span className="font-serif text-[24px] font-medium text-ink tracking-[-0.02em]">{value}</span>
                  {unit && <span className="font-mono text-[11px] text-ink-3">{unit}</span>}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Footer */}
        <div className="relative mt-8 pt-[18px] border-t border-rule-soft flex justify-between items-center font-mono text-[10px] text-ink-3 tracking-[0.08em]">
          <span>Sessão activa</span>
          <span className="font-serif italic text-[13px]">
            <span className="text-terra">●</span>&nbsp;&nbsp;Sondas a sincronizar a cada 5 min
          </span>
          <button
            onClick={() => { clearToken(); router.push("/login"); }}
            className="hover:text-ink transition-colors cursor-pointer"
          >
            Sair ↗
          </button>
        </div>
      </aside>

      {/* ── RIGHT — farm list ──────────────────────────────────────────────── */}
      <main className="flex flex-col px-10 pt-12 pb-8 md:px-14 md:pt-14 md:pb-10">
        {/* Section header */}
        <header className="flex justify-between items-baseline mb-6">
          <div className="flex items-center gap-2.5">
            <span className="h-[6px] w-[6px] rounded-full bg-terra" />
            <span className="font-mono text-[10.5px] text-terra tracking-[0.16em] uppercase">
              Explorações
            </span>
            <span className="font-serif italic text-[13px] text-ink-3 ml-2">
              escolha por onde começar
            </span>
          </div>
          <span className="font-mono text-[10px] text-ink-3 tracking-[0.08em]">
            {farmData.length} exploraç{farmData.length !== 1 ? "ões" : "ão"}
          </span>
        </header>

        {/* Farm cards */}
        <div className="flex flex-col gap-3.5 flex-1">
          {farmData.map((fd, i) => (
            <FarmCard key={fd.farm.id} fd={fd} idx={i + 1} />
          ))}

          {/* New farm — dotted invitation */}
          <Link
            href="/onboarding"
            className="group flex items-center gap-4 rounded-[10px] border border-dashed border-rule px-6 py-[22px] transition-colors hover:border-ink-2 no-underline"
          >
            <span className="h-[42px] w-[42px] shrink-0 rounded-full border border-dashed border-ink-3 flex items-center justify-center font-serif text-[24px] font-light text-ink-3 group-hover:border-ink-2 group-hover:text-ink-2 transition-colors">
              +
            </span>
            <div className="flex-1">
              <p className="font-serif text-[18px] font-medium text-ink-2 tracking-[-0.01em] group-hover:text-ink transition-colors">
                Adicionar nova exploração
              </p>
              <p className="font-serif italic text-[13px] text-ink-3 mt-0.5">
                Ligue sondas, importe parcelas KML, ou comece em branco.
              </p>
            </div>
            <span className="font-serif italic text-[14px] text-ink-3 group-hover:text-ink-2 transition-colors shrink-0">
              iniciar →
            </span>
          </Link>
        </div>

        {/* Footer note */}
        <footer className="mt-8 pt-[18px] border-t border-rule-soft font-serif italic text-[13px] text-ink-3 leading-[1.55]">
          Os dados estão sempre 5 minutos atrás do campo.{" "}
          <span className="text-ink-2 not-italic">
            O assistente lê tudo antes de si — abra uma exploração e veja o boletim do dia.
          </span>
        </footer>
      </main>
    </div>
  );
}
