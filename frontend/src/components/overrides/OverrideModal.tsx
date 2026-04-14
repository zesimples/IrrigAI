"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { recommendationsApi } from "@/lib/api";
import { X } from "lucide-react";
import type { RecommendationDetail } from "@/types";

interface OverrideModalProps {
  rec: RecommendationDetail;
  onClose: () => void;
  onSuccess: () => void;
}

const ACTION_OPTIONS = [
  { value: "irrigate", label: "Regar" },
  { value: "skip", label: "Não regar" },
  { value: "defer", label: "Adiar" },
];

const STRATEGY_OPTIONS = [
  { value: "one_time", label: "Apenas esta vez" },
  { value: "until_next_stage", label: "Até próxima fase fenológica" },
];

export function OverrideModal({ rec, onClose, onSuccess }: OverrideModalProps) {
  const [customAction, setCustomAction] = useState(rec.action);
  const [depthMm, setDepthMm] = useState(rec.irrigation_depth_mm?.toString() ?? "");
  const [runtimeMin, setRuntimeMin] = useState(rec.irrigation_runtime_min?.toString() ?? "");
  const [reason, setReason] = useState("");
  const [strategy, setStrategy] = useState<"one_time" | "until_next_stage">("one_time");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit() {
    if (!reason.trim()) {
      setError("A razão da substituição é obrigatória.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await recommendationsApi.override(rec.id, {
        custom_action: customAction,
        custom_depth_mm: depthMm ? parseFloat(depthMm) : undefined,
        custom_runtime_min: runtimeMin ? parseFloat(runtimeMin) : undefined,
        override_reason: reason,
        override_strategy: strategy,
      });
      onSuccess();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao guardar substituição.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/45 px-4">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="override-modal-title"
        className="w-full max-w-md rounded-[1.75rem] border border-slate-200 bg-white shadow-2xl"
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
          <h2 id="override-modal-title" className="font-semibold text-slate-900">Substituição de recomendação</h2>
          <button
            onClick={onClose}
            className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600"
            aria-label="Fechar modal"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Original values */}
        <div className="mx-5 mt-4 rounded-2xl bg-slate-50 px-4 py-3 text-sm">
          <p className="mb-1 text-xs font-medium uppercase tracking-wide text-slate-500">Valores originais</p>
          <div className="grid grid-cols-3 gap-2 text-slate-700">
            <div>
              <p className="text-xs text-slate-400">Acção</p>
              <p className="font-medium">{rec.action}</p>
            </div>
            <div>
              <p className="text-xs text-slate-400">Dose</p>
              <p className="font-medium">
                {rec.irrigation_depth_mm != null ? `${rec.irrigation_depth_mm.toFixed(1)} mm` : "—"}
              </p>
            </div>
            <div>
              <p className="text-xs text-slate-400">Duração</p>
              <p className="font-medium">
                {rec.irrigation_runtime_min != null ? `${Math.round(rec.irrigation_runtime_min)} min` : "—"}
              </p>
            </div>
          </div>
        </div>

        {/* Override fields */}
        <div className="space-y-3 px-5 py-4">
          <Select
            label="Nova acção"
            options={ACTION_OPTIONS}
            value={customAction}
            onChange={(e) => setCustomAction(e.target.value as typeof customAction)}
          />
          <div className="grid grid-cols-2 gap-3">
            <Input
              label="Dose (mm)"
              type="number"
              min={0}
              step={0.5}
              value={depthMm}
              onChange={(e) => setDepthMm(e.target.value)}
              placeholder="ex: 8.0"
            />
            <Input
              label="Duração (min)"
              type="number"
              min={0}
              step={5}
              value={runtimeMin}
              onChange={(e) => setRuntimeMin(e.target.value)}
              placeholder="ex: 120"
            />
          </div>
          <Select
            label="Estratégia"
            options={STRATEGY_OPTIONS}
            value={strategy}
            onChange={(e) => setStrategy(e.target.value as "one_time" | "until_next_stage")}
          />
          <div>
            <label htmlFor="override-reason" className="mb-1 block text-sm font-semibold text-slate-800">
              Razão <span className="text-red-500">*</span>
            </label>
            <textarea
              id="override-reason"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              rows={3}
              placeholder="Ex: Árvores mostram sinais visuais de stress..."
              className="w-full rounded-xl border border-slate-300 px-3.5 py-2.5 text-sm outline-none focus:border-emerald-600 focus:ring-1 focus:ring-emerald-600"
            />
            <p className="mt-1 text-xs text-slate-500">
              Registe o motivo para auditoria e validação agronómica posterior.
            </p>
          </div>
          {error && <p className="text-sm font-medium text-red-700">{error}</p>}
        </div>

        {/* Footer */}
        <div className="flex flex-col-reverse justify-end gap-2 border-t border-slate-100 px-5 py-3 sm:flex-row">
          <Button variant="ghost" onClick={onClose} disabled={submitting}>
            Cancelar
          </Button>
          <Button onClick={handleSubmit} loading={submitting}>
            Guardar substituição
          </Button>
        </div>
      </div>
    </div>
  );
}
