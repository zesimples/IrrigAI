"use client";

import { useState } from "react";
import type { FlowmeterReferenceOut } from "@/types";

interface Props {
  reference: FlowmeterReferenceOut | null | undefined;
  /** Optional: deviation_pct of the latest event vs reference (pre-computed or null) */
  latestDeviationPct?: number | null;
  sectorId: string;
  onRecompute?: (sectorId: string) => void;
}

export function FlowmeterReferenceStatusDot({ reference, latestDeviationPct, sectorId, onRecompute }: Props) {
  const [open, setOpen] = useState(false);

  // Determine dot colour
  let dotColor = "#c9c3ba"; // grey = no reference / insufficient
  let label: string | null = null;

  if (reference && reference.status !== "insufficient" && reference.reference_rate_m3_ha !== null) {
    if (latestDeviationPct !== null && latestDeviationPct !== undefined && Math.abs(latestDeviationPct) > (reference.tolerance_pct ?? 5)) {
      dotColor = "#b84a2a"; // amber/red = deviation
      const sign = latestDeviationPct > 0 ? "+" : "";
      label = `${sign}${latestDeviationPct.toFixed(1)}%`;
    } else if (latestDeviationPct !== null && latestDeviationPct !== undefined) {
      dotColor = "#4a8c4a"; // green = OK
    } else {
      dotColor = "#c9a34a"; // amber = no recent event data
    }
  }

  const refRate = reference?.reference_rate_m3_ha;
  const statusLabel =
    reference == null ? "Sem referência" :
    reference.status === "insufficient" ? "Dados insuficientes" :
    reference.status === "provisional" ? "Provisional" : "Estabelecida";

  return (
    <div style={{ position: "relative", display: "inline-flex", alignItems: "center", gap: 5 }}>
      <button
        onClick={(e) => { e.stopPropagation(); setOpen((v) => !v); }}
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 5,
          background: "transparent",
          border: "none",
          cursor: "pointer",
          padding: 0,
        }}
        title="Caudal de referência"
      >
        <span style={{ width: 8, height: 8, borderRadius: 999, background: dotColor, flexShrink: 0 }} />
        {label && (
          <span style={{
            fontFamily: "var(--font-jetbrains, ui-monospace)",
            fontSize: 10.5,
            color: dotColor,
            fontWeight: 600,
            letterSpacing: "0.03em",
          }}>
            {label}
          </span>
        )}
      </button>

      {open && (
        <>
          {/* Backdrop */}
          <div
            style={{ position: "fixed", inset: 0, zIndex: 49 }}
            onClick={() => setOpen(false)}
          />
          {/* Popover */}
          <div style={{
            position: "absolute",
            top: "calc(100% + 8px)",
            left: 0,
            zIndex: 50,
            background: "#fff",
            border: "1px solid #dcd3c2",
            borderRadius: 10,
            boxShadow: "0 4px 24px rgba(0,0,0,0.1)",
            padding: "14px 16px",
            minWidth: 220,
            maxWidth: 280,
          }}>
            <div style={{
              fontFamily: "var(--font-jetbrains, ui-monospace)",
              fontSize: 9.5,
              color: "#8a7f74",
              letterSpacing: "0.14em",
              textTransform: "uppercase",
              marginBottom: 10,
            }}>Caudal de referência</div>

            <dl style={{ margin: 0, display: "grid", gridTemplateColumns: "auto 1fr", gap: "4px 12px" }}>
              <dt style={{ fontSize: 11.5, color: "#8a7f74", fontFamily: "var(--font-dm-sans, system-ui)" }}>Estado</dt>
              <dd style={{ fontSize: 11.5, color: "#2a2520", fontFamily: "var(--font-fraunces)", fontStyle: "italic", margin: 0 }}>{statusLabel}</dd>

              {refRate != null && (
                <>
                  <dt style={{ fontSize: 11.5, color: "#8a7f74", fontFamily: "var(--font-dm-sans, system-ui)" }}>Referência</dt>
                  <dd style={{ fontSize: 13, color: "#2a2520", fontFamily: "var(--font-fraunces)", fontWeight: 600, margin: 0 }}>{refRate.toFixed(2)} m³/ha</dd>

                  <dt style={{ fontSize: 11.5, color: "#8a7f74", fontFamily: "var(--font-dm-sans, system-ui)" }}>Tolerância</dt>
                  <dd style={{ fontSize: 11.5, color: "#2a2520", fontFamily: "var(--font-jetbrains, ui-monospace)", margin: 0 }}>±{reference!.tolerance_pct}%</dd>

                  <dt style={{ fontSize: 11.5, color: "#8a7f74", fontFamily: "var(--font-dm-sans, system-ui)" }}>Limites</dt>
                  <dd style={{ fontSize: 11.5, color: "#2a2520", fontFamily: "var(--font-jetbrains, ui-monospace)", margin: 0 }}>
                    {reference!.lower_limit_m3_ha?.toFixed(2)} – {reference!.upper_limit_m3_ha?.toFixed(2)}
                  </dd>

                  <dt style={{ fontSize: 11.5, color: "#8a7f74", fontFamily: "var(--font-dm-sans, system-ui)" }}>Baseado em</dt>
                  <dd style={{ fontSize: 11.5, color: "#2a2520", fontFamily: "var(--font-dm-sans, system-ui)", margin: 0 }}>
                    {reference!.num_events_analyzed} evento{reference!.num_events_analyzed !== 1 ? "s" : ""}
                  </dd>
                </>
              )}
            </dl>

            {latestDeviationPct !== null && latestDeviationPct !== undefined && Math.abs(latestDeviationPct) > (reference?.tolerance_pct ?? 5) && (
              <div style={{
                marginTop: 10,
                padding: "6px 10px",
                background: "#fbf4ee",
                border: "1px solid rgba(184,74,42,0.2)",
                borderRadius: 6,
                fontSize: 11.5,
                color: "#b84a2a",
                fontFamily: "var(--font-dm-sans, system-ui)",
              }}>
                Último evento: {latestDeviationPct > 0 ? "+" : ""}{latestDeviationPct.toFixed(1)}% vs referência
              </div>
            )}

            {onRecompute && (
              <button
                onClick={(e) => { e.stopPropagation(); onRecompute(sectorId); setOpen(false); }}
                style={{
                  marginTop: 12,
                  width: "100%",
                  padding: "7px 0",
                  background: "transparent",
                  border: "1px solid #dcd3c2",
                  borderRadius: 6,
                  cursor: "pointer",
                  fontFamily: "var(--font-dm-sans, system-ui)",
                  fontSize: 12,
                  color: "#5a5048",
                }}
              >
                Recalcular referência
              </button>
            )}
          </div>
        </>
      )}
    </div>
  );
}
