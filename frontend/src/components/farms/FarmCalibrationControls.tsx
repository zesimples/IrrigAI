"use client";

import { useEffect, useRef, useState } from "react";
import { RefreshCw } from "lucide-react";
import { ApiError, calibrationApi, farmsApi } from "@/lib/api";
import { useToast } from "@/hooks/useToast";
import { formatDecimal } from "@/lib/utils";
import type { CalibrationSweepRun, SectorSweepOutcome, SweepQueued } from "@/types";

const POLL_MS = 2_000;
/** Give up displaying progress after this long — a spinner that never ends is
 *  what made the synchronous version look broken. */
const POLL_CAP_MS = 20 * 60 * 1_000;

const TERMINAL = new Set(["success", "partial", "failure", "stale"]);

/** The 409 body is flat (`{detail, run_id}`), not FastAPI's nested envelope. */
function runIdFrom409(e: unknown): string | null {
  if (!(e instanceof ApiError) || e.status !== 409) return null;
  const body = e.body as { run_id?: string } | undefined;
  return body?.run_id ?? null;
}

/** Machine reasons come from the backend; these labels are display-only, the
 *  same split used for crop-stage keys. */
const REASON_LABELS: Record<string, string> = {
  applied: "aplicada",
  manual_override: "ajuste manual do solo",
  probe_stale: "sonda sem dados recentes",
  flatline: "sinal plano",
  delta_exceeds_cap: "variação demasiado grande",
  // Structural vs actionable. A sector with no moisture probe (flowmeter-only,
  // bare, or tension/Watermark) can never be calibrated — calling that "sem dados
  // suficientes" sent people looking for a data gap that does not exist.
  not_applicable: "sem sonda de humidade",
  insufficient_data: "dados insuficientes na sonda",
  // Kept for sweep rows persisted before the split (2026-07-29).
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
  const [run, setRun] = useState<CalibrationSweepRun | null>(null);
  const [gaveUp, setGaveUp] = useState(false);
  const [showDetail, setShowDetail] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const aliveRef = useRef(true);

  // Unmounting mid-sweep must not leave a timer firing setState on a dead
  // component — navigating away during a ten-minute sweep is the normal case.
  useEffect(() => {
    aliveRef.current = true;
    return () => {
      aliveRef.current = false;
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, []);

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

  function announce(r: CalibrationSweepRun) {
    // The sweep takes minutes; by the time it lands the user may be looking
    // elsewhere on the page, so the outcome is toasted as well as rendered.
    if (r.status === "stale") {
      toast("Calibração interrompida", {
        variant: "error",
        description: "Nada foi perdido — tente novamente.",
      });
      return;
    }
    if (r.status === "failure") {
      toast("A calibração falhou", {
        variant: "error",
        description: r.error ?? "Erro inesperado.",
      });
      return;
    }
    toast(r.auto_apply ? "Calibração aplicada" : "Candidatas registadas", {
      variant: "success",
      description: r.auto_apply
        ? `${r.counts.applied} aplicadas · ${r.counts.skipped} ignoradas`
        : `${r.counts.candidates} candidatas · sem alterações aos limites`,
    });
  }

  // Recursive setTimeout, not setInterval: a slow poll must not stack on itself.
  function schedulePoll(runId: string, deadline: number) {
    timerRef.current = setTimeout(async () => {
      if (!aliveRef.current) return;
      try {
        const r = await calibrationApi.sweepRun(runId);
        if (!aliveRef.current) return;
        setRun(r);
        if (TERMINAL.has(r.status)) {
          setRunning(false);
          announce(r);
          return;
        }
      } catch {
        // A transient poll failure is not a sweep failure — keep trying until
        // the cap, then say so.
      }
      if (!aliveRef.current) return;
      if (Date.now() >= deadline) {
        setRunning(false);
        setGaveUp(true);
        return;
      }
      schedulePoll(runId, deadline);
    }, POLL_MS);
  }

  async function runSweep() {
    setConfirming(false);
    // Drop the previous tally first: left in place it sits beside the "a calibrar…"
    // spinner and reads as this run's answer.
    setRun(null);
    setGaveUp(false);
    setShowDetail(false);
    setRunning(true);
    let queued: SweepQueued;
    try {
      queued = await calibrationApi.sweepFarm(farmId);
    } catch (e) {
      const existing = runIdFrom409(e);
      if (existing) {
        // Already running — follow that one rather than erroring uselessly.
        toast("Já está a correr", {
          variant: "info",
          description: "A acompanhar a calibração em curso.",
        });
        schedulePoll(existing, Date.now() + POLL_CAP_MS);
        return;
      }
      setRunning(false);
      const rateLimited = e instanceof ApiError && e.status === 429;
      toast(rateLimited ? "Demasiados pedidos" : "Não foi possível iniciar", {
        variant: "error",
        description: rateLimited
          ? "Aguarde um minuto e tente novamente."
          : e instanceof ApiError
            ? e.detail
            : "Erro inesperado.",
      });
      return;
    }
    schedulePoll(queued.run_id, Date.now() + POLL_CAP_MS);
  }

  // Only an enabled farm can have its live bounds changed by this button.
  function handleTriggerClick() {
    if (enabled) setConfirming(true);
    else void runSweep();
  }

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

      {/* Live progress. The sweep runs 5-10 minutes on a large farm, so
          "sector N of M" is the difference between working and hung. */}
      {running && run && run.sectors_total ? (
        <p className="mt-1.5 font-mono text-[10.5px] text-ink-3">
          a calibrar… {run.sectors_done}/{run.sectors_total}
        </p>
      ) : null}

      {gaveUp && (
        <p className="mt-1.5 text-[11px] text-ink-3">
          Ainda a correr — recarregue a página mais tarde para ver o resultado.
        </p>
      )}

      {run && TERMINAL.has(run.status) && (
        <div className="mt-2">
          {run.status === "stale" ? (
            <p className="text-[11px] text-ink-3">Interrompida — tente novamente.</p>
          ) : run.status === "failure" ? (
            <p className="text-[11px] text-ink-3">
              A calibração falhou{run.error ? `: ${run.error}` : "."}
            </p>
          ) : (
            <>
              <div className="flex items-center justify-between gap-3">
                <span className="font-mono text-[10.5px] text-ink-3">
                  aplicadas {run.counts.applied} · ignoradas {run.counts.skipped} · sem dados{" "}
                  {run.counts.no_candidate}
                  {run.counts.candidates ? ` · candidatas ${run.counts.candidates}` : ""}
                  {run.counts.failed ? ` · erros ${run.counts.failed}` : ""}
                </span>
                {run.outcomes && run.outcomes.length > 0 && (
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
                  screen moves until the 05:00 UTC recommendation run recomputes
                  it — say so, or the card and the sector pages look like they
                  disagree. */}
              {run.counts.applied > 0 && (
                <p className="mt-1 text-[11px] text-ink-3">
                  Os novos limites só se refletem na próxima recomendação (05:00 UTC).
                </p>
              )}
              {showDetail && run.outcomes && (
                <div className="mt-1 divide-y divide-rule-soft">
                  {run.outcomes.map((o) => (
                    <OutcomeRow key={o.sector_id} o={o} />
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
