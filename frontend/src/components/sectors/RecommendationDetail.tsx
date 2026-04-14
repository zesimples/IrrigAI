"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { OverrideModal } from "@/components/overrides/OverrideModal";
import { recommendationsApi } from "@/lib/api";
import type {
  ConfidenceLevel,
  RecommendationAction,
  RecommendationDetail as Rec,
} from "@/types";

// ── Config ────────────────────────────────────────────────────────────────────

const ACTION_CONFIG: Record<
  RecommendationAction,
  { label: string; badge: string }
> = {
  irrigate: { label: "Irrigar",         badge: "bg-irrigai-green-bg text-irrigai-green-dark" },
  skip:     { label: "Não irrigar",     badge: "bg-irrigai-gray-bg text-irrigai-text-muted" },
  reduce:   { label: "Reduzir rega",    badge: "bg-irrigai-amber-bg text-irrigai-amber-dark" },
  increase: { label: "Aumentar rega",   badge: "bg-irrigai-amber-bg text-irrigai-amber-dark" },
  defer:    { label: "Adiar decisão",   badge: "bg-irrigai-amber-bg text-irrigai-amber-dark" },
};

const CONF_COLOR: Record<ConfidenceLevel, string> = {
  high:   "bg-irrigai-green",
  medium: "bg-irrigai-amber",
  low:    "bg-irrigai-red",
};

const CONF_FILL: Record<ConfidenceLevel, string> = {
  high:   "bg-irrigai-green",
  medium: "bg-irrigai-amber",
  low:    "bg-irrigai-red",
};

const CONF_LABEL: Record<ConfidenceLevel, string> = {
  high:   "Alta",
  medium: "Média",
  low:    "Baixa",
};

type ReasonCat = "soil" | "weather" | "trigger" | "config" | "confidence";

const REASON_STYLE: Record<ReasonCat, { dot: string; icon: string }> = {
  soil:       { dot: "bg-irrigai-green",  icon: "💧" },
  weather:    { dot: "bg-irrigai-blue",   icon: "☁" },
  trigger:    { dot: "bg-irrigai-text",   icon: "→" },
  config:     { dot: "bg-irrigai-amber",  icon: "⚠" },
  confidence: { dot: "bg-irrigai-text-hint", icon: "%" },
};

function reasonCat(category: string | undefined | null): ReasonCat {
  const c = (category ?? "").toLowerCase();
  if (c === "confidence") return "confidence";
  if (c === "trigger") return "trigger";
  if (c === "config" || c.includes("default") || c.includes("missing")) return "config";
  if (c.includes("weather") || c.includes("evapotranspiration") || c.includes("forecast") || c.includes("rain") || c === "dosage") return "weather";
  if (c === "water_balance") return "soil";
  return "soil";
}

// ── Component ─────────────────────────────────────────────────────────────────

interface RecommendationDetailProps {
  rec: Rec;
  onUpdate?: () => void;
}

