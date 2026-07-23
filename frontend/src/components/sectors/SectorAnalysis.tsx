"use client";

import { useEffect, useState } from "react";
import { StructuredAIResult } from "@/components/ai/StructuredAIResult";
import { chatApi, fieldObservationsApi } from "@/lib/api";
import { formatDecimal } from "@/lib/utils";
import type { AgronomicInterpretation } from "@/types";

// ─── Audio ───────────────────────────────────────────────────────────────────

function playResultChime() {
  try {
    const ctx = new AudioContext();
    const gain = ctx.createGain();
    gain.connect(ctx.destination);

    // Two-note ascending chime: C6 → E6
    const notes = [1046.5, 1318.5];
    notes.forEach((freq, i) => {
      const osc = ctx.createOscillator();
      osc.type = "sine";
      osc.frequency.value = freq;
      osc.connect(gain);

      const start = ctx.currentTime + i * 0.13;
      gain.gain.setValueAtTime(0, start);
      gain.gain.linearRampToValueAtTime(0.18, start + 0.01);
      gain.gain.exponentialRampToValueAtTime(0.0001, start + 0.55);

      osc.start(start);
      osc.stop(start + 0.6);
    });

    setTimeout(() => ctx.close(), 1500);
  } catch { /* AudioContext blocked or unavailable */ }
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function FieldWrapper({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <p className="font-serif text-[14.5px] font-semibold tracking-[-0.005em] text-ink mb-1.5">
        {label}
      </p>
      {children}
      {hint && (
        <p className="mt-1.5 text-[11.5px] text-ink-3 leading-[1.45]">{hint}</p>
      )}
    </div>
  );
}


const SOIL_OPTS = [
  { value: "very_dry", label: "Muito seco",  sub: "solo a fender",         dot: "#9c5a2a" },
  { value: "dry",      label: "Seco",        sub: "pouco húmido na mão",   dot: "#c9a34a" },
  { value: "adequate", label: "Adequado",    sub: "húmido mas solto",      dot: "#6b8f4e" },
  { value: "moist",    label: "Húmido",      sub: "compacta com pressão",  dot: "#5a8aa5" },
  { value: "wet",      label: "Encharcado",  sub: "água visível",          dot: "#3a6a8a" },
] as const;

function SoilVisualPicker({
  value,
  onChange,
}: {
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div className="grid grid-cols-2 sm:grid-cols-5 gap-2" role="radiogroup">
      {SOIL_OPTS.map((o) => {
        const sel = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={sel}
            onClick={() => onChange(sel ? "" : o.value)}
            className={`text-left rounded-md p-2.5 flex flex-col gap-1 transition-all ${
              sel
                ? "bg-card border"
                : "bg-paper border border-rule hover:bg-paper-in"
            }`}
            style={
              sel
                ? {
                    borderColor: o.dot,
                    boxShadow: `inset 3px 0 0 ${o.dot}`,
                  }
                : undefined
            }
          >
            <div className="flex items-center gap-1.5">
              <span
                className="h-2 w-2 rounded-full shrink-0"
                style={{ background: o.dot }}
              />
              <span className="font-serif text-[13px] font-semibold text-ink">
                {o.label}
              </span>
            </div>
            <span className="text-[10.5px] text-ink-3 leading-[1.35]">{o.sub}</span>
          </button>
        );
      })}
    </div>
  );
}

