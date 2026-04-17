"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { subHours } from "date-fns";
import { ChevronDown, ExternalLink } from "lucide-react";
import { useProbeReadings } from "@/hooks/useProbeReadings";
import { ProbeChart } from "@/components/probes/ProbeChart";
import { ReadingsControls } from "@/components/probes/ReadingsControls";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { sectorsApi } from "@/lib/api";
import type { ReferenceLines } from "@/types";

interface ProbeReadingsInlineProps {
  probeId: string;
  externalId: string;
  healthStatus?: string | null;
  lastReadingAt?: string | null;
  href: string;
  sectorId: string;
}

export function ProbeReadingsInline({
  probeId,
  externalId,
  healthStatus,
  lastReadingAt,
  href,
  sectorId,
}: ProbeReadingsInlineProps) {
  const [collapsed, setCollapsed] = useState(true);
  const [sinceHours, setSinceHours] = useState(72);
  const [interval, setInterval] = useState("");

  // Local override of reference lines so chart updates immediately on save
  const [refLines, setRefLines] = useState<ReferenceLines | null>(null);

  // CC/PMP edit state
  const [editing, setEditing] = useState(false);
  const [ccInput, setCcInput] = useState("");
  const [pmpInput, setPmpInput] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const since = useMemo(() => subHours(new Date(), sinceHours).toISOString(), [sinceHours]);

  const { data, loading, error } = useProbeReadings({
    probeId,
    since,
    interval: interval || undefined,
  });

  const activeRefLines = refLines ?? data?.reference_lines ?? { field_capacity: null, wilting_point: null };

  function startEdit() {
    setCcInput(activeRefLines.field_capacity != null ? (activeRefLines.field_capacity * 100).toFixed(1) : "");
    setPmpInput(activeRefLines.wilting_point != null ? (activeRefLines.wilting_point * 100).toFixed(1) : "");
    setSaved(false);
    setEditing(true);
  }

  async function handleSave() {
    const cc = parseFloat(ccInput);
    const pmp = parseFloat(pmpInput);
    if (isNaN(cc) || isNaN(pmp) || cc <= 0 || pmp <= 0 || pmp >= cc) return;
    setSaving(true);
    try {
      await sectorsApi.updateCropProfile(sectorId, {
        field_capacity: cc / 100,
        wilting_point: pmp / 100,
      });
      setRefLines({ field_capacity: cc / 100, wilting_point: pmp / 100 });
      setSaved(true);
      setEditing(false);
      setTimeout(() => setSaved(false), 2500);
    } finally {
      setSaving(false);
    }
  }

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
              referenceLines={activeRefLines}
              interval={interval}
            />

            {/* CC / PMP row */}
            <div className="flex flex-wrap items-center gap-3 rounded-xl border border-black/[0.07] bg-irrigai-surface px-4 py-3">
              {editing ? (
                <>
                  <div className="flex items-center gap-1.5">
                    <label className="text-[11px] font-medium text-[#16a34a] min-w-[28px]">CC</label>
                    <input
                      type="number"
                      value={ccInput}
                      onChange={(e) => setCcInput(e.target.value)}
                      step="0.1"
                      min="0"
                      max="100"
                      className="w-20 rounded-lg border border-black/[0.1] bg-white px-2.5 py-1.5 text-[13px] tabular-nums focus:border-irrigai-green focus:outline-none focus:ring-1 focus:ring-irrigai-green/30"
                    />
                    <span className="text-[11px] text-irrigai-text-muted">%</span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <label className="text-[11px] font-medium text-[#dc2626] min-w-[36px]">PMP</label>
                    <input
                      type="number"
                      value={pmpInput}
                      onChange={(e) => setPmpInput(e.target.value)}
                      step="0.1"
                      min="0"
                      max="100"
                      className="w-20 rounded-lg border border-black/[0.1] bg-white px-2.5 py-1.5 text-[13px] tabular-nums focus:border-irrigai-green focus:outline-none focus:ring-1 focus:ring-irrigai-green/30"
                    />
                    <span className="text-[11px] text-irrigai-text-muted">%</span>
                  </div>
                  <div className="flex items-center gap-2 ml-auto">
                    <Button size="sm" variant="secondary" onClick={() => setEditing(false)}>
                      Cancelar
                    </Button>
                    <Button size="sm" variant="brand" onClick={handleSave} loading={saving}>
                      Guardar
                    </Button>
                  </div>
                </>
              ) : (
                <>
                  <span className="text-[11px] font-medium text-[#16a34a]">
                    CC {activeRefLines.field_capacity != null ? `${(activeRefLines.field_capacity * 100).toFixed(1)}%` : "—"}
                  </span>
                  <span className="text-[11px] font-medium text-[#dc2626]">
                    PMP {activeRefLines.wilting_point != null ? `${(activeRefLines.wilting_point * 100).toFixed(1)}%` : "—"}
                  </span>
                  {saved && (
                    <span className="text-[11px] font-medium text-irrigai-green">Guardado ✓</span>
                  )}
                  <button
                    onClick={startEdit}
                    className="ml-auto text-[11px] text-irrigai-text-muted hover:text-irrigai-text transition-colors"
                  >
                    Editar
                  </button>
                </>
              )}
            </div>

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
