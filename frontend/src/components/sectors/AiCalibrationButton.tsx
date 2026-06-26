"use client";

import { useState } from "react";
import { SlidersHorizontal } from "lucide-react";
import { ApiError, calibrationApi } from "@/lib/api";
import { useToast } from "@/hooks/useToast";

interface Props {
  sectorId: string;
  /** Called after a successful calibration so the caller can refresh the
   *  recommendation/depletion using the freshly saved bounds. */
  onCalibrated?: () => void | Promise<void>;
  className?: string;
}

/**
 * Manually triggers deterministic probe calibration for a sector. The label says
 * "AI Calibration" for the user, but the work is deterministic Python on the
 * backend (no LLM decides soil parameters). On success it refreshes the
 * recommendation so the recalculated depletion reflects the new bounds.
 */
export function AiCalibrationButton({ sectorId, onCalibrated, className }: Props) {
  const { toast } = useToast();
  const [running, setRunning] = useState(false);

  async function handleClick() {
    setRunning(true);
    try {
      const r = await calibrationApi.run(sectorId);
      toast("Calibração concluída", {
        variant: "success",
        description:
          `CC calibrada ${(r.observed_fc * 100).toFixed(0)} vol% · ` +
          `linha de recarga efetiva ${(r.observed_refill * 100).toFixed(0)} vol% ` +
          `(${r.method === "cycles" ? "ciclos de rega" : "envelope"})`,
      });
      await onCalibrated?.();
    } catch (e) {
      const insufficient = e instanceof ApiError && e.status === 422;
      toast(insufficient ? "Dados insuficientes" : "Calibração falhou", {
        variant: "error",
        description: insufficient
          ? "Não há dados de sonda suficientes para calibrar este sector."
          : e instanceof ApiError
            ? e.detail
            : "Ocorreu um erro inesperado.",
      });
    } finally {
      setRunning(false);
    }
  }

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={running}
      aria-busy={running}
      className={
        className ??
        "inline-flex items-center gap-2 rounded-full border border-rule bg-paper px-4 py-2 text-[13px] font-medium text-ink hover:bg-paper-in disabled:opacity-50 transition-colors"
      }
    >
      <SlidersHorizontal className="h-3.5 w-3.5" />
      <span className="hidden sm:inline">{running ? "A calibrar…" : "Calibração AI"}</span>
    </button>
  );
}
