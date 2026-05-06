"use client";

import { useMemo, useState } from "react";
import { subHours } from "date-fns";
import { useProbeReadings } from "@/hooks/useProbeReadings";
import { useSectorStatus } from "@/hooks/useSectorDetail";
import { ProbeChart } from "@/components/probes/ProbeChart";
import { ProbeSumChart } from "@/components/probes/ProbeSumChart";
import { ReadingsControls } from "@/components/probes/ReadingsControls";
import { AppHeader } from "@/components/ui/AppHeader";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";
import { CROP_LABELS } from "@/lib/cropConfig";
import type { ProbeDetectedEvent } from "@/types";

interface Props {
  params: { farmId: string; sectorId: string; probeId: string };
}

export default function ProbeDetailPage({ params }: Props) {
  const { farmId, sectorId, probeId } = params;
  const [sinceHours, setSinceHours] = useState(72);
  const [interval, setInterval] = useState("");
  const [chartView, setChartView] = useState<"depths" | "sum">("depths");

  const since = useMemo(() => subHours(new Date(), sinceHours).toISOString(), [sinceHours]);

  const { data, loading, error } = useProbeReadings({
    probeId,
    since,
    interval: interval || undefined,
  });

  const { data: sectorStatus } = useSectorStatus(sectorId);
  const cropLabel = CROP_LABELS[sectorStatus?.crop_type ?? ""] ?? sectorStatus?.crop_type ?? "…";
  const sectorLabel = sectorStatus?.sector_name ?? "…";

  return (
    <div className="min-h-screen">
      <AppHeader
        crumbs={[
          { label: "Exploração", href: `/farms/${farmId}` },
          { label: cropLabel, href: `/farms/${farmId}?crop=${sectorStatus?.crop_type ?? ""}` },
          { label: sectorLabel, href: `/farms/${farmId}/sectors/${sectorId}` },
          { label: probeId },
        ]}
      />

      <main className="mx-auto max-w-4xl space-y-5 px-4 py-6 sm:px-6 animate-fade-in-up">
        <div>
          <h1 className="text-xl font-bold text-slate-900">
            Leituras da sonda
          </h1>
          <p className="mt-0.5 font-mono text-xs text-slate-400">{probeId}</p>
        </div>

        <Card>
          <CardHeader>
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <CardTitle>Humidade do solo (VWC)</CardTitle>
              <ReadingsControls
                sinceHours={sinceHours}
                interval={interval}
                view={chartView}
                onSinceChange={setSinceHours}
                onIntervalChange={setInterval}
                onViewChange={setChartView}
              />
            </div>
          </CardHeader>
          <CardBody>
            {loading ? (
              <div className="h-80 animate-pulse rounded-2xl bg-slate-100" />
            ) : error ? (
              <div className="rounded-2xl border border-red-200 bg-red-50 px-4 py-5 text-center text-sm text-red-700">
                {error}
              </div>
            ) : data ? (
              chartView === "depths" ? (
                <ProbeChart
                  depths={data.depths}
                  referenceLines={data.reference_lines}
                  events={data.events ?? []}
                  interval={interval}
                />
              ) : (
                <ProbeSumChart
                  depths={data.depths}
                  referenceLines={data.reference_lines}
                  events={data.events ?? []}
                />
              )
            ) : (
              <div className="rounded-2xl border border-dashed border-slate-300 bg-slate-50 px-4 py-8 text-center text-sm text-slate-500">
                Sem leituras disponíveis para o intervalo seleccionado.
              </div>
            )}
          </CardBody>
        </Card>

        {data && data.depths.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle>Rega / chuva detectada</CardTitle>
            </CardHeader>
            <CardBody>
              <DetectedEvents events={data.events ?? []} />
            </CardBody>
          </Card>
        )}

        {/* Depth summary table */}
        {data && data.depths.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle>Resumo por profundidade</CardTitle>
            </CardHeader>
            <CardBody className="p-0">
              <div className="overflow-x-auto">
                <table className="min-w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-100">
                      <th className="px-5 pb-3 pt-4 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
                        Profundidade
                      </th>
                      <th className="px-5 pb-3 pt-4 text-right text-xs font-semibold uppercase tracking-wide text-slate-500">
                        Leituras
                      </th>
                      <th className="px-5 pb-3 pt-4 text-right text-xs font-semibold uppercase tracking-wide text-slate-500">
                        Última VWC
                      </th>
                      <th className="px-5 pb-3 pt-4 text-right text-xs font-semibold uppercase tracking-wide text-slate-500">
                        Mín / Máx
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-50">
                    {data.depths.map((d) => {
                      const vwcs = d.readings.map((r) => r.vwc);
                      const last = vwcs[vwcs.length - 1];
                      const min = Math.min(...vwcs);
                      const max = Math.max(...vwcs);
                      return (
                        <tr key={d.depth_cm} className="hover:bg-slate-50">
                          <td className="whitespace-nowrap px-5 py-3 font-semibold text-slate-700">
                            {d.depth_cm} cm
                          </td>
                          <td className="whitespace-nowrap px-5 py-3 text-right tabular-nums text-slate-500">
                            {d.readings.length}
                          </td>
                          <td className="whitespace-nowrap px-5 py-3 text-right tabular-nums font-medium text-slate-800">
                            {last != null ? `${(last * 100).toFixed(1)}%` : "—"}
                          </td>
                          <td className="whitespace-nowrap px-5 py-3 text-right tabular-nums text-slate-500">
                            {vwcs.length > 0
                              ? `${(min * 100).toFixed(1)}% / ${(max * 100).toFixed(1)}%`
                              : "—"}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </CardBody>
          </Card>
        )}
      </main>
    </div>
  );
}

function DetectedEvents({ events }: { events: ProbeDetectedEvent[] }) {
  if (events.length === 0) {
    return (
      <p className="text-[12.5px] text-ink-3">
        Sem aumentos rápidos de humidade no período seleccionado.
      </p>
    );
  }

  return (
    <ul className="divide-y divide-rule-soft">
      {events.map((event) => (
        <li key={event.id} className="py-3 first:pt-0 last:pb-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className={`rounded-full px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.08em] ${event.kind === "rain" ? "bg-[#0284c7]/10 text-[#0284c7]" : event.kind === "irrigation" ? "bg-olive/10 text-olive" : "bg-[#c9a34a]/10 text-[#c9a34a]"}`}>
              {event.kind === "rain" ? "Chuva" : event.kind === "irrigation" ? "Rega" : "Sem registo"}
            </span>
            <span className="font-mono text-[11px] text-ink-3">
              {new Date(event.timestamp).toLocaleString("pt-PT", {
                day: "2-digit",
                month: "2-digit",
                hour: "2-digit",
                minute: "2-digit",
              })}
            </span>
            <span className="font-mono text-[11px] text-ink-3">conf. {event.confidence}</span>
          </div>
          <p className="mt-1 text-[12.5px] leading-relaxed text-ink-2">
            {event.message} Prof.: {event.depths_cm.join(", ")} cm; aumento soma {(event.delta_vwc * 100).toFixed(1)}%.
            {event.rainfall_mm != null ? ` Chuva: ${event.rainfall_mm.toFixed(1)} mm.` : ""}
            {event.irrigation_mm != null ? ` Rega: ${event.irrigation_mm.toFixed(1)} mm.` : ""}
          </p>
        </li>
      ))}
    </ul>
  );
}
