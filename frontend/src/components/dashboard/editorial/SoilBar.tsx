interface SoilBarProps {
  value: number; // 0..1, where 1 = fully saturated
  tint?: "olive" | "terra";
  tall?: boolean;
}

export function SoilBar({ value, tint = "olive", tall = false }: SoilBarProps) {
  const pct = Math.max(0, Math.min(1, value)) * 100;
  const fillColor = tint === "terra" ? "#b84a2a" : "#6b8f4e";
  const h = tall ? "h-2" : "h-1.5";
  return (
    <div className={`relative ${h} w-full rounded-full overflow-hidden bg-[#e9e4dc]`}>
      {/* Optimal zone 35%–65% */}
      <div className="absolute inset-y-0 left-[35%] right-[35%] bg-olive/10" />
      <div
        className="absolute inset-y-0 left-0 rounded-full"
        style={{ width: `${pct}%`, backgroundColor: fillColor }}
      />
    </div>
  );
}
