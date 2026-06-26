"use client";

import { useState } from "react";
import { SlidersHorizontal } from "lucide-react";
import { ApiError, calibrationApi } from "@/lib/api";
import { useToast } from "@/hooks/useToast";

const UNAVAILABLE_TOOLTIP = "Calibração disponível apenas para sondas de humidade (VWC)";

interface Props {
  sectorId: string;
  /** Called after a successful calibration so the caller can refresh the
   *  recommendation/depletion using the freshly saved bounds. */
  onCalibrated?: () => void | Promise<void>;
  /** False for tension/Watermark-only sectors (no VWC sensor) — the button is
   *  disabled with an explanatory tooltip rather than failing on click. */
  available?: boolean;
  className?: string;
}

/**
 * Manually triggers deterministic probe calibration for a sector. The label says
 * "AI Calibration" for the user, but the work is deterministic Python on the
 * backend (no LLM decides soil parameters). On success it refreshes the
 * recommendation so the recalculated depletion reflects the new bounds.
 */
export function AiCalibrationButton({
  sectorId,
  onCalibrated,
  available = true,
  className,
}: Props) {
  const { toast } = useToast();
  const [running, setRunning] = useState(false);

  async function handleClick() {
    setRunning(true);
    try {
      const r = await calibrationApi.run(sectorId);
      const cc = (r.observed_fc * 100).toFixed(0);
      const refill = (r.observed_refill * 100).toFixed(0);
      if (!r.changed) {
        // Already calibrated and the recompute matched — say so honestly instead
        // of showing an "updated" toast with identical numbers.
        toast("Sem alterações", {
          variant: "info",
          description: `Já calibrado — CC ${cc} vol% · linha de recarga efetiva ${refill} vol%`,
        });
        return;
      }
      if (r.previous_fc != null) {
        toast("Calibração atualizada", {
          variant: "success",
          description:
            `CC ${(r.previous_fc * 100).toFixed(0)}→${cc} vol% · ` +
            `linha de recarga efetiva ${refill} vol%`,
        });
      } else {
        toast("Calibração concluída", {
          variant: "success",
          description: `CC calibrada ${cc} vol% · linha de recarga efetiva ${refill} vol%`,
        });
      }
      // Only refresh the recommendation when the bounds actually moved.
      await onCalibrated?.();
    } catch (e) {
      // 422 carries a specific, user-readable reason from the backend (tension-only
      // probe, too few VWC readings, implausible envelope) — surface it verbatim.
      const is422 = e instanceof ApiError && e.status === 422;
      toast(is422 ? "Calibração indisponível" : "Calibração falhou", {
        variant: "error",
        description: e instanceof ApiError ? e.detail : "Ocorreu um erro inesperado.",
      });
    } finally {
      setRunning(false);
    }
  }

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={running || !available}
      aria-busy={running}
      title={available ? undefined : UNAVAILABLE_TOOLTIP}
      className={
        className ??
        "inline-flex items-center gap-2 rounded-full border border-rule bg-paper px-4 py-2 text-[13px] font-medium text-ink hover:bg-paper-in disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
      }
    >
      <SlidersHorizontal className="h-3.5 w-3.5" />
      <span className="hidden sm:inline">{running ? "A calibrar…" : "Calibração AI"}</span>
    </button>
  );
}
