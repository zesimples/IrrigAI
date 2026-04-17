"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { subHours } from "date-fns";
import { ChevronDown, ExternalLink } from "lucide-react";
import { useProbeReadings } from "@/hooks/useProbeReadings";
import { ProbeChart } from "@/components/probes/ProbeChart";
import { ReadingsControls } from "@/components/probes/ReadingsControls";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";

interface ProbeReadingsInlineProps {
  probeId: string;
  externalId: string;
  healthStatus?: string | null;
  lastReadingAt?: string | null;
  href: string;
}

export function ProbeReadingsInline({
  probeId,
  externalId,
  healthStatus,
  lastReadingAt,
  href,
}: ProbeReadingsInlineProps) {
  const [collapsed, setCollapsed] = useState(true);
  const [sinceHours, setSinceHours] = useState(72);
  const [interval, setInterval] = useState("");

  const since = useMemo(() => subHours(new Date(), sinceHours).toISOString(), [sinceHours]);

  const { data, loading, error } = useProbeReadings({
    probeId,
    since,
    interval: interval || undefined,
  });

  const healthDot =
    healthStatus === "ok"
      ? "bg-irrigai-green"
      : healthStatus === "degraded" || healthStatus === "warning"
        ? "bg-irrigai-amber"
        : "bg-irrigai-red";

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-3">
          <button
            onClick={() => setCollapsed((c) => !c)}
            className="flex items-center gap-2 min-w-0 flex-1 text-left"
          >
            <span className={`shrink-0 inline-block h-1.5 w-1.5 rounded-full ${healthDot}`} />
            <CardTitle className="font-mono">{externalId}</CardTitle>
            {lastReadingAt && (
              <span className="text-[11px] text-irrigai-text-muted truncate">
                · {new Date(lastReadingAt).toLocaleString("pt-PT", {
                  day: "numeric",
                  month: "short",
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </span>
            )}
            <ChevronDown
              className={`shrink-0 h-3.5 w-3.5 text-irrigai-text-hint transition-transform duration-200 ${collapsed ? "-rotate-90" : ""}`}
            />
          </button>
          <Link
            href={href}
            className="shrink-0 flex items-center gap-1 text-[11px] text-irrigai-text-muted hover:text-irrigai-text transition-colors"
          >
            <ExternalLink className="h-3 w-3" />
            <span className="hidden sm:inline">Ver histórico</span>
          </Link>
        </div>
      </CardHeader>

      {!collapsed && <CardBody className="space-y-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <p className="text-[12px] font-medium text-irrigai-text-hint uppercase tracking-[0.05em]">
            Humidade do solo (VWC)
          </p>
          <ReadingsControls
            sinceHours={sinceHours}
            interval={interval}
            onSinceChange={setSinceHours}
            onIntervalChange={setInterval}
          />
        </div>

        {loading ? (
          <div className="h-64 animate-pulse rounded-xl bg-irrigai-surface" />
        ) : error ? (
          <div className="rounded-xl border border-irrigai-red/20 bg-irrigai-red-bg px-4 py-4 text-center text-[13px] text-irrigai-red-dark">
            {error}
          </div>
        ) : data && data.depths.length > 0 ? (
          <>
            <ProbeChart
              depths={data.depths}
              referenceLines={data.reference_lines}
              interval={interval}
            />

            {/* Depth summary */}
            <div className="overflow-x-auto rounded-xl border border-black/[0.07]">
              <table className="min-w-full text-sm">
                <thead>
                  <tr className="border-b border-black/[0.06]">
                    <th className="px-4 pb-2.5 pt-3 text-left text-[11px] font-medium uppercase tracking-[0.05em] text-irrigai-text-hint">
                      Profundidade
                    </th>
                    <th className="px-4 pb-2.5 pt-3 text-right text-[11px] font-medium uppercase tracking-[0.05em] text-irrigai-text-hint">
                      Última VWC
                    </th>
                    <th className="px-4 pb-2.5 pt-3 text-right text-[11px] font-medium uppercase tracking-[0.05em] text-irrigai-text-hint">
                      Mín / Máx
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-black/[0.04]">
                  {data.depths.map((d) => {
                    const vwcs = d.readings.map((r) => r.vwc);
                    const last = vwcs[vwcs.length - 1];
                    const min = Math.min(...vwcs);
                    const max = Math.max(...vwcs);
                    return (
                      <tr key={d.depth_cm}>
                        <td className="whitespace-nowrap px-4 py-2.5 font-medium text-[13px] text-irrigai-text">
                          {d.depth_cm} cm
                        </td>
                        <td className="whitespace-nowrap px-4 py-2.5 text-right tabular-nums text-[13px] text-irrigai-text">
                          {last != null ? `${(last * 100).toFixed(1)}%` : "—"}
                        </td>
                        <td className="whitespace-nowrap px-4 py-2.5 text-right tabular-nums text-[13px] text-irrigai-text-muted">
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
          </>
        ) : (
          <div className="rounded-xl border border-dashed border-black/[0.08] bg-irrigai-surface px-4 py-8 text-center">
            <p className="text-[13px] text-irrigai-text-muted">
              Sem leituras para o intervalo seleccionado.
            </p>
          </div>
        )}
      </CardBody>}
    </Card>
  );
}
