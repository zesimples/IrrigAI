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
  rootDepthCm?: number | null;
  events?: ProbeDetectedEvent[];
  hoveredEventId?: string | null;
}

interface SumPoint {
  ts: number;
  sum: number;
  depthCount: number;
}

/** Depths that actually have readings in the window. Silent sensors / stale
 * ProbeDepth rows still arrive as empty series and must not scale the
 * CC/PMP reference lines (they contribute nothing to the summed line). */
export function countLiveDepths(depths: DepthReadings[]): number {
  return depths.filter((d) => d.readings.length > 0).length;
}

/** Keep the summed decision view on the same soil volume as the recommendation.
 * If the configured root zone is shallower than every sensor, mirror the engine's
 * fallback and retain all depths instead of rendering an empty chart. */
export function filterRootzoneDepths(
  depths: DepthReadings[],
  rootDepthCm?: number | null,
): DepthReadings[] {
  if (rootDepthCm == null) return depths;
  const inZone = depths.filter((d) => d.depth_cm <= rootDepthCm);
  return inZone.length > 0 ? inZone : depths;
}

/** Sum one reference bound (CC or PMP) across live depths.
 *
 * Prefers each depth's own observed envelope (per-layer bounds from the
 * backend); falls back to the sector-resolved per-depth value for depths
 * without one. Dead depths (no readings) don't count at all. Returns null
 * when a live depth has no envelope and there is no fallback. */
export function sumReferenceBound(
  depths: DepthReadings[],
  perDepth: (d: DepthReadings) => number | null | undefined,
  fallback: number | null | undefined,
): number | null {
  const live = depths.filter((d) => d.readings.length > 0);
  if (live.length === 0) return null;
  let total = 0;
  for (const d of live) {
    const v = perDepth(d) ?? fallback;
    if (v == null) return null;
    total += v;
  }
  return total * 100;
}

export function buildSumData(depths: DepthReadings[]) {
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
  // Normalize rows where not every live depth reported at that timestamp
  // (per-depth downsampling keeps original timestamps, so depths can
  // misalign): plot avg-of-reporting × live-count instead of a partial sum
  // that fakes a dip against the n-scaled reference lines.
  const nLive = countLiveDepths(depths);
  const rows = [...map.values()].sort((a, b) => a.ts - b.ts);
  for (const row of rows) {
    if (row.depthCount > 0 && row.depthCount < nLive) {
      row.sum = (row.sum / row.depthCount) * nLive;
    }
  }
  return rows;
}

/** Zoom the Y axis around the observed series and agronomic thresholds.
 * Keeping CC and PMP inside the domain preserves the meaning of the coloured
 * bands, while a small padding avoids pinning the line to the chart edges. */
export function calculateSumDomain(
  minValue: number,
  maxValue: number,
  sumWP: number | null,
  sumFC: number | null,
): [number, number] {
  const values = [minValue, maxValue, sumWP, sumFC].filter(
    (value): value is number => value != null && Number.isFinite(value),
  );
  const domainMin = Math.min(...values);
  const domainMax = Math.max(...values);
  const span = domainMax - domainMin;
  const padding = Math.max(5, span * 0.12);

  return [
    Math.floor(Math.max(0, domainMin - padding)),
    Math.ceil(domainMax + padding),
  ];
}

export function ProbeSumChart({
  depths,
  referenceLines,
  rootDepthCm,
  events,
  hoveredEventId,
}: ProbeSumChartProps) {
  const summedDepths = filterRootzoneDepths(depths, rootDepthCm);
  const data = buildSumData(summedDepths);

  if (data.length === 0) {
    return (
      <div className="flex h-48 items-center justify-center rounded-lg bg-paper-in text-[13px] text-ink-3">
        Sem dados para o período seleccionado
      </div>
    );
  }

  // Sum each live depth's own observed envelope (per-layer bounds); depths
  // without one use the sector-resolved value. Dead sensors count for nothing.
  const sumFC = sumReferenceBound(summedDepths, (d) => d.field_capacity, referenceLines.field_capacity);
  const sumWP = sumReferenceBound(summedDepths, (d) => d.wilting_point, referenceLines.wilting_point);

  const maxVal = Math.max(...data.map((d) => d.sum));
  const minVal = Math.min(...data.map((d) => d.sum));
  const latest = data[data.length - 1];
  const [yMin, yMax] = calculateSumDomain(minVal, maxVal, sumWP, sumFC);

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
            formatter={(value: number) => [`${value.toFixed(1)}%`, "Soma da zona radicular"]}
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
          <p className="font-mono text-[9.5px] uppercase tracking-[0.1em] text-ink-3">Soma atual · zona radicular</p>
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
