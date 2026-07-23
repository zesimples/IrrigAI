import type { AgronomicInterpretation } from "@/types";
import { CROP_LABELS, STAGE_LABELS } from "@/lib/cropConfig";
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

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const INTERNAL_CODE_RE = /^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$/;


/** Render the validated API object directly; never parse model-authored prose. */
export function StructuredAIResult({ interpretation, compact = false }: Props) {
  const confidencePct = interpretation.confidence_score * 100;
  const evidence = interpretation.evidence
    .reduce<typeof interpretation.evidence>((rows, item) => {
      const label = item.label?.trim();
      const rawValue = item.value?.trim();
      if (!label || label.toLocaleLowerCase("pt-PT") === "dados" || !rawValue) {
        return rows;
      }
      const value =
        CROP_LABELS[rawValue] ?? STAGE_LABELS[rawValue] ?? rawValue;
      if (
        UUID_RE.test(value) ||
        (INTERNAL_CODE_RE.test(value) && value === rawValue) ||
        rows.some(
          (row) =>
            row.label.toLocaleLowerCase("pt-PT") ===
            label.toLocaleLowerCase("pt-PT"),
        )
      ) {
        return rows;
      }
      rows.push({ ...item, label, value });
      return rows;
    }, [])
    .slice(0, 5);

  return (
    <div className="space-y-4" data-testid="structured-ai-result">
      {interpretation.degraded && (
        <div
          role="status"
          className="rounded-md border border-[#c9a34a]/30 bg-[#c9a34a]/[0.08] px-3.5 py-2.5 text-[12px] leading-relaxed text-[#715617]"
        >
          O serviço de IA não respondeu. Esta é uma síntese de contingência,
          baseada apenas nos dados determinísticos disponíveis.
        </div>
      )}
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

      {evidence.length > 0 && (
        <section aria-label="Evidência verificada">
          <p className="font-mono text-[9px] uppercase tracking-[0.12em] text-ink-3 mb-2">
            Evidência verificada
          </p>
          <ul className="divide-y divide-black/[0.05] border-y border-black/[0.05]">
            {evidence.map((item) => (
              <li
                key={item.evidence_id || item.source}
                className="grid grid-cols-[minmax(110px,0.7fr)_1fr] gap-3 py-2.5 text-[13px]"
              >
                <span className="font-medium text-ink">{item.label}</span>
                <span className="text-ink-2">{item.value}</span>
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
