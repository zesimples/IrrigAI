"use client";

// Deliberately NOT in page.tsx: a Next.js "page" file may only export the
// well-known page fields (default component, metadata, generateStaticParams,
// …) — `next build`'s type-checker rejects any other named export
// ("FarmCard" is not a valid Page export field"). FarmCard needs a named
// export so it can be unit-tested without mounting the whole page (data
// fetching + router), so it lives in its own module instead.
import Link from "next/link";
import { FarmCalibrationControls } from "@/components/farms/FarmCalibrationControls";
import type { FarmData } from "./page";

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

export function FarmCard({ fd, idx }: { fd: FarmData; idx: number }) {
  const vc = VERDICT_COLORS[fd.verdict];
  const moisturePct = fd.moisture != null ? Math.round(fd.moisture * 100) : null;

  return (
    <div className="bg-card border border-rule rounded-[10px] overflow-hidden transition-shadow hover:shadow-[0_4px_18px_rgba(42,37,32,0.08)]">
      <Link
        href={`/farms/${fd.farm.id}`}
        className="group block relative p-[22px_24px] no-underline"
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
      <FarmCalibrationControls
        farmId={fd.farm.id}
        initialEnabled={fd.farm.calibration_auto_apply}
      />
    </div>
  );
}
