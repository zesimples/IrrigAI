// frontend/src/components/flowmeter/FlowmeterSparkline.tsx
import type { SectorDailyBreakdown } from "@/types";

interface FlowmeterSparklineProps {
  data: SectorDailyBreakdown[];
}

export function FlowmeterSparkline({ data }: FlowmeterSparklineProps) {
  const H = 32;
  const gap = 4;

  const hasAnyData = data.some((d) => d.m3_ha > 0);

  // No-data state: thin 2px lines for each day
  if (!hasAnyData) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', gap, height: H }}>
        {Array.from({ length: 7 }).map((_, i) => (
          <span key={i} style={{ flex: 1, height: 2, background: '#e8e0d0', borderRadius: 2 }} />
        ))}
      </div>
    );
  }

  const max = Math.max(...data.map((d) => d.m3_ha), 1);

  return (
    <div style={{ display: 'flex', alignItems: 'flex-end', gap, height: H, position: 'relative' }}>
      {/* baseline */}
      <div style={{ position: 'absolute', left: 0, right: 0, bottom: 0, borderTop: '1px solid #e8e0d0' }} />
      {data.map((d, i) => {
        const active = d.m3_ha > 0;
        const h = active ? Math.max(4, (d.m3_ha / max) * (H - 4)) : 2;
        return (
          <div
            key={i}
            title={`${d.date}: ${d.m3_ha.toFixed(1)} m³/ha`}
            style={{
              flex: 1,
              height: h,
              background: active ? '#b84a2a' : '#e8e0d0',
              borderRadius: 2,
            }}
          />
        );
      })}
    </div>
  );
}
