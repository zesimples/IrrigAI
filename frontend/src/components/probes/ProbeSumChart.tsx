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
import type { ProbeDetectedEvent, ReferenceLines } from "@/types";

interface RootzonePoint {
  timestamp: string;
  vwc: number;
  quality?: string;
}

interface ProbeSumChartProps {
  rootzoneSwc: RootzonePoint[];
  referenceLines: ReferenceLines;
  events?: ProbeDetectedEvent[];
  hoveredEventId?: string | null;
}

export interface RootzoneChartPoint {
  ts: number;
  vwcPct: number;
  depletionPct: number | null;
  availablePct: number | null;
}

/** Use the same normalized depletion equation and CC/PMP clamping as the
 * backend water-balance engine. */
export function computeRootzoneDepletionPct(
  vwc: number,
  fieldCapacity: number | null | undefined,
  wiltingPoint: number | null | undefined,
): number | null {
  if (
    fieldCapacity == null ||
    wiltingPoint == null ||
    fieldCapacity <= wiltingPoint
  ) {
    return null;
  }

  const clampedVwc = Math.max(wiltingPoint, Math.min(fieldCapacity, vwc));
  return ((fieldCapacity - clampedVwc) / (fieldCapacity - wiltingPoint)) * 100;
}

export function buildRootzoneData(
  points: RootzonePoint[],
  referenceLines: ReferenceLines,
): RootzoneChartPoint[] {
  return points
    .map((point) => {
      const depletionPct = computeRootzoneDepletionPct(
        point.vwc,
        referenceLines.field_capacity,
        referenceLines.wilting_point,
      );
      return {
        ts: new Date(point.timestamp).getTime(),
        vwcPct: point.vwc * 100,
        depletionPct,
        availablePct: depletionPct == null ? null : 100 - depletionPct,
      };
    })
    .sort((a, b) => a.ts - b.ts);
}

/** Zoom the Y axis around the weighted series and the engine's CC/PMP bounds. */
export function calculateSumDomain(
  minValue: number,
  maxValue: number,
  pwpPct: number | null,
  fcPct: number | null,
): [number, number] {
  const values = [minValue, maxValue, pwpPct, fcPct].filter(
    (value): value is number => value != null && Number.isFinite(value),
  );
  const domainMin = Math.min(...values);
  const domainMax = Math.max(...values);
  const span = domainMax - domainMin;
  const padding = Math.max(1, span * 0.12);

  return [
    Math.floor(Math.max(0, domainMin - padding)),
    Math.ceil(domainMax + padding),
  ];
}

export function ProbeSumChart({
  rootzoneSwc,
  referenceLines,
  events,
  hoveredEventId,
}: ProbeSumChartProps) {
  const data = buildRootzoneData(rootzoneSwc, referenceLines);

  if (data.length === 0) {
    return (
      <div className="flex h-48 items-center justify-center rounded-lg bg-paper-in text-[13px] text-ink-3">
        Sem média ponderada da zona radicular para o período seleccionado
      </div>
    );
  }

  const fcPct =
    referenceLines.field_capacity == null
      ? null
      : referenceLines.field_capacity * 100;
  const pwpPct =
    referenceLines.wilting_point == null
      ? null
      : referenceLines.wilting_point * 100;
  const maxVal = Math.max(...data.map((point) => point.vwcPct));
  const minVal = Math.min(...data.map((point) => point.vwcPct));
  const latest = data[data.length - 1];
  const [yMin, yMax] = calculateSumDomain(minVal, maxVal, pwpPct, fcPct);

  return (
    <div className="space-y-2">
      <ResponsiveContainer width="100%" height={280}>
        <LineChart data={data} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e8e4dc" />

          {pwpPct != null && (
            <ReferenceArea y1={yMin} y2={pwpPct} fill="#f87171" fillOpacity={0.18} />
          )}
          {pwpPct != null && fcPct != null && (
            <ReferenceArea y1={pwpPct} y2={fcPct} fill="#4ade80" fillOpacity={0.14} />
          )}
          {fcPct != null && (
            <ReferenceArea y1={fcPct} y2={yMax} fill="#60a5fa" fillOpacity={0.18} />
          )}

          {fcPct != null && (
            <ReferenceLine
              y={fcPct}
              stroke="#16a34a"
              strokeDasharray="5 3"
              label={{ value: "CC", fontSize: 10, fill: "#16a34a", position: "insideTopRight" }}
            />
          )}
          {pwpPct != null && (
            <ReferenceLine
              y={pwpPct}
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
            tickFormatter={(value) => format(new Date(value), "dd/MM HH:mm")}
            tick={{ fontSize: 11 }}
          />
          <YAxis
            tickFormatter={(value) => `${value.toFixed(0)}%`}
            domain={[yMin, yMax]}
            tick={{ fontSize: 11 }}
            width={40}
          />
          <Tooltip
            formatter={(value: number) => [
              `${value.toFixed(1)}%`,
              "Zona radicular (média ponderada)",
            ]}
            labelFormatter={(label: number) => format(new Date(label), "dd/MM/yyyy HH:mm")}
            contentStyle={{ fontSize: 12 }}
          />

          <Line
            type="monotone"
            dataKey="vwcPct"
            stroke="#1c1917"
            dot={false}
            strokeWidth={2}
            connectNulls={false}
          />
        </LineChart>
      </ResponsiveContainer>

      <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
        <div className="rounded-md border border-rule-soft bg-card px-3 py-2">
          <p className="font-mono text-[9.5px] uppercase tracking-[0.1em] text-ink-3">
            Humidade atual · zona radicular
          </p>
          <p className="mt-0.5 font-mono text-[14px] font-medium text-ink tabular-nums">
            {latest.vwcPct.toFixed(1)}%
          </p>
        </div>
        <div className="rounded-md border border-rule-soft bg-card px-3 py-2">
          <p className="font-mono text-[9.5px] uppercase tracking-[0.1em] text-ink-3">
            Água disponível
          </p>
          <p className="mt-0.5 font-mono text-[14px] font-medium text-olive tabular-nums">
            {latest.availablePct == null ? "—" : `${latest.availablePct.toFixed(1)}%`}
          </p>
        </div>
        <div className="rounded-md border border-rule-soft bg-card px-3 py-2">
          <p className="font-mono text-[9.5px] uppercase tracking-[0.1em] text-ink-3">
            Depleção da sonda
          </p>
          <p className="mt-0.5 font-mono text-[14px] font-medium text-terra tabular-nums">
            {latest.depletionPct == null ? "—" : `${latest.depletionPct.toFixed(1)}%`}
          </p>
        </div>
      </div>

      <div className="flex flex-wrap gap-x-4 gap-y-1 px-1">
        <span className="flex items-center gap-1.5 font-mono text-[10px] text-ink-3">
          <span className="h-2 w-4 shrink-0 rounded-sm bg-[#60a5fa]/50" /> Saturado
        </span>
        <span className="flex items-center gap-1.5 font-mono text-[10px] text-ink-3">
          <span className="h-2 w-4 shrink-0 rounded-sm bg-[#4ade80]/50" /> Entre PMP e CC
        </span>
        <span className="flex items-center gap-1.5 font-mono text-[10px] text-ink-3">
          <span className="h-2 w-4 shrink-0 rounded-sm bg-[#f87171]/50" /> Abaixo do PMP
        </span>
        {fcPct != null && (
          <span className="ml-auto font-mono text-[10px] text-ink-3">
            CC: {fcPct.toFixed(1)}% · PMP: {pwpPct?.toFixed(1) ?? "—"}%
          </span>
        )}
      </div>
    </div>
  );
}
