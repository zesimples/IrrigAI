import type { SectorDailyBreakdown } from "@/types";

interface FlowmeterSparklineProps {
  data: SectorDailyBreakdown[];
  barColor?: string;
}

export function FlowmeterSparkline({
  data,
  barColor = "#6b9e3a",
}: FlowmeterSparklineProps) {
  if (!data.length) return <span className="text-ink-4 text-xs">—</span>;

  const max = Math.max(...data.map((d) => d.m3_ha), 0.1);

  return (
    <div className="flex items-end gap-[2px] h-5">
      {data.map((d, i) => {
        const height = d.m3_ha > 0 ? Math.max(3, Math.round((d.m3_ha / max) * 20)) : 3;
        return (
          <div
            key={i}
            title={`${d.date}: ${d.m3_ha.toFixed(1)} m³/ha`}
            style={{
              width: 6,
              height,
              backgroundColor: d.m3_ha > 0 ? barColor : "#e5e3de",
              borderRadius: "1px 1px 0 0",
            }}
          />
        );
      })}
    </div>
  );
}
