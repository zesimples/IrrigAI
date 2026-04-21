"use client";

import { useEffect, useState } from "react";
import { calibrationApi } from "@/lib/api";
import { ApiError } from "@/lib/api";
import type { AutoCalibrationResult } from "@/types";

interface Props {
  sectorId: string;
  onAccepted?: () => void;
}

export function AutoCalibrationCard({ sectorId, onAccepted }: Props) {
  const [result, setResult] = useState<AutoCalibrationResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [accepting, setAccepting] = useState(false);
  const [dismissing, setDismissing] = useState(false);

  useEffect(() => {
    calibrationApi
      .get(sectorId)
      .then(setResult)
      .catch((e) => {
        // 404 = dismissed, insufficient data, or not applicable — just hide the card
        setResult(null);
      })
      .finally(() => setLoading(false));
  }, [sectorId]);

  async function handleAccept() {
    if (!result || result.match.status !== "better_match_found") return;
    setAccepting(true);
    try {
      await calibrationApi.accept(sectorId);
      setResult(null);
      onAccepted?.();
    } finally {
      setAccepting(false);
    }
  }

  async function handleDismiss() {
    setDismissing(true);
    try {
      await calibrationApi.dismiss(sectorId);
      setResult(null);
    } finally {
      setDismissing(false);
    }
  }

  if (loading || !result) return null;

  const { match, observed } = result;

  if (match.status === "validated") {
    const cp = match.current_preset ?? match.best_match;
    return (
      <div className="rounded-xl border border-irrigai-green/30 bg-irrigai-green/5 px-4 py-3.5">
        <p className="text-[11px] font-medium uppercase tracking-[0.05em] text-irrigai-text-hint mb-1">
          Solo validado
        </p>
        <p className="text-[13px] text-irrigai-text font-medium">
          {cp.preset_name_pt}
        </p>
        <p className="text-[12px] text-irrigai-text-muted mt-0.5">
          CC observada {observed.observed_fc_pct.toFixed(0)} vol% · preset {cp.preset_fc_pct.toFixed(0)} vol%
          {" · "}com base em {observed.num_cycles} ciclos de rega
        </p>
      </div>
    );
  }

  if (match.status === "better_match_found") {
    const bm = match.best_match;
    const cp = match.current_preset;
    return (
      <div className="rounded-xl border border-irrigai-amber/50 bg-irrigai-amber/5 px-4 py-3.5">
        <p className="text-[11px] font-medium uppercase tracking-[0.05em] text-irrigai-text-hint mb-2">
          Sugestão de tipo de solo
        </p>
        <p className="text-[13px] text-irrigai-text mb-1">
          {result.suggestion_pt}
        </p>
        <p className="text-[11px] text-irrigai-text-muted mb-3">
          Com base em {observed.num_cycles} ciclos de rega · CC observada {observed.observed_fc_pct.toFixed(0)} vol%
        </p>
        <div className="flex gap-2">
          <button
            onClick={handleAccept}
            disabled={accepting}
            className="flex-1 rounded-lg bg-irrigai-green px-3 py-2 text-[12px] font-medium text-white hover:bg-irrigai-green/90 disabled:opacity-50 transition-colors"
          >
            {accepting ? "A alterar…" : `Alterar para ${bm.preset_name_pt}`}
          </button>
          <button
            onClick={handleDismiss}
            disabled={dismissing}
            className="rounded-lg border border-black/[0.08] px-3 py-2 text-[12px] font-medium text-irrigai-text-muted hover:bg-black/[0.04] disabled:opacity-50 transition-colors"
          >
            {dismissing ? "…" : "Manter atual"}
          </button>
        </div>
      </div>
    );
  }

  // no_good_match
  return (
    <div className="rounded-xl border border-black/[0.08] bg-irrigai-surface px-4 py-3.5">
      <p className="text-[11px] font-medium uppercase tracking-[0.05em] text-irrigai-text-hint mb-1">
        Tipo de solo
      </p>
      <p className="text-[13px] text-irrigai-text-muted">
        {result.suggestion_pt}
      </p>
    </div>
  );
}
