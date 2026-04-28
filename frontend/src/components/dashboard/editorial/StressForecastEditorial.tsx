import type { StressProjection } from "@/types";

interface Props {
  projection: StressProjection;
}

const URGENCY = {
  none: {
    border: "border-rule-soft border-l-[3px] border-l-olive",
    bg: "bg-[#f3f1e8]",
    dot: "bg-olive",
    text: "text-olive",
    label: "Sem risco de stress",
    fill: "bg-olive",
  },
  low: {
    border: "border-rule-soft border-l-[3px] border-l-[#c9a34a]",
    bg: "bg-[#faf7ee]",
    dot: "bg-[#c9a34a]",
    text: "text-[#c9a34a]",
    label: "Risco baixo",
    fill: "bg-[#c9a34a]",
  },
  medium: {
    border: "border-rule-soft border-l-[3px] border-l-[#c9a34a]",
    bg: "bg-[#faf7ee]",
    dot: "bg-[#c9a34a]",
    text: "text-[#c9a34a]",
    label: "Risco moderado",
    fill: "bg-[#c9a34a]",
  },
  high: {
    border: "border-rule-soft border-l-[3px] border-l-terra",
    bg: "bg-terra-bg",
    dot: "bg-terra",
    text: "text-terra",
    label: "Risco alto",
    fill: "bg-terra",
  },
} as const;

export function StressForecastEditorial({ projection }: Props) {
  const s = URGENCY[projection.urgency] ?? URGENCY.none;
  const days = projection.projections.slice(0, 4);

  return (
    <article className={`border ${s.border} ${s.bg} p-[18px_22px] mb-[22px] rounded-sm`}>
      <header className="flex items-baseline justify-between mb-1.5">
        <p className="font-mono text-[10px] tracking-[0.14em] uppercase text-ink-3">
          Projecção · próximas 72 h
        </p>
        <div className={`flex items-center gap-1.5 text-[12.5px] font-medium ${s.text}`}>
          <span className={`h-[7px] w-[7px] rounded-full ${s.dot}`} />
          {s.label}
        </div>
      </header>

      <p className="font-serif text-[16px] leading-[1.4] tracking-[-0.005em] text-ink mb-4">
        {projection.message_pt}
      </p>

      {days.length > 0 && (
        <div className="flex gap-3.5">
          {days.map((d) => {
            const pct = Math.min(100, d.projected_depletion_pct);
            const dateLabel = new Date(d.date).toLocaleDateString("pt-PT", {
              weekday: "short",
              day: "numeric",
            });
            return (
              <div key={d.date} className="flex-1 text-center">
                <div className="relative h-[60px] bg-black/[0.04] rounded mb-1.5 overflow-hidden">
                  <div
                    className={`absolute bottom-0 left-0 right-0 rounded-b ${s.fill}`}
                    style={{ height: `${Math.min(pct * 1.2, 100)}%` }}
                  />
                  <div
                    className="absolute left-0 right-0 border-t border-dashed border-ink-3 opacity-60"
                    style={{ top: "40%" }}
                  />
                </div>
                <p className="font-mono text-[10px] text-ink-3 tracking-[0.04em]">{dateLabel}</p>
                <p className="font-serif text-[14px] font-medium text-ink mt-0.5">{pct.toFixed(0)}%</p>
              </div>
            );
          })}
        </div>
      )}
    </article>
  );
}
