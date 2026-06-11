"use client";

import { useEffect, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { flowmeterApi } from "@/lib/api";
import { FlowmeterSectorAIAnalysis } from "./FlowmeterSectorAIAnalysis";
import type {
  FlowmeterReadingPoint,
  FlowmeterReferenceOut,
  IrrigationEventOut,
} from "@/types";

interface Props {
  sectorId: string;
  period: "7d" | "30d" | "season";
}

type ResolvedInterval = "15m" | "1h" | "1d";

function fmtTick(iso: string, interval: ResolvedInterval) {
  const d = new Date(iso);
  if (interval === "15m") {
    // dd/MM HH:mm — recharts will skip most ticks automatically when dense
    return d.toLocaleString("pt-PT", {
      day: "2-digit",
      month: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  }
  return d.toLocaleDateString("pt-PT", { day: "2-digit", month: "2-digit" });
}

function fmtTooltipLabel(iso: string, interval: ResolvedInterval) {
  const d = new Date(iso);
  if (interval === "15m") {
    return d.toLocaleString("pt-PT", {
      day: "2-digit",
      month: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  }
  if (interval === "1h") {
    return d.toLocaleString("pt-PT", { day: "2-digit", month: "2-digit", hour: "2-digit" });
  }
  return d.toLocaleDateString("pt-PT", { day: "2-digit", month: "2-digit" });
}

function fmtDuration(minutes: number) {
  const h = Math.floor(minutes / 60);
  const m = Math.round(minutes % 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

function fmtEventDate(iso: string) {
  return new Date(iso).toLocaleDateString("pt-PT", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function periodToSinceUntil(period: "7d" | "30d" | "season"): { since: string; until: string } {
  const until = new Date();
  const since = new Date(until);
  if (period === "7d") {
    since.setDate(since.getDate() - 7);
  } else if (period === "30d") {
    since.setDate(since.getDate() - 30);
  } else {
    since.setDate(since.getDate() - 90);
  }
  return { since: since.toISOString(), until: until.toISOString() };
}

function intervalLabel(interval: ResolvedInterval) {
  if (interval === "15m") return "por 15 min";
  if (interval === "1h") return "por hora";
  return "por dia";
}

export function FlowmeterSectorDetail({ sectorId, period }: Props) {
  const [readings, setReadings] = useState<FlowmeterReadingPoint[]>([]);
  const [events, setEvents] = useState<IrrigationEventOut[]>([]);
  const [resolvedInterval, setResolvedInterval] = useState<ResolvedInterval>("1h");
  const [loading, setLoading] = useState(true);
  const [reference, setReference] = useState<FlowmeterReferenceOut | null>(null);

  useEffect(() => {
    setLoading(true);
    const { since, until } = periodToSinceUntil(period);

    async function load() {
      // Start events + reference fetch immediately — independent of interval resolution.
      const eventsPromise = flowmeterApi.events(sectorId, { since, until });
      const referencePromise = flowmeterApi.getReference(sectorId).catch(() => null);

      let readingsResult;
      if (period === "7d") {
        // Prefer 15-min readings; fall back to hourly when the flowmeter only reports hourly.
        const r15 = await flowmeterApi.readings(sectorId, { interval: "15m", since, until });
        if (r15.readings.length > 0) {
          setResolvedInterval("15m");
          readingsResult = r15;
        } else {
          const r1h = await flowmeterApi.readings(sectorId, { interval: "1h", since, until });
          setResolvedInterval("1h");
          readingsResult = r1h;
        }
      } else {
        setResolvedInterval("1d");
        readingsResult = await flowmeterApi.readings(sectorId, { interval: "1d", since, until });
      }

      const [eventsResult, refResult] = await Promise.all([eventsPromise, referencePromise]);
      setReadings(readingsResult.readings);
      setEvents(eventsResult.events);
      setReference(refResult);
    }

    load().catch(console.error).finally(() => setLoading(false));
  }, [sectorId, period]);

  if (loading) {
    return <div className="px-6 py-4 text-sm text-ink-3">A carregar...</div>;
  }

  const chartData = readings.map((r) => ({
    ts: r.timestamp,
    label: fmtTick(r.timestamp, resolvedInterval),
    value: r.value,
  }));

  return (
    <div className="px-6 py-4 bg-surface-subtle border-t border-rule-soft space-y-4">
      <div>
        <p className="text-xs font-semibold text-ink-3 uppercase tracking-wide mb-2">
          Consumo m³/ha — {intervalLabel(resolvedInterval)}
        </p>
        <ResponsiveContainer width="100%" height={120}>
          <BarChart data={chartData} margin={{ top: 0, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e5e3de" vertical={false} />
            <XAxis dataKey="label" tick={{ fontSize: 10 }} />
            <YAxis tick={{ fontSize: 10 }} width={32} />
            <Tooltip
              labelFormatter={(label, payload) => {
                const ts = payload?.[0]?.payload?.ts;
                return ts ? fmtTooltipLabel(ts, resolvedInterval) : label;
              }}
              formatter={(v: number) => [`${v.toFixed(2)} m³/ha`, "Consumo"]}
            />
            <Bar dataKey="value" fill="#6b9e3a" radius={[2, 2, 0, 0]} maxBarSize={24} />
            {reference && reference.reference_rate_m3_ha !== null && (
              <>
                <ReferenceArea
                  y1={reference.lower_limit_m3_ha ?? undefined}
                  y2={reference.upper_limit_m3_ha ?? undefined}
                  fill="#4a8c4a"
                  fillOpacity={0.07}
                />
                <ReferenceLine
                  y={reference.upper_limit_m3_ha ?? undefined}
                  stroke="#4a8c4a"
                  strokeDasharray="4 3"
                  strokeWidth={1}
                  label={{
                    value: `+${reference.tolerance_pct}%`,
                    position: "insideTopRight",
                    fontSize: 9,
                    fill: "#4a8c4a",
                  }}
                />
                <ReferenceLine
                  y={reference.lower_limit_m3_ha ?? undefined}
                  stroke="#4a8c4a"
                  strokeDasharray="4 3"
                  strokeWidth={1}
                  label={{
                    value: `-${reference.tolerance_pct}%`,
                    position: "insideBottomRight",
                    fontSize: 9,
                    fill: "#4a8c4a",
                  }}
                />
                <ReferenceLine
                  y={reference.reference_rate_m3_ha}
                  stroke="#4a8c4a"
                  strokeWidth={1.5}
                  strokeOpacity={0.6}
                  label={{
                    value: `Ref: ${reference.reference_rate_m3_ha.toFixed(2)} m³/ha`,
                    position: "insideTopLeft",
                    fontSize: 9,
                    fill: "#4a8c4a",
                  }}
                />
              </>
            )}
          </BarChart>
        </ResponsiveContainer>
      </div>

      {events.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-ink-3 uppercase tracking-wide mb-2">
            Eventos detectados
          </p>
          <div className="grid grid-cols-4 gap-2 text-xs text-ink-3 font-semibold uppercase tracking-wide mb-1">
            <span>Início</span>
            <span>Duração</span>
            <span>Dotação</span>
            <span>Pico</span>
          </div>
          {events.slice(0, 10).map((ev) => (
            <div key={ev.id} className="grid grid-cols-4 gap-2 text-sm text-ink-2 py-1 border-t border-rule-soft">
              <span>{fmtEventDate(ev.start_time)}</span>
              <span>{fmtDuration(ev.duration_minutes)}</span>
              <span className="font-semibold">{ev.total_m3_ha.toFixed(1)} m³/ha</span>
              <span className="text-ink-3">—</span>
            </div>
          ))}
        </div>
      )}

      {/* AI analysis for this sector */}
      <FlowmeterSectorAIAnalysis sectorId={sectorId} period={period} />
    </div>
  );
}
