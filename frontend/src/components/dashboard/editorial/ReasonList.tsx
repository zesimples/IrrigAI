import { ConfidenceDots, type Confidence } from "./ConfidenceDots";
import type { RecommendationReason } from "@/types";

interface ReasonListProps {
  reasons: RecommendationReason[];
  confidence: Confidence;
  confidencePct: number;
}

// Maps API category keys (English snake_case) to Portuguese display labels + colour
const CATEGORY_MAP: Record<string, { label: string; color: string }> = {
  water_balance:      { label: "Solo",          color: "text-olive" },
  soil:               { label: "Solo",          color: "text-olive" },
  solo:               { label: "Solo",          color: "text-olive" },
  evapotranspiration: { label: "ET₀",           color: "text-terra" },
  et0:                { label: "ET₀",           color: "text-terra" },
  crop:               { label: "Cultura",       color: "text-terra" },
  cultura:            { label: "Cultura",       color: "text-terra" },
  rainfall:           { label: "Chuva",         color: "text-terra" },
  weather:            { label: "Meteorologia",  color: "text-terra" },
  meteorologia:       { label: "Meteorologia",  color: "text-terra" },
  trigger:            { label: "Reserva",       color: "text-ink-2" },
  reserva:            { label: "Reserva",       color: "text-ink-2" },
  stress:             { label: "Stress",        color: "text-[#c9a34a]" },
  confidence:         { label: "Fiabilidade",   color: "text-[#c9a34a]" },
  fiabilidade:        { label: "Fiabilidade",   color: "text-[#c9a34a]" },
  limitation:         { label: "Limitação",     color: "text-[#c9a34a]" },
  limitacao:          { label: "Limitação",     color: "text-[#c9a34a]" },
  warning:            { label: "Aviso",         color: "text-[#c9a34a]" },
  aviso:              { label: "Aviso",         color: "text-[#c9a34a]" },
  probe:              { label: "Sonda",         color: "text-ink-3" },
  sonda:              { label: "Sonda",         color: "text-ink-3" },
};

function resolveCategory(cat: string): { label: string; color: string } {
  const key = cat.toLowerCase().replace(/-/g, "_");
  if (CATEGORY_MAP[key]) return CATEGORY_MAP[key];
  // Partial match fallback
  for (const [k, v] of Object.entries(CATEGORY_MAP)) {
    if (key.includes(k) || k.includes(key)) return v;
  }
  return { label: cat, color: "text-ink-3" };
}

function confidenceValueColor(level: Confidence): string {
  if (level === "alta") return "text-olive";
  if (level === "media" || level === "baixa") return "text-[#c9a34a]";
  return "text-ink-3";
}

function confidenceValueLabel(level: Confidence, pct: number): string {
  if (level === "alta") return `alta · ${pct}%`;
  if (level === "media") return `média · ${pct}%`;
  if (level === "baixa") return `baixa · ${pct}%`;
  return "sem sonda";
}

export function ReasonList({ reasons, confidence, confidencePct }: ReasonListProps) {
  const sorted = [...reasons].sort((a, b) => a.order - b.order);

  return (
    <article className="bg-card border border-rule-soft rounded-lg p-[22px_26px] mb-[22px]">
      <header className="flex items-baseline justify-between mb-3.5">
        <div className="flex items-center gap-2">
          <span className="h-1.5 w-1.5 rounded-full bg-terra" />
          <span className="font-mono text-[10.5px] tracking-[0.16em] uppercase text-terra">
            Razões da decisão
          </span>
        </div>
        <div className="flex items-center gap-2 text-[11.5px] text-ink-3">
          <span>Fiabilidade</span>
          <ConfidenceDots level={confidence} />
          <span className={`font-medium ${confidenceValueColor(confidence)}`}>
            {confidenceValueLabel(confidence, confidencePct)}
          </span>
        </div>
      </header>

      <ol className="list-none m-0 p-0">
        {sorted.map((r, i) => {
          const { label, color } = resolveCategory(r.category);
          return (
            <li
              key={r.order}
              className={`grid gap-3.5 py-3.5 items-baseline${i > 0 ? " border-t border-rule-soft" : ""}`}
              style={{ gridTemplateColumns: "34px 92px 1fr" }}
            >
              <span className="font-serif italic text-[18px] text-ink-3">{i + 1}.</span>
              <span className={`font-mono text-[10.5px] tracking-[0.1em] uppercase font-medium ${color}`}>
                {label}
              </span>
              <span
                className="font-serif text-[15.5px] leading-[1.5] text-ink"
                style={{ textWrap: "pretty" } as React.CSSProperties}
              >
                {r.message_pt}
              </span>
            </li>
          );
        })}
      </ol>
    </article>
  );
}
