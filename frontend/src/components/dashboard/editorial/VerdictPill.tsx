import type { DoseBand } from "@/types";

export type Verdict = DoseBand | "em-rega";

interface VerdictPillProps {
  verdict: Verdict;
  size?: "sm" | "lg";
}

const CONFIG: Record<Verdict, { label: string; className: string; dot: boolean }> = {
  reforcada:   { label: "Rega reforçada", className: "bg-terra text-[#fef7f2]", dot: true },
  normal:      { label: "Rega normal",    className: "bg-olive/15 text-ink-2 border border-olive/30", dot: false },
  curta:       { label: "Rega curta",     className: "bg-[#f4f1ec] text-ink-2 border border-[#e3ddd2]", dot: false },
  pode_saltar: { label: "Pode saltar",    className: "bg-[#f4f1ec] text-ink-3 border border-[#e3ddd2]", dot: false },
  "em-rega":   { label: "Em rega",        className: "bg-water text-white", dot: false },
};

export function VerdictPill({ verdict, size = "sm" }: VerdictPillProps) {
  const c = CONFIG[verdict];
  const pad = size === "lg" ? "px-3 py-1.5 text-[13px]" : "px-2.5 py-[3px] text-[11px]";
  return (
    <span
      aria-label={`Recomendação: ${c.label}`}
      className={`inline-flex items-center gap-1.5 rounded-full font-medium tracking-[-0.01em] whitespace-nowrap ${pad} ${c.className}`}
    >
      {c.dot && <span className="h-1 w-1 rounded-full bg-[#fef7f2]" />}
      {c.label}
    </span>
  );
}
