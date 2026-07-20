import type { AgronomicInterpretation } from "@/types";
import { formatDecimal } from "@/lib/utils";


interface Props {
  interpretation: AgronomicInterpretation;
  compact?: boolean;
}

const RISK_LABEL = {
  low: "Risco baixo",
  medium: "Atenção",
  high: "Risco elevado",
} as const;

const RISK_CLASS = {
  low: "bg-olive/10 text-olive",
  medium: "bg-[#c9a34a]/15 text-[#8a6a18]",
  high: "bg-terra/10 text-terra",
} as const;


/** Render the validated API object directly; never parse model-authored prose. */
export function StructuredAIResult({ interpretation, compact = false }: Props) {
  const confidencePct = interpretation.confidence_score * 100;

  return (
    <div className="space-y-4" data-testid="structured-ai-result">
      <div className="flex items-start justify-between gap-3">
        <p className="font-serif text-[16px] leading-relaxed text-ink">
          {interpretation.summary}
        </p>
        <span
          className={`shrink-0 rounded-full px-2 py-1 font-mono text-[9px] uppercase tracking-[0.08em] ${RISK_CLASS[interpretation.risk_level]}`}
        >
          {RISK_LABEL[interpretation.risk_level]}
        </span>
      </div>

      <div className="rounded-lg border border-olive/20 bg-olive/[0.06] px-4 py-3">
        <p className="font-mono text-[9px] uppercase tracking-[0.12em] text-olive mb-1">
          Conselho de rega
        </p>
        <p className="text-[13.5px] leading-relaxed text-ink-2">
          {interpretation.irrigation_advice}
        </p>
      </div>

      {interpretation.evidence.length > 0 && (
        <section aria-label="Evidência verificada">
          <p className="font-mono text-[9px] uppercase tracking-[0.12em] text-ink-3 mb-2">
            Evidência verificada
          </p>
          <ul className="divide-y divide-black/[0.05] border-y border-black/[0.05]">
            {interpretation.evidence.map((evidence) => (
              <li
                key={evidence.evidence_id || evidence.source}
                className="grid grid-cols-[minmax(110px,0.7fr)_1fr] gap-3 py-2.5 text-[13px]"
              >
                <span className="font-medium text-ink">{evidence.label}</span>
                <span className="text-ink-2">{evidence.value}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {!compact && interpretation.recommended_actions.length > 0 && (
        <section>
          <p className="font-mono text-[9px] uppercase tracking-[0.12em] text-ink-3 mb-2">
            Próximos passos
          </p>
          <ul className="space-y-1.5">
            {interpretation.recommended_actions.map((action, index) => (
              <li key={`${index}-${action}`} className="flex gap-2 text-[13px] leading-relaxed text-ink-2">
                <span className="text-olive" aria-hidden="true">•</span>
                <span>{action}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {interpretation.missing_data.length > 0 && (
        <section className="rounded-md border border-[#c9a34a]/25 bg-[#c9a34a]/[0.07] px-3.5 py-3">
          <p className="font-mono text-[9px] uppercase tracking-[0.12em] text-[#8a6a18] mb-1.5">
            Limitações
          </p>
          {interpretation.missing_data.map((item, index) => (
            <p key={`${index}-${item}`} className="text-[12.5px] leading-relaxed text-ink-2">
              {item}
            </p>
          ))}
        </section>
      )}

      <p className="text-[11px] leading-relaxed text-ink-3">
        Confiança {formatDecimal(confidencePct, 0)}% — {interpretation.confidence_explanation}
      </p>
    </div>
  );
}
