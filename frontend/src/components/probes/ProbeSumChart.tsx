"use client";

import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { format } from "date-fns";
import type { DepthReadings, ProbeDetectedEvent, ReferenceLines } from "@/types";

interface ProbeSumChartProps {
  depths: DepthReadings[];
  referenceLines: ReferenceLines;
  events?: ProbeDetectedEvent[];
  hoveredEventId?: string | null;
}

interface SumPoint {
  ts: number;
  sum: number;
  depthCount: number;
}

function buildSumData(depths: DepthReadings[]) {
  const map = new Map<string, SumPoint>();
  for (const d of depths) {
    for (const pt of d.readings) {
      const ts = pt.timestamp;
      if (!map.has(ts)) {
        map.set(ts, { ts: new Date(ts).getTime(), sum: 0, depthCount: 0 });
      }
      const row = map.get(ts)!;
      row.sum += pt.vwc * 100;
      row.depthCount += 1;
    }
  }
  return [...map.values()].sort((a, b) => a.ts - b.ts);
}

export function ProbeSumChart({ depths, referenceLines, events, hoveredEventId }: ProbeSumChartProps) {
  const data = buildSumData(depths);

  if (data.length === 0) {
    return (
      <div className="flex h-48 items-center justify-center rounded-lg bg-paper-in text-[13px] text-ink-3">
        Sem dados para o período seleccionado
      </div>
    );
  }

  const n = depths.length;

  // Per-depth FC/WP take priority; fall back to the global reference lines
  const fcPerDepth = depths[0]?.field_capacity ?? referenceLines.field_capacity;
  const wpPerDepth = depths[0]?.wilting_point ?? referenceLines.wilting_point;

  const sumFC = fcPerDepth != null ? fcPerDepth * 100 * n : null;
  const sumWP = wpPerDepth != null ? wpPerDepth * 100 * n : null;

  const maxVal = Math.max(...data.map((d) => d.sum));
  const minVal = Math.min(...data.map((d) => d.sum));
  const latest = data[data.length - 1];
  const yMax = Math.ceil(Math.max(maxVal, sumFC ?? 0) * 1.12);
  const yMin = 0;

  return (
    <div className="space-y-2">
      <ResponsiveContainer width="100%" height={280}>
        <LineChart data={data} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e8e4dc" />

          {/* Stress zone — below WP */}
          {sumWP != null && (
            <ReferenceArea y1={yMin} y2={sumWP} fill="#f87171" fillOpacity={0.18} />
          )}

          {/* Comfort zone — between WP and FC */}
          {sumWP != null && sumFC != null && (
            <ReferenceArea y1={sumWP} y2={sumFC} fill="#4ade80" fillOpacity={0.14} />
          )}

          {/* Saturated zone — above FC */}
          {sumFC != null && (
            <ReferenceArea y1={sumFC} y2={yMax} fill="#60a5fa" fillOpacity={0.18} />
          )}

          {sumFC != null && (
            <ReferenceLine
              y={sumFC}
              stroke="#16a34a"
              strokeDasharray="5 3"
              label={{ value: "CC", fontSize: 10, fill: "#16a34a", position: "insideTopRight" }}
            />
          )}
          {sumWP != null && (
            <ReferenceLine
              y={sumWP}
              stroke="#dc2626"
              strokeDasharray="5 3"
              label={{ value: "PMP", fontSize: 10, fill: "#dc2626", position: "insideBottomRight" }}
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

          <XAxis
            dataKey="ts"
            type="number"
            domain={["auto", "auto"]}
            scale="time"
            tickFormatter={(v) => format(new Date(v), "dd/MM HH:mm")}
            tick={{ fontSize: 11 }}
          />
          <YAxis
            tickFormatter={(v) => `${v.toFixed(0)}%`}
            domain={[yMin, yMax]}
            tick={{ fontSize: 11 }}
            width={40}
          />
          <Tooltip
            formatter={(value: number) => [`${value.toFixed(1)}%`, "Soma das profundidades"]}
            labelFormatter={(label: number) => format(new Date(label), "dd/MM/yyyy HH:mm")}
            contentStyle={{ fontSize: 12 }}
          />

          <Line
            type="monotone"
            dataKey="sum"
            stroke="#1c1917"
            dot={false}
            strokeWidth={1.5}
            connectNulls={false}
          />
        </LineChart>
      </ResponsiveContainer>

      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        <div className="rounded-md border border-rule-soft bg-card px-3 py-2">
          <p className="font-mono text-[9.5px] uppercase tracking-[0.1em] text-ink-3">Soma atual</p>
          <p className="mt-0.5 font-mono text-[14px] font-medium text-ink tabular-nums">
            {latest.sum.toFixed(1)}%
          </p>
        </div>
        <div className="rounded-md border border-rule-soft bg-card px-3 py-2">
          <p className="font-mono text-[9.5px] uppercase tracking-[0.1em] text-ink-3">Min / Max</p>
          <p className="mt-0.5 font-mono text-[14px] font-medium text-ink tabular-nums">
            {minVal.toFixed(1)}% / {maxVal.toFixed(1)}%
          </p>
        </div>
      </div>

      {/* Zone legend */}
      <div className="flex flex-wrap gap-x-4 gap-y-1 px-1">
        <span className="flex items-center gap-1.5 font-mono text-[10px] text-ink-3">
          <span className="h-2 w-4 rounded-sm bg-[#60a5fa]/50 shrink-0" />
          Saturado
        </span>
        <span className="flex items-center gap-1.5 font-mono text-[10px] text-ink-3">
          <span className="h-2 w-4 rounded-sm bg-[#4ade80]/50 shrink-0" />
          Conforto
        </span>
        <span className="flex items-center gap-1.5 font-mono text-[10px] text-ink-3">
          <span className="h-2 w-4 rounded-sm bg-[#f87171]/50 shrink-0" />
          Stress
        </span>
        {sumFC != null && (
          <span className="font-mono text-[10px] text-ink-3 ml-auto">
            CC soma: {sumFC.toFixed(0)}% · PMP soma: {sumWP?.toFixed(0) ?? "—"}%
          </span>
        )}
      </div>
    </div>
  );
}
