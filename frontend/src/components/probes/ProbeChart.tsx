"use client";

import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { format } from "date-fns";
import type { DepthReadings, ProbeDetectedEvent, ReferenceLines } from "@/types";

const DEPTH_COLORS = [
  "#059669", // emerald-600
  "#0284c7", // sky-600
  "#d97706", // amber-600
  "#7c3aed", // violet-600
  "#db2777", // pink-600
];

interface RootzonePoint {
  timestamp: string;
  vwc: number;
  quality?: string;
}

interface ProbeChartProps {
  depths: DepthReadings[];
  referenceLines: ReferenceLines;
  events?: ProbeDetectedEvent[];
  hoveredEventId?: string | null;
  interval?: string;
  /** Rootzone-weighted SWC series — the value the recommendation engine actually
   *  uses. Rendered as a distinct, prominent line so the chart can't visually
   *  disagree with the recommendation on split-moisture profiles. */
  rootzoneSwc?: RootzonePoint[];
  rootDepthCm?: number | null;
}

const ROOTZONE_COLOR = "#1c1917"; // near-black, distinct from depth palette + CC/PMP

// Merge all depth readings into a unified timeline keyed by timestamp
function buildChartData(depths: DepthReadings[], rootzoneSwc?: RootzonePoint[]) {
  const map = new Map<string, Record<string, number>>();
  for (const d of depths) {
    for (const pt of d.readings) {
      const ts = pt.timestamp;
      if (!map.has(ts)) map.set(ts, { ts: new Date(ts).getTime() });
      const row = map.get(ts)!;
      row[`d_${d.depth_cm}`] = pt.vwc;
    }
  }
  for (const pt of rootzoneSwc ?? []) {
    const ts = pt.timestamp;
    if (!map.has(ts)) map.set(ts, { ts: new Date(ts).getTime() });
    const row = map.get(ts)!;
    row.rootzone = pt.vwc;
  }
  return [...map.values()].sort((a, b) => a.ts - b.ts);
}

function fmtTick(ts: number) {
  return format(new Date(ts), "dd/MM HH:mm");
}

export function ProbeChart({
  depths,
  referenceLines,
  events,
  hoveredEventId,
  rootzoneSwc,
  rootDepthCm,
}: ProbeChartProps) {
  const data = buildChartData(depths, rootzoneSwc);

  if (data.length === 0) {
    return (
      <div className="flex h-48 items-center justify-center rounded-lg bg-gray-50 text-sm text-gray-500">
        Sem dados de leitura para o período seleccionado
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={320}>
      <LineChart data={data} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
        <XAxis
          dataKey="ts"
          type="number"
          domain={["auto", "auto"]}
          scale="time"
          tickFormatter={fmtTick}
          tick={{ fontSize: 11 }}
        />
        <YAxis
          tickFormatter={(v) => `${(v * 100).toFixed(0)}%`}
          domain={[0, 0.6]}
          tick={{ fontSize: 11 }}
          width={40}
        />
        <Tooltip
          formatter={(value: number, name: string) => [
            `${(value * 100).toFixed(1)}%`,
            name === "rootzone" ? "Zona radicular (média)" : name.replace("d_", "") + " cm",
          ]}
          labelFormatter={(label: number) =>
            format(new Date(label), "dd/MM/yyyy HH:mm")
          }
        />
        <Legend
          formatter={(value) =>
            value === "rootzone" ? "Zona radicular (média)" : value.replace("d_", "") + " cm"
          }
          wrapperStyle={{ fontSize: 12 }}
        />
        {referenceLines.field_capacity != null && (
          <ReferenceLine
            y={referenceLines.field_capacity}
            stroke="#16a34a"
            strokeDasharray="6 3"
            label={{ value: "CC", fontSize: 11, fill: "#16a34a", position: "insideTopRight" }}
          />
        )}
        {referenceLines.wilting_point != null && (
          <ReferenceLine
            y={referenceLines.wilting_point}
            stroke="#dc2626"
            strokeDasharray="6 3"
            label={{ value: "PMP", fontSize: 11, fill: "#dc2626", position: "insideBottomRight" }}
          />
        )}
        {events?.map((event) => {
          const hovered = hoveredEventId === event.id;
          const color = event.kind === "rain" ? "#0284c7" : event.kind === "irrigation" ? "#059669" : "#d97706";
          return (
            <ReferenceLine
              key={event.id}
              x={new Date(event.timestamp).getTime()}
              stroke={color}
              strokeDasharray={hovered ? undefined : "4 4"}
              strokeWidth={hovered ? 2 : 1}
              strokeOpacity={hovered ? 1 : 0.6}
              label={{
                value: event.kind === "rain" ? "Chuva" : event.kind === "irrigation" ? "Rega" : `+${(event.delta_vwc * 100).toFixed(1)}%`,
                fontSize: hovered ? 11 : 10,
                fontWeight: hovered ? 600 : 400,
                fill: color,
                position: "insideTop",
              }}
            />
          );
        })}
        {depths.map((d, idx) => (
          <Line
            key={d.depth_cm}
            type="monotone"
            dataKey={`d_${d.depth_cm}`}
            stroke={DEPTH_COLORS[idx % DEPTH_COLORS.length]}
            dot={false}
            strokeWidth={1.5}
            connectNulls={false}
          />
        ))}
        {rootzoneSwc && rootzoneSwc.length > 0 && (
          <Line
            key="rootzone"
            type="monotone"
            dataKey="rootzone"
            name="rootzone"
            data-testid="rootzone-line"
            stroke={ROOTZONE_COLOR}
            dot={false}
            strokeWidth={3}
            connectNulls={false}
          />
        )}
      </LineChart>
    </ResponsiveContainer>
  );
}

/** Exported for the hint text next to the chart (root depth used for the overlay). */
export function formatRootDepthHint(rootDepthCm?: number | null): string | null {
  if (rootDepthCm == null) return null;
  return `Zona radicular: ${Math.round(rootDepthCm)} cm (valor usado pela recomendação)`;
}
