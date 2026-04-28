import { SoilBar } from "./SoilBar";

interface KpiCellProps {
  label: string;
  value: string | number;
  unit?: string;
  sub?: string;
  tint?: "terra" | "olive" | "amber" | "ink";
  bar?: number; // 0..1
  first?: boolean;
}

export function KpiCell({ label, value, unit, sub, tint = "ink", bar, first }: KpiCellProps) {
  const valueColor = {
    terra: "text-terra",
    olive: "text-olive",
    amber: "text-[#c9a34a]",
    ink: "text-ink",
  }[tint];

  return (
    <div className={`px-4 py-3.5${first ? "" : " border-l border-rule-soft"}`}>
      <p className="font-mono text-[10.5px] tracking-[0.06em] uppercase text-ink-3 mb-1.5">{label}</p>
      <div className="flex items-baseline gap-1.5">
        <span className={`font-serif text-[28px] font-medium leading-none tracking-[-0.02em] ${valueColor}`}>
          {value}
        </span>
        {unit && <span className="font-mono text-[11px] text-ink-3">{unit}</span>}
      </div>
      {sub && <p className="text-[11px] text-ink-3 mt-1">{sub}</p>}
      {bar !== undefined && (
        <div className="mt-2">
          <SoilBar value={bar} tint={tint === "terra" ? "terra" : "olive"} />
        </div>
      )}
    </div>
  );
}
