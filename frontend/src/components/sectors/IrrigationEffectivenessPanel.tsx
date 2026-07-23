"use client";

import { useEffect, useState } from "react";

import { StructuredAIResult } from "@/components/ai/StructuredAIResult";
import {
  calibrationApi,
  chatApi,
  probesApi,
  sectorsApi,
} from "@/lib/api";
import { formatDecimal } from "@/lib/utils";
import type {
  AgronomicInterpretation,
  CalibrationHistoryRun,
  ProbeReadingsDiagnosticsResponse,
  RecommendationOutcome,
} from "@/types";

interface Props {
  sectorId: string;
  probeId?: string | null;
}

const OUTCOME_STATUS: Record<string, string> = {
  executed: "Rega executada",
  followed_skip: "Decisão de não regar seguida",
  no_event: "Sem rega associada",
};

export function IrrigationEffectivenessPanel({ sectorId, probeId }: Props) {
  const [outcomes, setOutcomes] = useState<RecommendationOutcome[]>([]);
  const [calibrations, setCalibrations] = useState<CalibrationHistoryRun[]>([]);
  const [diagnostics, setDiagnostics] =
    useState<ProbeReadingsDiagnosticsResponse | null>(null);
  const [analysis, setAnalysis] = useState<AgronomicInterpretation | null>(null);
  const [loading, setLoading] = useState(true);
  const [analysing, setAnalysing] = useState<"effectiveness" | "changes" | null>(
    null,
  );
  const [applying, setApplying] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    const requests: Promise<unknown>[] = [
      sectorsApi.recommendationOutcomes(sectorId),
      calibrationApi.history(sectorId),
      ...(probeId ? [probesApi.readingsDiagnostics(probeId)] : []),
    ];
    const results = await Promise.allSettled(requests);
    const outcomeResult = results[0];
    const calibrationResult = results[1];
    if (outcomeResult.status === "fulfilled") {
      setOutcomes(
        (outcomeResult.value as { items: RecommendationOutcome[] }).items,
      );
    }
    if (calibrationResult.status === "fulfilled") {
      setCalibrations(calibrationResult.value as CalibrationHistoryRun[]);
    }
    if (probeId && results[2]?.status === "fulfilled") {
      setDiagnostics(
        results[2].value as ProbeReadingsDiagnosticsResponse,
      );
    }
    if (results.every((result) => result.status === "rejected")) {
      setError("Não foi possível carregar os dados de eficácia.");
    }
    setLoading(false);
  }

  useEffect(() => {
    load();
  }, [sectorId, probeId]); // eslint-disable-line react-hooks/exhaustive-deps

  async function runAnalysis(kind: "effectiveness" | "changes") {
    setAnalysing(kind);
    setError(null);
    try {
      const response =
        kind === "effectiveness"
          ? await chatApi.effectivenessAnalysis(sectorId)
          : await chatApi.changeAnalysis(sectorId, 72);
      setAnalysis(response.structured ?? null);
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "Não foi possível gerar a análise.",
      );
    } finally {
      setAnalysing(null);
    }
  }

  async function applyCalibration(run: CalibrationHistoryRun) {
    setApplying(run.id);
    try {
      await calibrationApi.applyRun(run.id);
      await load();
    } finally {
      setApplying(null);
    }
  }

  if (loading) {
    return <div className="h-56 animate-pulse rounded-xl border border-rule bg-card" />;
  }

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-terra">
            Resultado medido
          </p>
          <h2 className="mt-1 font-serif text-[28px] text-ink">
            Eficácia da rega
          </h2>
          <p className="mt-1 max-w-2xl text-[13px] leading-relaxed text-ink-2">
            Recomendação, dotação aplicada e resposta observada pela sonda.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            disabled={analysing !== null}
            onClick={() => runAnalysis("changes")}
            className="rounded-full border border-rule bg-paper px-4 py-2 text-[12px] text-ink hover:bg-paper-in disabled:opacity-50"
          >
            {analysing === "changes" ? "A analisar…" : "O que mudou em 72 h"}
          </button>
          <button
            type="button"
            disabled={analysing !== null}
            onClick={() => runAnalysis("effectiveness")}
            className="rounded-full bg-ink px-4 py-2 text-[12px] text-paper hover:opacity-85 disabled:opacity-50"
          >
            {analysing === "effectiveness"
              ? "A analisar…"
              : "Explicar eficácia com IA"}
          </button>
        </div>
      </header>

      {error && (
        <div className="rounded-md border border-terra/20 bg-terra-bg px-4 py-3 text-[13px] text-terra">
          {error}
        </div>
      )}

      {analysis && (
        <section className="rounded-xl border border-olive/25 bg-[#f0ece0] p-5">
          <StructuredAIResult interpretation={analysis} />
        </section>
      )}

      <section className="rounded-xl border border-rule bg-paper">
        <div className="border-b border-rule-soft px-5 py-3">
          <h3 className="font-serif text-[18px] text-ink">Resultados recentes</h3>
        </div>
        {outcomes.length === 0 ? (
          <p className="px-5 py-8 text-center text-[13px] text-ink-3">
            Ainda não existem recomendações aceites com uma rega posterior que
            possa ser avaliada.
          </p>
        ) : (
          <div className="divide-y divide-rule-soft">
            {outcomes.map((outcome) => (
              <article
                key={outcome.id}
                className="grid gap-3 px-5 py-4 sm:grid-cols-[1fr_repeat(3,minmax(100px,auto))]"
              >
                <div>
                  <p className="text-[13px] font-medium text-ink">
                    {OUTCOME_STATUS[outcome.status] ?? outcome.status}
                  </p>
                  <p className="mt-0.5 text-[11px] text-ink-3">
                    {new Date(outcome.evaluated_at).toLocaleString("pt-PT")}
                  </p>
                </div>
                <OutcomeValue
                  label="Recomendado"
                  value={outcome.recommended_depth_mm}
                  unit="mm"
                />
                <OutcomeValue
                  label="Aplicado"
                  value={outcome.actual_applied_mm}
                  unit="mm"
                />
                <OutcomeValue
                  label="Desvio"
                  value={outcome.dose_error_pct}
                  unit="%"
                  signed
                />
                {outcome.probe_response_delta != null && (
                  <p className="sm:col-span-4 text-[12px] text-ink-2">
                    A sonda registou resposta após a rega. O valor bruto fica
                    disponível ao avaliador determinístico, não é usado pela IA
                    para recalibrar limites.
                  </p>
                )}
                <ProbeResponseByDepth details={outcome.details} />
              </article>
            ))}
          </div>
        )}
      </section>

      <div className="grid gap-6 lg:grid-cols-2">
        <section className="rounded-xl border border-rule bg-paper">
          <div className="border-b border-rule-soft px-5 py-3">
            <h3 className="font-serif text-[18px] text-ink">
              Histórico de calibração
            </h3>
          </div>
          {calibrations.length === 0 ? (
            <p className="px-5 py-8 text-[13px] text-ink-3">
              Sem calibrações calculadas.
            </p>
          ) : (
            <div className="divide-y divide-rule-soft">
              {calibrations.slice(0, 8).map((run) => (
                <div key={run.id} className="flex items-center gap-4 px-5 py-3">
                  <div className="min-w-0 flex-1">
                    <p className="text-[13px] font-medium text-ink">
                      CC {formatDecimal(run.observed_fc * 100, 1)}% · recarga{" "}
                      {formatDecimal(run.observed_refill * 100, 1)}%
                    </p>
                    <p className="text-[11px] text-ink-3">
                      {new Date(run.computed_at).toLocaleDateString("pt-PT")} ·{" "}
                      {run.num_cycles} ciclos · {run.status}
                    </p>
                  </div>
                  {run.status === "candidate" && (
                    <button
                      type="button"
                      disabled={applying !== null}
                      onClick={() => applyCalibration(run)}
                      className="rounded-full border border-olive/30 bg-olive/10 px-3 py-1.5 text-[11px] font-medium text-olive disabled:opacity-50"
                    >
                      {applying === run.id ? "A aplicar…" : "Aplicar"}
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}
        </section>

        <section className="rounded-xl border border-rule bg-paper">
          <div className="border-b border-rule-soft px-5 py-3">
            <h3 className="font-serif text-[18px] text-ink">
              Diagnóstico da ingestão
            </h3>
          </div>
          {!probeId ? (
            <p className="px-5 py-8 text-[13px] text-ink-3">
              Este sector não tem sonda configurada.
            </p>
          ) : diagnostics ? (
            <div className="space-y-3 px-5 py-4 text-[13px] text-ink-2">
              <div className="flex justify-between">
                <span>Estado</span>
                <strong className="text-ink">{diagnostics.overall_status}</strong>
              </div>
              <div className="flex justify-between">
                <span>Leituras analisadas</span>
                <strong className="text-ink">{diagnostics.total_readings}</strong>
              </div>
              <div className="flex justify-between">
                <span>Falhas detectadas</span>
                <strong className="text-ink">{diagnostics.gap_count}</strong>
              </div>
              {diagnostics.max_gap_minutes != null && (
                <div className="flex justify-between">
                  <span>Maior intervalo</span>
                  <strong className="text-ink">
                    {formatDecimal(diagnostics.max_gap_minutes / 60, 1)} h
                  </strong>
                </div>
              )}
            </div>
          ) : (
            <p className="px-5 py-8 text-[13px] text-ink-3">
              Diagnóstico indisponível.
            </p>
          )}
        </section>
      </div>
    </div>
  );
}

function ProbeResponseByDepth({
  details,
}: {
  details: Record<string, unknown>;
}) {
  const rows = Array.isArray(details.probe_response_by_depth)
    ? (details.probe_response_by_depth as Array<Record<string, unknown>>)
    : [];
  if (rows.length === 0) return null;
  const label: Record<string, string> = {
    increase: "respondeu à rega",
    stable: "sem resposta clara",
    decrease: "continuou a consumir",
  };
  return (
    <div className="flex flex-wrap gap-2 sm:col-span-4">
      {rows.map((row) => (
        <span
          key={`${row.depth_cm}`}
          className="rounded-full border border-rule-soft bg-card px-2.5 py-1 text-[11px] text-ink-2"
        >
          {String(row.depth_cm)} cm ·{" "}
          {label[String(row.response)] ?? String(row.response)}
        </span>
      ))}
    </div>
  );
}

function OutcomeValue({
  label,
  value,
  unit,
  signed = false,
}: {
  label: string;
  value: number | null;
  unit: string;
  signed?: boolean;
}) {
  const prefix = signed && value != null && value > 0 ? "+" : "";
  return (
    <div>
      <p className="font-mono text-[9px] uppercase tracking-[0.1em] text-ink-3">
        {label}
      </p>
      <p className="font-serif text-[16px] text-ink">
        {value == null ? "—" : `${prefix}${formatDecimal(value, 1)} ${unit}`}
      </p>
    </div>
  );
}
