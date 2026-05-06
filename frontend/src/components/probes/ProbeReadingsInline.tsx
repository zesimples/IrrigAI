"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { subHours } from "date-fns";
import { ChevronDown, ExternalLink, ScanLine, RefreshCw } from "lucide-react";
import { useProbeReadings } from "@/hooks/useProbeReadings";
import { ProbeChart } from "@/components/probes/ProbeChart";
import { ProbeSumChart } from "@/components/probes/ProbeSumChart";
import { ReadingsControls } from "@/components/probes/ReadingsControls";
import { sectorsApi, probesApi } from "@/lib/api";
import type { ProbeDetectedEvent, ReferenceLines } from "@/types";

interface ProbeReadingsInlineProps {
  probeId: string;
  externalId: string;
  healthStatus?: string | null;
  lastReadingAt?: string | null;
  href: string;
  sectorId: string;
  onSaved?: () => void | Promise<void>;
  /** Increment this value to force the card open from outside. */
  openTrigger?: number;
}

export function ProbeReadingsInline({
  probeId,
  externalId,
  healthStatus,
  lastReadingAt,
  href,
  sectorId,
  onSaved,
  openTrigger,
}: ProbeReadingsInlineProps) {
  const [collapsed, setCollapsed] = useState(true);

  useEffect(() => {
    if (openTrigger && openTrigger > 0) setCollapsed(false);
  }, [openTrigger]);
  const [sinceHours, setSinceHours] = useState(72);
  const [interval, setInterval] = useState("");
  const [interpretation, setInterpretation] = useState<string | null>(null);
  const [interpreting, setInterpreting] = useState(false);
  const [interpretError, setInterpretError] = useState<string | null>(null);

  const [refLines, setRefLines] = useState<ReferenceLines | null>(null);

  const [chartView, setChartView] = useState<"depths" | "sum">("depths");
  const [hoveredEventId, setHoveredEventId] = useState<string | null>(null);

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

  const nDepths = data?.depths.length ?? 1;
  const editScale = chartView === "sum" ? nDepths : 1;

  function startEdit() {
    const fc = activeRefLines.field_capacity;
    const wp = activeRefLines.wilting_point;
    setCcInput(fc != null ? (fc * 100 * editScale).toFixed(1) : "");
    setPmpInput(wp != null ? (wp * 100 * editScale).toFixed(1) : "");
    setSaved(false);
    setEditing(true);
  }

  async function handleSave() {
    const cc = parseFloat(ccInput);
    const pmp = parseFloat(pmpInput);
    if (isNaN(cc) || isNaN(pmp) || cc <= 0 || pmp <= 0 || pmp >= cc) return;
    setSaving(true);
    try {
      const fcPerDepth = cc / 100 / editScale;
      const wpPerDepth = pmp / 100 / editScale;
      await sectorsApi.updateCropProfile(sectorId, {
        field_capacity: fcPerDepth,
        wilting_point: wpPerDepth,
      });
      setRefLines({ field_capacity: fcPerDepth, wilting_point: wpPerDepth });
      setSaved(true);
      setEditing(false);
      setTimeout(() => setSaved(false), 2500);
      await onSaved?.();
    } finally {
      setSaving(false);
    }
  }

  async function runInterpretation() {
    setInterpreting(true);
    setInterpretError(null);
    try {
      const res = await probesApi.interpret(probeId);
      setInterpretation(res.interpretation);
    } catch (e) {
      setInterpretError(e instanceof Error ? e.message : "Erro ao interpretar sonda.");
    } finally {
      setInterpreting(false);
    }
  }

  const healthDot =
    healthStatus === "ok"
      ? "bg-olive"
      : healthStatus === "degraded" || healthStatus === "warning"
        ? "bg-[#c9a34a]"
        : "bg-terra";

  return (
    <div className="border border-rule-soft rounded-lg overflow-hidden mb-5">
      {/* Header row */}
      <div className="bg-card border-b border-rule-soft px-5 pt-3 pb-3.5">
        <p className="font-mono text-[9.5px] tracking-[0.14em] uppercase text-ink-3 mb-2">
          Leituras da sonda
        </p>
        <div className="flex items-center justify-between gap-3">
          <button
            onClick={() => setCollapsed((c) => !c)}
            className="flex items-center gap-2.5 min-w-0 flex-1 text-left"
          >
            <span className={`shrink-0 h-[7px] w-[7px] rounded-full ${healthDot}`} />
            <span className="font-mono text-[13px] font-medium text-ink">{externalId}</span>
            {lastReadingAt && (
              <span className="font-mono text-[11px] text-ink-3 truncate">
                · {new Date(lastReadingAt).toLocaleString("pt-PT", {
                  day: "numeric",
                  month: "short",
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </span>
            )}
            <ChevronDown
              className={`shrink-0 h-3.5 w-3.5 text-ink-3 transition-transform duration-200 ml-0.5 ${collapsed ? "-rotate-90" : ""}`}
            />
          </button>
          <Link
            href={href}
            className="shrink-0 flex items-center gap-1.5 font-serif italic text-[11.5px] text-ink-2 hover:text-ink transition-colors"
          >
            <ExternalLink className="h-3 w-3" />
            <span className="hidden sm:inline">Ver histórico</span>
          </Link>
        </div>
      </div>

      {!collapsed && (
        <div className="px-5 py-4 space-y-4 bg-paper">
          {/* Controls row */}
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <span className="font-mono text-[10px] tracking-[0.1em] uppercase text-ink-3">
              Humidade do solo (VWC)
            </span>
            <ReadingsControls
              sinceHours={sinceHours}
              interval={interval}
              view={chartView}
              onSinceChange={setSinceHours}
              onIntervalChange={setInterval}
              onViewChange={setChartView}
            />
          </div>

          {loading ? (
            <div className="h-64 animate-pulse rounded-lg bg-card" />
          ) : error ? (
            <div className="rounded-lg border border-terra/20 bg-terra-bg px-4 py-4 text-center text-[13px] text-terra">
              {error}
            </div>
          ) : data && data.depths.length > 0 ? (
            <>
              {chartView === "depths" ? (
                <ProbeChart
                  depths={data.depths}
                  referenceLines={activeRefLines}
                  events={data.events ?? []}
                  hoveredEventId={hoveredEventId}
                  interval={interval}
                />
              ) : (
                <ProbeSumChart
                  depths={data.depths}
                  referenceLines={activeRefLines}
                  events={data.events ?? []}
                  hoveredEventId={hoveredEventId}
                />
              )}

              <DetectedEvents
                events={data.events ?? []}
                hoveredEventId={hoveredEventId}
                onHover={setHoveredEventId}
              />

              {/* CC / PMP row */}
              <div className="flex flex-wrap items-center gap-3 rounded-md border border-rule-soft bg-card px-4 py-3">
                {editing ? (
                  <>
                    <div className="flex items-center gap-1.5">
                      <label className="font-mono text-[11px] font-medium text-olive min-w-[28px]">CC</label>
                      <input
                        type="number"
                        value={ccInput}
                        onChange={(e) => setCcInput(e.target.value)}
                        step="0.1"
                        min="0"
                        max={100 * editScale}
                        className="w-20 rounded-md border border-rule bg-paper px-2.5 py-1.5 text-[13px] text-ink tabular-nums focus:outline-none focus:ring-1 focus:ring-olive/30"
                      />
                      <span className="font-mono text-[11px] text-ink-3">
                        {chartView === "sum" ? "% soma" : "%"}
                      </span>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <label className="font-mono text-[11px] font-medium text-terra min-w-[36px]">PMP</label>
                      <input
                        type="number"
                        value={pmpInput}
                        onChange={(e) => setPmpInput(e.target.value)}
                        step="0.1"
                        min="0"
                        max={100 * editScale}
                        className="w-20 rounded-md border border-rule bg-paper px-2.5 py-1.5 text-[13px] text-ink tabular-nums focus:outline-none focus:ring-1 focus:ring-terra/30"
                      />
                      <span className="font-mono text-[11px] text-ink-3">
                        {chartView === "sum" ? "% soma" : "%"}
                      </span>
                    </div>
                    <div className="flex items-center gap-2 ml-auto">
                      <button
                        type="button"
                        onClick={() => setEditing(false)}
                        className="rounded-md border border-rule bg-paper px-3 py-1.5 text-[12px] text-ink-2 hover:bg-paper-in transition-colors"
                      >
                        Cancelar
                      </button>
                      <button
                        type="button"
                        onClick={handleSave}
                        disabled={saving}
                        className="rounded-md bg-ink text-paper px-3 py-1.5 text-[12px] font-medium hover:opacity-85 disabled:opacity-40 transition-opacity"
                      >
                        {saving ? "A guardar…" : "Guardar"}
                      </button>
                    </div>
                  </>
                ) : (
                  <>
                    {chartView === "depths" ? (
                      <>
                        <span className="font-mono text-[11.5px] font-medium text-olive">
                          CC {activeRefLines.field_capacity != null ? `${(activeRefLines.field_capacity * 100).toFixed(1)}%` : "—"}
                        </span>
                        <span className="font-mono text-[11.5px] font-medium text-terra">
                          PMP {activeRefLines.wilting_point != null ? `${(activeRefLines.wilting_point * 100).toFixed(1)}%` : "—"}
                        </span>
                      </>
                    ) : (
                      <>
                        <span className="font-mono text-[11.5px] font-medium text-olive">
                          CC soma{" "}
                          {activeRefLines.field_capacity != null
                            ? `${(activeRefLines.field_capacity * 100 * data.depths.length).toFixed(1)}%`
                            : "—"}
                        </span>
                        <span className="font-mono text-[11.5px] font-medium text-terra">
                          PMP soma{" "}
                          {activeRefLines.wilting_point != null
                            ? `${(activeRefLines.wilting_point * 100 * data.depths.length).toFixed(1)}%`
                            : "—"}
                        </span>
                        <span className="font-mono text-[10px] text-ink-3">
                          ×{data.depths.length} profundidades
                        </span>
                      </>
                    )}
                    {saved && (
                      <span className="font-mono text-[11px] text-olive">Guardado ✓</span>
                    )}
                    <button
                      onClick={startEdit}
                      className="ml-auto font-serif italic text-[11.5px] text-ink-2 hover:text-ink transition-colors"
                    >
                      Editar
                    </button>
                  </>
                )}
              </div>

              {/* Depth summary table */}
              <div className="overflow-x-auto rounded-md border border-rule-soft">
                <table className="min-w-full">
                  <thead>
                    <tr className="border-b border-rule-soft bg-card">
                      <th className="px-4 pb-2.5 pt-3 text-left font-mono text-[10px] tracking-[0.1em] uppercase text-ink-3">
                        Profundidade
                      </th>
                      <th className="px-4 pb-2.5 pt-3 text-right font-mono text-[10px] tracking-[0.1em] uppercase text-ink-3">
                        Última VWC
                      </th>
                      <th className="px-4 pb-2.5 pt-3 text-right font-mono text-[10px] tracking-[0.1em] uppercase text-ink-3">
                        Mín / Máx
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-rule-soft">
                    {data.depths.map((d) => {
                      const vwcs = d.readings.map((r) => r.vwc);
                      const last = vwcs[vwcs.length - 1];
                      const min = Math.min(...vwcs);
                      const max = Math.max(...vwcs);
                      return (
                        <tr key={d.depth_cm}>
                          <td className="whitespace-nowrap px-4 py-2.5 font-mono text-[13px] font-medium text-ink">
                            {d.depth_cm} cm
                          </td>
                          <td className="whitespace-nowrap px-4 py-2.5 text-right font-mono tabular-nums text-[13px] text-ink">
                            {last != null ? `${(last * 100).toFixed(1)}%` : "—"}
                          </td>
                          <td className="whitespace-nowrap px-4 py-2.5 text-right font-mono tabular-nums text-[13px] text-ink-2">
                            {vwcs.length > 0 ? `${(min * 100).toFixed(1)}% / ${(max * 100).toFixed(1)}%` : "—"}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </>
          ) : (
            <div className="rounded-lg border border-dashed border-rule px-4 py-8 text-center">
              <p className="text-[13px] text-ink-3">
                Sem leituras para o intervalo seleccionado.
              </p>
            </div>
          )}

          {/* AI Pattern Interpretation */}
          {data && data.depths.length > 0 && (
            <div className="rounded-md border border-rule-soft overflow-hidden">
              <div className="flex items-center justify-between gap-3 px-4 py-2.5 bg-card border-b border-rule-soft">
                <div className="flex items-center gap-2">
                  <ScanLine className="h-3.5 w-3.5 text-ink-3" />
                  <span className="font-mono text-[10px] tracking-[0.1em] uppercase text-ink-3">
                    Interpretação de padrões
                  </span>
                </div>
                <button
                  type="button"
                  onClick={runInterpretation}
                  disabled={interpreting}
                  className="inline-flex items-center gap-1.5 rounded-md border border-rule bg-paper px-3 py-1.5 text-[11.5px] text-ink-2 hover:bg-paper-in disabled:opacity-40 transition-colors"
                >
                  {interpreting ? (
                    "A analisar…"
                  ) : interpretation ? (
                    <><RefreshCw className="h-3 w-3" /> Reanalisar</>
                  ) : (
                    "Analisar sonda"
                  )}
                </button>
              </div>

              {interpreting && (
                <div className="space-y-2 px-4 py-3">
                  {[...Array(3)].map((_, i) => (
                    <div key={i} className={`h-3 animate-pulse rounded bg-card ${i === 2 ? "w-3/5" : "w-full"}`} />
                  ))}
                </div>
              )}

              {interpretError && (
                <p className="px-4 py-3 text-[13px] text-terra">{interpretError}</p>
              )}

              {interpretation && !interpreting && (
                <InterpretationBody text={interpretation} />
              )}

              {!interpretation && !interpreting && !interpretError && (
                <p className="px-4 py-3 text-[12px] text-ink-3">
                  A IA identifica padrões no sinal: flatline, resposta fraca, drenagem rápida, profundidade não atingida.
                </p>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function DetectedEvents({ events, hoveredEventId, onHover }: {
  events: ProbeDetectedEvent[];
  hoveredEventId: string | null;
  onHover: (id: string | null) => void;
}) {
  const [open, setOpen] = useState(false);

  return (
    <div className="rounded-md border border-rule-soft bg-card">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between px-4 py-3 text-left"
      >
        <span className="font-mono text-[10px] tracking-[0.1em] uppercase text-ink-3">
          Rega / chuva detectada
        </span>
        <span className="flex items-center gap-2 shrink-0">
          {events.length > 0 && (
            <span className="font-mono text-[10px] text-ink-3">{events.length}</span>
          )}
          <ChevronDown className={`h-3.5 w-3.5 text-ink-3 transition-transform duration-200 ${open ? "" : "-rotate-90"}`} />
        </span>
      </button>

      {open && (
        <div className="border-t border-rule-soft px-4 pb-3 pt-2">
          {events.length === 0 ? (
            <p className="text-[12.5px] text-ink-3">
              Sem aumentos rápidos de humidade no período seleccionado.
            </p>
          ) : (
            <ul className="divide-y divide-rule-soft">
              {events.map((event) => (
                <li
                  key={event.id}
                  className={`py-2 first:pt-0 last:pb-0 rounded transition-colors ${hoveredEventId === event.id ? "bg-paper-in" : ""}`}
                  onMouseEnter={() => onHover(event.id)}
                  onMouseLeave={() => onHover(null)}
                >
                  <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
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
                    <span className="font-mono text-[11px] text-ink-3">
                      conf. {event.confidence}
                    </span>
                  </div>
                  <p className="mt-1 text-[12.5px] leading-relaxed text-ink-2">
                    {event.message} Prof.: {event.depths_cm.join(", ")} cm; aumento soma {(event.delta_vwc * 100).toFixed(1)}%.
                    {event.rainfall_mm != null ? ` Chuva: ${event.rainfall_mm.toFixed(1)} mm.` : ""}
                    {event.irrigation_mm != null ? ` Rega: ${event.irrigation_mm.toFixed(1)} mm.` : ""}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

function InterpretationBody({ text }: { text: string }) {
  const lines = text
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean);

  return (
    <ul className="divide-y divide-rule-soft">
      {lines.map((line, i) => {
        const clean = line.replace(/^[•\-]\s*/, "");
        const colonIdx = clean.indexOf(":");
        const label = colonIdx > -1 ? clean.slice(0, colonIdx).trim() : null;
        const rest = colonIdx > -1 ? clean.slice(colonIdx + 1).trim() : clean;
        const parts = rest.split(/\s*→\s*/);

        return (
          <li key={i} className="px-4 py-2.5 text-[12.5px] leading-relaxed">
            {label && (
              <span className="font-serif font-semibold text-ink">{label}: </span>
            )}
            {parts.map((part, j) => (
              <span key={j}>
                {j > 0 && <span className="mx-1 text-ink-3">→</span>}
                <span className={
                  j === parts.length - 1 && parts.length > 1
                    ? "font-medium text-[#c9a34a]"
                    : "text-ink-2"
                }>
                  {part}
                </span>
              </span>
            ))}
          </li>
        );
      })}
    </ul>
  );
}
