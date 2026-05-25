"use client";

import { useEffect, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { flowmeterApi } from "@/lib/api";
import { FlowmeterSectorAIAnalysis } from "./FlowmeterSectorAIAnalysis";
import type {
  FlowmeterReadingPoint,
  IrrigationEventOut,
} from "@/types";

interface Props {
  sectorId: string;
  period: "7d" | "30d" | "season";
}

function fmtDate(iso: string) {
  return new Date(iso).toLocaleDateString("pt-PT", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function fmtDuration(minutes: number) {
  const h = Math.floor(minutes / 60);
  const m = Math.round(minutes % 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

function periodToSinceUntil(period: "7d" | "30d" | "season"): { since: string; until: string } {
  const until = new Date();
  const since = new Date(until);
  if (period === "7d") {
    since.setDate(since.getDate() - 7);
  } else if (period === "30d") {
    since.setDate(since.getDate() - 30);
  } else {
    // season: 90 days, matching backend default
    since.setDate(since.getDate() - 90);
  }
  return {
    since: since.toISOString(),
    until: until.toISOString(),
  };
}

export function FlowmeterSectorDetail({ sectorId, period }: Props) {
  const [readings, setReadings] = useState<FlowmeterReadingPoint[]>([]);
  const [events, setEvents] = useState<IrrigationEventOut[]>([]);
  const [loading, setLoading] = useState(true);

  const interval = period === "7d" ? "1h" : "1d";

  useEffect(() => {
    setLoading(true);
    const { since, until } = periodToSinceUntil(period);
    Promise.all([
      flowmeterApi.readings(sectorId, { interval, since, until }),
      flowmeterApi.events(sectorId, { since, until }),
    ])
      .then(([r, e]) => {
        setReadings(r.readings);
        setEvents(e.events);
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [sectorId, period, interval]);

  if (loading) {
    return <div className="px-6 py-4 text-sm text-ink-3">A carregar...</div>;
  }

  const chartData = readings.map((r) => ({
    ts: new Date(r.timestamp).toLocaleDateString("pt-PT", {
      day: "2-digit",
      month: "2-digit",
    }),
    value: r.value,
  }));

  return (
    <div className="px-6 py-4 bg-surface-subtle border-t border-rule-soft space-y-4">
      <div>
        <p className="text-xs font-semibold text-ink-3 uppercase tracking-wide mb-2">
          Consumo m³/ha — {interval === "1h" ? "por hora" : "por dia"}
        </p>
        <ResponsiveContainer width="100%" height={120}>
          <BarChart data={chartData} margin={{ top: 0, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e5e3de" vertical={false} />
            <XAxis dataKey="ts" tick={{ fontSize: 10 }} />
            <YAxis tick={{ fontSize: 10 }} width={32} />
            <Tooltip
              formatter={(v: number) => [`${v.toFixed(2)} m³/ha`, "Consumo"]}
            />
            <Bar dataKey="value" fill="#6b9e3a" radius={[2, 2, 0, 0]} maxBarSize={24} />
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
              <span>{fmtDate(ev.start_time)}</span>
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