export function RecommendationDetail({ rec, onUpdate }: RecommendationDetailProps) {
  const [notes, setNotes] = useState("");
  const [loading, setLoading] = useState<"accept" | "reject" | null>(null);
  const [showOverrideModal, setShowOverrideModal] = useState(false);

  const action = ACTION_CONFIG[rec.action];
  const confPct = Math.round(rec.confidence_score * 100);

  async function handleAccept() {
    setLoading("accept");
    try {
      await recommendationsApi.accept(rec.id, notes || undefined);
      onUpdate?.();
    } finally {
      setLoading(null);
    }
  }

  async function handleReject() {
    setLoading("reject");
    try {
      await recommendationsApi.reject(rec.id, notes || undefined);
      onUpdate?.();
    } finally {
      setLoading(null);
    }
  }

  return (
    <div className="rounded-xl border border-black/[0.08] bg-white overflow-hidden">
      {/* ── Header ── */}
      <div className="px-4 pt-4 pb-3 border-b border-black/[0.06]">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <span className={`rounded-full px-3 py-[4px] text-[13px] font-medium ${action.badge}`}>
              {action.label}
            </span>
            {rec.irrigation_depth_mm != null && (
              <span className="text-[12px] text-irrigai-text-muted">
                <span className="font-display font-[500] text-[16px] text-irrigai-text">
                  {rec.irrigation_depth_mm.toFixed(1)}
                </span>
                {" mm"}
                {rec.irrigation_runtime_min != null && (
                  <>
                    {" · "}
                    <span className="font-display font-[500] text-[16px] text-irrigai-text">
                      {Math.round(rec.irrigation_runtime_min)}
                    </span>
                    {" min"}
                  </>
                )}
              </span>
            )}
          </div>
          <span className="text-[12px] font-medium text-irrigai-text tabular-nums">{confPct}%</span>
        </div>

        {/* Confidence bar */}
        <div className="flex items-center gap-3 mt-3">
          <span className="text-[11px] text-irrigai-text-muted min-w-[54px]">Confiança</span>
          <div className="flex-1 h-1.5 rounded-full bg-black/[0.06] overflow-hidden">
            <div
              className={`h-full rounded-full ${CONF_FILL[rec.confidence_level]}`}
              style={{ width: `${confPct}%` }}
            />
          </div>
          <span className={`text-[11px] font-medium`}>
            <span className={`inline-block h-1.5 w-1.5 rounded-full mr-1 align-middle ${CONF_COLOR[rec.confidence_level]}`} />
            {CONF_LABEL[rec.confidence_level]}
          </span>
        </div>

        <p className="mt-2 text-[11px] text-irrigai-text-hint">
          Gerada em{" "}
          {new Date(rec.generated_at).toLocaleString("pt-PT", {
            day: "numeric",
            month: "short",
            hour: "2-digit",
            minute: "2-digit",
          })}
        </p>
      </div>

      <div className="px-4 py-4 space-y-5">
        {/* ── Input data grid ── */}
        {(rec.inputs_snapshot.et0_mm != null ||
          rec.inputs_snapshot.depletion_mm != null ||
          rec.inputs_snapshot.taw_mm != null ||
          rec.inputs_snapshot.kc != null) && (
          <div>
            <p className="mb-2 text-[11px] font-medium uppercase tracking-[0.05em] text-irrigai-text-hint">
              Dados do cálculo
            </p>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              {rec.inputs_snapshot.et0_mm != null && (
                <DataCell label="Evapotranspiração" value={`${rec.inputs_snapshot.et0_mm.toFixed(2)} mm/dia`} />
              )}
              {rec.inputs_snapshot.depletion_mm != null && (
                <DataCell label="Água em falta" value={`${rec.inputs_snapshot.depletion_mm.toFixed(1)} mm`} />
              )}
              {rec.inputs_snapshot.taw_mm != null && (
                <DataCell label="Água disponível" value={`${rec.inputs_snapshot.taw_mm.toFixed(0)} mm`} />
              )}
              {rec.inputs_snapshot.kc != null && (
                <DataCell label="Factor da cultura" value={rec.inputs_snapshot.kc.toFixed(2)} />
              )}
            </div>
          </div>
        )}

        {/* ── Reasons ── */}
        {rec.reasons.length > 0 && (
          <div>
            <p className="mb-2 text-[11px] font-medium uppercase tracking-[0.05em] text-irrigai-text-hint">
              Razões
            </p>
            <div className="rounded-xl border border-black/[0.07] overflow-hidden">
              {rec.reasons.map((r, i) => {
                const cat = reasonCat(r.category);
                const style = REASON_STYLE[cat];
                return (
                  <div
                    key={r.order}
                    className={`flex items-center gap-3 px-4 py-3 ${
                      i < rec.reasons.length - 1 ? "border-b border-black/[0.05]" : ""
                    }`}
                  >
                    <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${style.dot}`} />
                    <span className="flex-1 text-[12px] leading-snug text-irrigai-text">
                      {r.message_pt}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* ── Decision ── */}
        {rec.is_accepted === null ? (
          <div className="space-y-3 rounded-xl border border-black/[0.07] bg-irrigai-surface p-4">
            <div>
              <p className="text-[13px] font-medium text-irrigai-text">A sua decisão</p>
              <p className="text-[11px] text-irrigai-text-muted mt-0.5">
                Notas opcionais para auditoria e feedback do modelo.
              </p>
            </div>
            <label htmlFor="rec-notes" className="sr-only">Notas da recomendação</label>
            <textarea
              id="rec-notes"
              className="w-full rounded-lg border border-black/[0.1] bg-white px-3 py-2.5 text-[13px] text-irrigai-text placeholder-irrigai-text-hint focus:border-irrigai-green focus:outline-none focus:ring-1 focus:ring-irrigai-green/30 resize-y"
              placeholder="Ex: solo visualmente seco, rega manual feita ontem…"
              rows={2}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
            />
            <div className="flex gap-2">
              <Button
                size="md"
                variant="primary"
                loading={loading === "accept"}
                onClick={handleAccept}
                className="flex-1"
              >
                Aceitar recomendação
              </Button>
              <Button
                size="md"
                variant="secondary"
                loading={loading === "reject"}
                onClick={handleReject}
                className="flex-1"
              >
                Rejeitar
              </Button>
            </div>
            <button
              className="w-full text-center text-[12px] text-irrigai-text-muted hover:text-irrigai-text transition-colors"
              onClick={() => setShowOverrideModal(true)}
            >
              Substituir com dose personalizada (Agrónomo)
            </button>
          </div>
        ) : (
          <div className="flex items-center gap-3 rounded-xl border border-black/[0.07] bg-irrigai-surface px-4 py-3">
            <span
              className={`inline-block h-2 w-2 rounded-full ${
                rec.is_accepted ? "bg-irrigai-green" : "bg-irrigai-gray"
              }`}
            />
            <div>
              <p className="text-[13px] font-medium text-irrigai-text">
                {rec.is_accepted ? "Recomendação aceite" : "Recomendação rejeitada"}
              </p>
              {rec.accepted_at && (
                <p className="text-[11px] text-irrigai-text-muted mt-0.5">
                  {new Date(rec.accepted_at).toLocaleString("pt-PT", {
                    day: "numeric",
                    month: "short",
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                  {rec.override_by &&
                    ` · Dose ajustada para ${rec.irrigation_depth_mm?.toFixed(1)} mm`}
                </p>
              )}
            </div>
          </div>
        )}
      </div>

      {showOverrideModal && (
        <OverrideModal
          rec={rec}
          onClose={() => setShowOverrideModal(false)}
          onSuccess={() => {
            setShowOverrideModal(false);
            onUpdate?.();
          }}
        />
      )}
    </div>
  );
}

function DataCell({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-black/[0.07] bg-irrigai-surface px-3 py-2.5 text-center">
      <p className="text-[11px] text-irrigai-text-muted">{label}</p>
      <p className="mt-0.5 text-[13px] font-medium text-irrigai-text">{value}</p>
    </div>
  );
}
