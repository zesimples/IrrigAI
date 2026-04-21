"use client";

import type { StressProjection } from "@/types";

interface Props {
  projection: StressProjection;
  onAcceptRecommendation?: () => void;
}

const URGENCY_STYLES = {
  none: {
    border: "border-irrigai-green/30",
    bg: "bg-irrigai-green/5",
    dot: "bg-irrigai-green",
    text: "text-irrigai-green",
  },
  low: {
    border: "border-irrigai-amber/40",
    bg: "bg-irrigai-amber/5",
    dot: "bg-irrigai-amber",
    text: "text-irrigai-amber",
  },
  medium: {
    border: "border-irrigai-amber/60",
    bg: "bg-irrigai-amber/10",
    dot: "bg-irrigai-amber",
    text: "text-irrigai-amber",
  },
  high: {
    border: "border-irrigai-red/50",
    bg: "bg-irrigai-red/5",
    dot: "bg-irrigai-red",
    text: "text-irrigai-red",
  },
};

export function StressProjectionCard({ projection, onAcceptRecommendation }: Props) {
  const style = URGENCY_STYLES[projection.urgency] ?? URGENCY_STYLES.none;

  return (
    <div className={`rounded-xl border ${style.border} ${style.bg} px-4 py-3.5`}>
      <div className="flex items-center justify-between mb-2">
        <p className="text-[11px] font-medium uppercase tracking-[0.05em] text-irrigai-text-hint">
          Projecção de Stress Hídrico · 72h
        </p>
        <span className={`flex items-center gap-1.5 text-[12px] font-medium ${style.text}`}>
          <span className={`h-2 w-2 rounded-full ${style.dot}`} />
          {projection.urgency === "none"
            ? "Sem risco"
            : projection.urgency === "high"
            ? "Urgente"
            : projection.urgency === "medium"
            ? "Provável"
            : "Possível"}
        </span>
      </div>

      <p className="text-[13px] text-irrigai-text mb-3">{projection.message_pt}</p>

      {/* Mini 3-day depletion bars */}
      {projection.projections.length > 0 && (
        <div className="flex gap-2 mb-3">
          {projection.projections.map((p) => {
            const pct = Math.min(100, p.projected_depletion_pct);
            const barColor = p.stress_triggered
              ? "bg-irrigai-red"
              : pct > 60
              ? "bg-irrigai-amber"
              : "bg-irrigai-green";
            const dateLabel = new Date(p.date).toLocaleDateString("pt-PT", {
              weekday: "short",
              day: "numeric",
            });
            return (
              <div key={p.date} className="flex-1 flex flex-col items-center gap-1">
                <div className="w-full h-10 rounded bg-black/[0.05] relative overflow-hidden">
                  <div
                    className={`absolute bottom-0 left-0 right-0 rounded ${barColor} transition-all`}
                    style={{ height: `${pct}%` }}
                  />
                  {/* MAD threshold line — placeholder at 65% */}
                  <div
                    className="absolute left-0 right-0 border-t border-dashed border-black/20"
                    style={{ bottom: "35%" }}
                  />
                </div>
                <span className="text-[10px] text-irrigai-text-hint text-center leading-tight">
                  {dateLabel}
                </span>
                <span className={`text-[10px] font-medium ${p.stress_triggered ? "text-irrigai-red" : "text-irrigai-text-hint"}`}>
                  {pct.toFixed(0)}%
                </span>
              </div>
            );
          })}
        </div>
      )}

      {projection.urgency !== "none" && onAcceptRecommendation && (
        <button
          onClick={onAcceptRecommendation}
          className="w-full text-center text-[12px] font-medium text-irrigai-green hover:underline"
        >
          Aceitar recomendação →
        </button>
      )}
    </div>
  );
}
