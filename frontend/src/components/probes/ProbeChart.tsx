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

interface ProbeChartProps {
  depths: DepthReadings[];
  referenceLines: ReferenceLines;
  events?: ProbeDetectedEvent[];
  interval?: string;
}

// Merge all depth readings into a unified timeline keyed by timestamp
function buildChartData(depths: DepthReadings[]) {
  const map = new Map<string, Record<string, number>>();
  for (const d of depths) {
    for (const pt of d.readings) {
      const ts = pt.timestamp;
      if (!map.has(ts)) map.set(ts, { ts: new Date(ts).getTime() });
      const row = map.get(ts)!;
      row[`d_${d.depth_cm}`] = pt.vwc;
    }
  }
  return [...map.values()].sort((a, b) => a.ts - b.ts);
}

function fmtTick(ts: number) {
  return format(new Date(ts), "dd/MM HH:mm");
}

export function ProbeChart({ depths, referenceLines, events }: ProbeChartProps) {
  const data = buildChartData(depths);

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
            name.replace("d_", "") + " cm",
          ]}
          labelFormatter={(label: number) =>
            format(new Date(label), "dd/MM/yyyy HH:mm")
          }
        />
        <Legend
          formatter={(value) => value.replace("d_", "") + " cm"}
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
        {events?.map((event) => (
          <ReferenceLine
            key={event.id}
            x={new Date(event.timestamp).getTime()}
            stroke={event.kind === "rain" ? "#0284c7" : event.kind === "irrigation" ? "#059669" : "#d97706"}
            strokeDasharray="4 4"
            label={{
              value: event.kind === "rain" ? "Chuva" : event.kind === "irrigation" ? "Rega" : "H2O?",
              fontSize: 10,
              fill: event.kind === "rain" ? "#0284c7" : event.kind === "irrigation" ? "#059669" : "#d97706",
              position: "insideTop",
            }}
          />
        ))}
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
      </LineChart>
    </ResponsiveContainer>
  );
}
