"use client";

import { useState } from "react";
import { Microscope, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { chatApi } from "@/lib/api";

interface Props {
  sectorId: string;
}

export function SectorDiagnosisCard({ sectorId }: Props) {
  const [diagnosis, setDiagnosis] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    setLoading(true);
    setError(null);
    try {
      const res = await chatApi.diagnoseSector(sectorId);
      setDiagnosis(res.diagnosis);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao gerar diagnóstico.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="rounded-xl border border-black/[0.08] bg-white overflow-hidden">
      <div className="flex items-center justify-between gap-3 px-4 py-3 border-b border-black/[0.06]">
        <div className="flex items-center gap-2">
          <Microscope className="h-4 w-4 text-irrigai-text-hint" />
          <p className="text-[12px] font-medium uppercase tracking-[0.05em] text-irrigai-text-hint">
            Diagnóstico Agronómico
          </p>
        </div>
        <Button
          size="sm"
          variant="secondary"
          onClick={run}
          loading={loading}
        >
          {diagnosis ? (
            <>
              <RefreshCw className="h-3.5 w-3.5" />
              Reanalisar
            </>
          ) : (
            "Analisar causas"
          )}
        </Button>
      </div>

      {!diagnosis && !loading && !error && (
        <div className="px-4 py-5 text-center">
          <p className="text-[13px] text-irrigai-text-muted">
            A IA explica porque o sector está no estado hídrico actual — causas prováveis,
            não apenas sintomas.
          </p>
        </div>
      )}

      {loading && (
        <div className="space-y-2 px-4 py-4">
          {[...Array(4)].map((_, i) => (
            <div key={i} className={`h-3.5 animate-pulse rounded bg-irrigai-surface ${i === 3 ? "w-2/3" : "w-full"}`} />
          ))}
        </div>
      )}

      {error && (
        <div className="px-4 py-4 text-[13px] text-irrigai-red">{error}</div>
      )}

      {diagnosis && !loading && (
        <DiagnosisBody text={diagnosis} />
      )}
    </div>
  );
}

function DiagnosisBody({ text }: { text: string }) {
  const lines = text
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean);

  return (
    <ul className="divide-y divide-black/[0.04]">
      {lines.map((line, i) => {
        const clean = line.replace(/^[•\-]\s*/, "");
        const colonIdx = clean.indexOf(":");
        const label = colonIdx > -1 ? clean.slice(0, colonIdx) : null;
        const body = colonIdx > -1 ? clean.slice(colonIdx + 1).trim() : clean;

        return (
          <li key={i} className="px-4 py-3 text-[13px] leading-relaxed text-irrigai-text">
            {label ? (
              <>
                <span className="font-medium">{label}:</span>{" "}
                <span className="text-irrigai-text-muted">{body}</span>
              </>
            ) : (
              <span className="text-irrigai-text-muted">{body}</span>
            )}
          </li>
        );
      })}
    </ul>
  );
}
