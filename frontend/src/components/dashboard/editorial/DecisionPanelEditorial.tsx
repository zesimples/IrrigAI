"use client";

import { useState } from "react";
import { recommendationsApi } from "@/lib/api";
import type { RecommendationDetail } from "@/types";

interface Props {
  rec: RecommendationDetail;
  onUpdate: () => void;
  onOverride: () => void;
}

export function DecisionPanelEditorial({ rec, onUpdate, onOverride }: Props) {
  const [notes, setNotes] = useState("");
  const [loading, setLoading] = useState<"accept" | "reject" | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [optimisticAccepted, setOptimisticAccepted] = useState<boolean | null>(null);

  const displayAccepted = optimisticAccepted !== null ? optimisticAccepted : rec.is_accepted;
  const isRegar = rec.action === "irrigate";

  async function handleAccept() {
    setLoading("accept");
    setActionError(null);
    try {
      setOptimisticAccepted(true);
      await recommendationsApi.accept(rec.id, notes || undefined);
      await onUpdate();
    } catch {
      setOptimisticAccepted(null);
      setActionError("Erro ao registar decisão.");
    } finally {
      setLoading(null);
    }
  }

  async function handleReject() {
    setLoading("reject");
    setActionError(null);
    try {
      setOptimisticAccepted(false);
      await recommendationsApi.reject(rec.id, notes || undefined);
      await onUpdate();
    } catch {
      setOptimisticAccepted(null);
      setActionError("Erro ao registar decisão.");
    } finally {
      setLoading(null);
    }
  }

  if (displayAccepted === true) {
    return (
      <article className="bg-paper-in border border-rule rounded-lg p-[22px_26px] mb-[22px]">
        <h3 className="font-serif text-[20px] font-semibold tracking-[-0.01em] mb-3">A sua decisão</h3>
        <div className="flex items-center gap-2">
          <span className="h-2 w-2 rounded-full bg-olive" />
          <p className="font-serif text-[14px] text-olive font-medium">
            Aceite{rec.accepted_at ? ` em ${new Date(rec.accepted_at).toLocaleDateString("pt-PT")}` : ""}
          </p>
        </div>
        {rec.override_by && (
          <p className="text-[12px] text-ink-3 mt-1.5">Substituído com dose personalizada</p>
        )}
      </article>
    );
  }

  if (displayAccepted === false) {
    return (
      <article className="bg-paper-in border border-rule rounded-lg p-[22px_26px] mb-[22px]">
        <h3 className="font-serif text-[20px] font-semibold tracking-[-0.01em] mb-3">A sua decisão</h3>
        <div className="flex items-center gap-2">
          <span className="h-2 w-2 rounded-full bg-terra" />
          <p className="font-serif text-[14px] text-terra font-medium">Rejeitado</p>
        </div>
      </article>
    );
  }

  return (
    <article className="bg-paper-in border border-rule rounded-lg p-[22px_26px] mb-[22px]">
      <div className="flex items-baseline justify-between mb-1">
        <h3 className="font-serif text-[20px] font-semibold tracking-[-0.01em]">A sua decisão</h3>
        <button
          onClick={onOverride}
          className="font-serif italic text-[13px] text-ink-2 hover:text-ink transition-colors shrink-0 ml-4"
        >
          Substituir com dose personalizada →
        </button>
      </div>
      <p className="text-[13px] text-ink-2 mb-3.5">
        Notas opcionais para auditoria e feedback do modelo.
      </p>

      <textarea
        placeholder="Ex: solo visualmente seco, rega manual feita ontem…"
        value={notes}
        onChange={(e) => setNotes(e.target.value)}
        className="w-full min-h-[60px] resize-y border border-rule bg-paper rounded-md px-3 py-2.5 text-[13px] text-ink placeholder:text-ink-3 focus:outline-none focus:ring-1 focus:ring-terra"
      />

      {actionError && <p className="text-[12px] text-terra mt-2">{actionError}</p>}

      <div className="flex gap-2.5 mt-3.5">
        <button
          onClick={handleAccept}
          disabled={loading !== null}
          className={`flex-1 rounded-md py-3 px-4 text-[14px] font-semibold transition-opacity disabled:opacity-50 ${
            isRegar ? "bg-terra text-paper" : "bg-ink text-paper"
          }`}
        >
          {loading === "accept"
            ? "A guardar…"
            : isRegar
            ? `Iniciar rega${rec.irrigation_depth_mm ? ` — ${rec.irrigation_depth_mm.toFixed(0)} mm` : ""}`
            : "Aceitar recomendação"}
        </button>
        <button
          onClick={handleReject}
          disabled={loading !== null}
          className="flex-1 rounded-md py-3 px-4 text-[14px] text-ink-2 border border-rule transition-opacity disabled:opacity-50 hover:bg-paper-in"
        >
          {loading === "reject" ? "A guardar…" : "Rejeitar"}
        </button>
      </div>
    </article>
  );
}