function AssistantResult({
  result,
  structured,
  timestamp,
  onCopy,
}: {
  result: string;
  structured: AgronomicInterpretation | null;
  timestamp: Date | null;
  onCopy: () => void;
}) {
  const timeLabel = timestamp
    ? Date.now() - timestamp.getTime() < 120_000
      ? "agora"
      : `há ${Math.round((Date.now() - timestamp.getTime()) / 60_000)} min`
    : null;

  return (
    <section className="mb-[26px] bg-[#f0ece0] border border-olive/30 rounded-xl overflow-hidden animate-fade-up">
      {/* Top accent bar */}
      <div className="h-[3px] bg-gradient-to-r from-olive/70 via-olive/40 to-transparent" />

      <div className="px-5 pt-5 pb-6 sm:px-7">
        {/* Header */}
        <header className="flex items-start justify-between mb-5 gap-4 flex-wrap">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <span className="h-2 w-2 rounded-full bg-olive" />
              <span className="font-mono text-[10.5px] tracking-[0.16em] uppercase text-[#4a6a36] font-medium">
                Explicação com IA
              </span>
            </div>
            {timeLabel && (
              <p className="font-serif italic text-[13px] text-ink-3 leading-none">
                {timeLabel} · cruzamento de sondas + meteo + histórico
              </p>
            )}
          </div>
        </header>

        {structured ? (
          <StructuredAIResult interpretation={structured} />
        ) : (
          <p className="text-[14px] leading-[1.65] text-ink-2 whitespace-pre-wrap">{result}</p>
        )}

        <footer className="mt-5 pt-4 border-t border-dashed border-olive/40 flex items-center justify-end gap-1.5">
          <button
            type="button"
            onClick={onCopy}
            className="inline-flex items-center gap-1.5 bg-paper/80 border border-rule rounded-md py-1.5 px-3 text-[12px] text-ink-2 hover:bg-paper transition-colors"
          >
            Copiar
          </button>
        </footer>
      </div>
    </section>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

interface Props {
  sectorId: string;
  et0Mm?: number | null;
  probeExternalId?: string | null;
  onSaved?: () => void | Promise<void>;
}

export function SectorAnalysis({
  sectorId,
  et0Mm,
  probeExternalId,
  onSaved,
}: Props) {
  const [soilCondition, setSoilCondition] = useState("");
  const [notes, setNotes] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [structured, setStructured] = useState<AgronomicInterpretation | null>(null);
  const [resultTimestamp, setResultTimestamp] = useState<Date | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Restore last AI result from localStorage so it survives tab/panel toggles
  const storageKey = `sector-analysis-result:${sectorId}`;
  useEffect(() => {
    try {
      const stored = localStorage.getItem(storageKey);
      if (stored) {
        const { text, structured: cachedStructured, ts } = JSON.parse(stored) as {
          text: string;
          structured?: AgronomicInterpretation | null;
          ts: number;
        };
        setResult(text);
        setStructured(cachedStructured ?? null);
        setResultTimestamp(new Date(ts));
      }
    } catch { /* ignore */ }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [storageKey]);

  async function handleAnalyse() {
    setLoading(true);
    setError(null);
    try {

      const soilLabel =
        SOIL_OPTS.find((o) => o.value === soilCondition)?.label ?? "";
      const userNotes =
        [
          soilCondition ? `Estado visual do solo: ${soilLabel}` : "",
          notes.trim() ? `Observações: ${notes.trim()}` : "",
        ]
          .filter(Boolean)
          .join("\n") || undefined;

      if (userNotes) {
        const expiresAt = new Date();
        expiresAt.setDate(expiresAt.getDate() + 7);
        await fieldObservationsApi.create(sectorId, {
          observation_type: "field_check",
          structured_value: soilCondition
            ? { visual_soil_condition: soilCondition }
            : null,
          text: notes.trim() || null,
          observed_at: new Date().toISOString(),
          expires_at: expiresAt.toISOString(),
        });
      }

      const res = await chatApi.explainSector(sectorId);
      const ts = new Date();
      setResult(res.explanation);
      setStructured(res.structured ?? null);
      setResultTimestamp(ts);
      setSoilCondition("");
      setNotes("");
      playResultChime();
      try {
        localStorage.setItem(
          storageKey,
          JSON.stringify({
            text: res.explanation,
            structured: res.structured ?? null,
            ts: ts.getTime(),
          }),
        );
      } catch { /* quota exceeded or SSR */ }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Erro ao contactar o assistente.");
    } finally {
      setLoading(false);
    }
  }

  function handleCopy() {
    if (result) navigator.clipboard.writeText(result).catch(() => {});
  }

  return (
    <article className="bg-paper border border-rule rounded-[10px] overflow-hidden">
      {/* Header */}
      <header className="bg-card border-b border-rule px-[26px] pt-[18px] pb-4 flex items-start justify-between gap-6 flex-wrap">
        <div>
          <div className="flex items-center gap-2 mb-1.5">
            <span className="h-1.5 w-1.5 rounded-full bg-terra" />
            <span className="font-mono text-[10.5px] tracking-[0.16em] uppercase text-terra">
              Explicação com IA
            </span>
          </div>
          <h2
            className="font-serif text-[24px] font-medium tracking-[-0.02em] text-ink leading-[1.2]"
            style={{ textWrap: "balance" } as React.CSSProperties}
          >
            Conte-nos o que vê no campo.{" "}
            <em className="font-instrument not-italic text-ink-2">
              Os sensores e a meteorologia já estão a ser lidos.
            </em>
          </h2>
        </div>
        <div className="flex items-center gap-2.5 shrink-0 pt-1">
          <span className="font-mono text-[10px] tracking-[0.08em] uppercase text-ink-3">
            Auto-incluídos
          </span>
          {["Sondas", "Meteo", "Histórico"].map((k) => (
            <span
              key={k}
              className="inline-flex items-center gap-1.5 font-serif italic text-[11px] text-ink-2"
            >
              <span className="h-[5px] w-[5px] rounded-full bg-olive" />
              {k}
            </span>
          ))}
        </div>
      </header>

      <div className="px-[26px] py-6">
        {/* Previous analysis result */}
        {result && (
          <AssistantResult
            key={resultTimestamp?.getTime() ?? 0}
            result={result}
            structured={structured}
            timestamp={resultTimestamp}
            onCopy={handleCopy}
          />
        )}

        {/* Observations form */}
        <div className="border border-rule-soft rounded-lg overflow-hidden bg-paper">
          <div className="bg-card border-b border-rule-soft px-[18px] py-2.5">
            <p className="font-mono text-[9.5px] tracking-[0.16em] uppercase text-ink-3">
              Observação de campo
            </p>
            <p className="font-serif italic text-[13px] text-ink-2 mt-0.5">
              O que os sensores não vêem
            </p>
          </div>
          <div className="p-[18px_22px] flex flex-col gap-[18px]">
            <FieldWrapper
              label="Estado visual do solo"
              hint="Útil quando a percepção visual não bate certo com a telemetria."
            >
              <SoilVisualPicker value={soilCondition} onChange={setSoilCondition} />
            </FieldWrapper>

            <FieldWrapper
              label="Observações adicionais"
              hint="Folhas, pragas, regas manuais, qualquer coisa que o modelo não saiba."
            >
              <textarea
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                rows={5}
                placeholder="Ex: Folhas com sinais de stress hídrico na manhã. Rega manual feita ontem à tarde…"
                className="w-full resize-y bg-paper border border-rule rounded-md px-3 py-2.5 text-[13px] text-ink leading-[1.5] placeholder:text-ink-3 focus:outline-none focus:ring-1 focus:ring-terra/30"
              />
            </FieldWrapper>
          </div>
        </div>

        {/* Error */}
        {error && (
          <div className="mt-4 rounded-md border border-terra/20 bg-terra-bg px-4 py-3 text-[13px] text-terra">
            {error}
          </div>
        )}

        {/* Footer CTA */}
        <div className="mt-5 pt-[18px] border-t border-rule-soft flex items-center justify-between gap-4 flex-wrap">
          <p className="font-serif italic text-[13.5px] text-ink-2 leading-[1.5] flex-1 min-w-0">
            Vou cruzar isto com{" "}
            <strong className="not-italic font-semibold text-ink">
              {et0Mm != null ? `${formatDecimal(et0Mm, 1)} mm` : "dados actuais"}
            </strong>{" "}
            de ET₀ de hoje
            {probeExternalId && (
              <>
                , a sonda{" "}
                <strong className="not-italic font-semibold text-ink font-mono text-[12.5px]">
                  {probeExternalId}
                </strong>
              </>
            )}{" "}
            e os últimos 14 dias de histórico desta parcela.
          </p>
          <button
            type="button"
            onClick={handleAnalyse}
            disabled={loading}
            className="inline-flex items-center gap-2.5 bg-ink text-paper rounded-md py-3 px-[22px] text-[14px] font-semibold shadow-[0_6px_18px_rgba(42,37,32,0.18)] hover:opacity-85 disabled:opacity-40 transition-opacity shrink-0"
          >
            <span className="h-1.5 w-1.5 rounded-full bg-terra" />
            {loading ? "A analisar…" : "Pedir análise ao assistente"}
          </button>
        </div>
      </div>
    </article>
  );
}
