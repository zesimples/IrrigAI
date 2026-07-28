"use client";

import { useState } from "react";
import { RefreshCw } from "lucide-react";
import { ApiError, calibrationApi, farmsApi } from "@/lib/api";
import { useToast } from "@/hooks/useToast";
import { formatDecimal } from "@/lib/utils";
import type { CalibrationSweepResponse, SectorSweepOutcome } from "@/types";

/** Machine reasons come from the backend; these labels are display-only, the
 *  same split used for crop-stage keys. */
const REASON_LABELS: Record<string, string> = {
  applied: "aplicada",
  manual_override: "ajuste manual do solo",
  probe_stale: "sonda sem dados recentes",
  flatline: "sinal plano",
  delta_exceeds_cap: "variação demasiado grande",
  no_candidate: "sem dados suficientes",
  candidate: "registada como candidata",
  error: "erro",
};

/** m³/m³ → vol% for display, pt-PT formatted. */
function vol(v: number | null): string | null {
  return v == null ? null : formatDecimal(v * 100, 0);
}

function OutcomeRow({ o }: { o: SectorSweepOutcome }) {
  const before = vol(o.fc_before);
  const candidate = vol(o.fc_candidate);
  return (
    <div className="flex items-baseline justify-between gap-3 py-1">
      <span className="text-[12px] text-ink-2 truncate">{o.sector_name}</span>
      <span className="font-mono text-[10.5px] text-ink-3 shrink-0">
        {o.applied && before != null && candidate != null
          ? `${before} → ${candidate} vol%`
          : REASON_LABELS[o.reason] ?? o.reason}
        {/* A blocked sector still reports what it measured: the gate withheld a
            real value, which reads very differently from "no data". */}
        {!o.applied && before != null && candidate != null
          ? ` · ${before} ⇢ ${candidate} vol%`
          : ""}
      </span>
    </div>
  );
}

interface Props {
  farmId: string;
  initialEnabled: boolean;
}

/**
 * Per-farm calibration auto-apply toggle plus an on-demand sweep.
 *
 * The sweep runs the SAME path the Monday 04:00 UTC job runs and honours this
 * farm's flag, so with the toggle off it is a safe preview: candidates are
 * recorded and no soil bound moves.
 */
export function FarmCalibrationControls({ farmId, initialEnabled }: Props) {
  const { toast } = useToast();
  const [enabled, setEnabled] = useState(initialEnabled);
  const [saving, setSaving] = useState(false);
  const [running, setRunning] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [result, setResult] = useState<CalibrationSweepResponse | null>(null);
  const [showDetail, setShowDetail] = useState(false);

  async function handleToggle() {
    const next = !enabled;
    setEnabled(next); // optimistic
    setSaving(true);
    try {
      await farmsApi.setCalibrationAutoApply(farmId, next);
    } catch {
      setEnabled(!next); // revert
      toast("Não foi possível alterar a calibração automática", {
        variant: "error",
        description: "Tente novamente.",
      });
    } finally {
      setSaving(false);
    }
  }

  async function runSweep() {
    setConfirming(false);
    // Drop the previous tally first: left in place it sits beside the "a calibrar…"
    // spinner and reads as this run's answer.
    setResult(null);
    setShowDetail(false);
    setRunning(true);
    try {
      const r = await calibrationApi.sweepFarm(farmId);
      setResult(r);
      toast(r.auto_apply ? "Calibração aplicada" : "Candidatas registadas", {
        variant: "success",
        description: r.auto_apply
          ? `${r.counts.applied} aplicadas · ${r.counts.skipped} ignoradas`
          : `${r.counts.candidates} candidatas · sem alterações aos limites`,
      });
    } catch (e) {
      const rateLimited = e instanceof ApiError && e.status === 429;
      toast(rateLimited ? "Demasiados pedidos" : "A calibração falhou", {
        variant: "error",
        description: rateLimited
          ? "Aguarde um minuto e tente novamente."
          : e instanceof ApiError
            ? e.detail
            : "Erro inesperado.",
      });
    } finally {
      setRunning(false);
    }
  }

  // Only an enabled farm can have its live bounds changed by this button.
  function handleTriggerClick() {
    if (enabled) setConfirming(true);
    else void runSweep();
  }

  const c = result?.counts;

  return (
    <div className="border-t border-rule-soft px-6 py-2.5">
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-2.5">
          <button
            type="button"
            role="switch"
            aria-checked={enabled}
            aria-label="Calibração automática"
            disabled={saving}
            onClick={handleToggle}
            className={`relative h-[18px] w-8 rounded-full transition-colors disabled:opacity-40 ${
              enabled ? "bg-olive" : "bg-rule"
            }`}
          >
            <span
              className={`absolute top-[2px] h-[14px] w-[14px] rounded-full bg-paper transition-[left] ${
                enabled ? "left-[16px]" : "left-[2px]"
              }`}
            />
          </button>
          <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-ink-3">
            calibração automática
          </span>
        </div>

        {confirming ? (
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => void runSweep()}
              className="rounded-md border border-rule bg-paper px-2.5 py-1 text-[11.5px] text-ink-2"
            >
              confirmar
            </button>
            <button
              type="button"
              onClick={() => setConfirming(false)}
              className="text-[11.5px] text-ink-3 underline"
            >
              cancelar
            </button>
          </div>
        ) : (
          <button
            type="button"
            // Also blocked while the toggle write is in flight: `enabled` is
            // optimistic, so mid-PUT it can disagree with the flag the backend
            // will read — and the confirmation branch keys off `enabled`. Running
            // then could apply live bounds farm-wide with no confirmation shown.
            disabled={running || saving}
            onClick={handleTriggerClick}
            className="inline-flex items-center gap-1.5 rounded-md border border-rule bg-paper px-2.5 py-1 text-[11.5px] text-ink-2 hover:bg-paper-in disabled:opacity-40 transition-colors"
          >
            <RefreshCw className={`h-3 w-3 ${running ? "animate-spin" : ""}`} />
            {running ? "a calibrar…" : "correr"}
          </button>
        )}
      </div>

      {enabled && (
        <p className="mt-1.5 text-[11px] text-ink-3">
          Ativa: segunda-feira às 04:00 UTC os limites deste campo podem ser
          atualizados automaticamente.
        </p>
      )}

      {c && (
        <div className="mt-2">
          <div className="flex items-center justify-between gap-3">
            <span className="font-mono text-[10.5px] text-ink-3">
              aplicadas {c.applied} · ignoradas {c.skipped} · sem dados{" "}
              {c.no_candidate}
              {c.candidates ? ` · candidatas ${c.candidates}` : ""}
              {c.failed ? ` · erros ${c.failed}` : ""}
            </span>
            {result!.outcomes.length > 0 && (
              <button
                type="button"
                onClick={() => setShowDetail((s) => !s)}
                className="text-[11px] text-ink-3 underline shrink-0"
              >
                detalhe
              </button>
            )}
          </div>
          {/* Applied bounds change the depletion denominator, but nothing on
              screen moves until the 05:00 UTC recommendation run recomputes it —
              say so, or the card and the sector pages look like they disagree. */}
          {c.applied > 0 && (
            <p className="mt-1 text-[11px] text-ink-3">
              Os novos limites só se refletem na próxima recomendação (05:00 UTC).
            </p>
          )}
          {showDetail && (
            <div className="mt-1 divide-y divide-rule-soft">
              {result!.outcomes.map((o) => (
                <OutcomeRow key={o.sector_id} o={o} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
