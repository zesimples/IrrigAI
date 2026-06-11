"use client";

import { useState } from "react";
import { flowmeterApi } from "@/lib/api";
import type { FlowmeterReferenceOut } from "@/types";

interface Props {
  references: FlowmeterReferenceOut[];
  onUpdated: (ref: FlowmeterReferenceOut) => void;
}

const STATUS_LABEL: Record<string, string> = {
  established: "Estabelecido",
  provisional: "Provisional",
  insufficient: "Insuficiente",
};

const STATUS_COLOR: Record<string, string> = {
  established: "#4a8c4a",
  provisional: "#c9a34a",
  insufficient: "#8a7f74",
};

interface EditState {
  sectorId: string;
  field: "tolerance" | "manual";
  value: string;
}

export function FlowmeterReferenceManager({ references, onUpdated }: Props) {
  const [editing, setEditing] = useState<EditState | null>(null);
  const [saving, setSaving] = useState<string | null>(null);

  async function handleSaveManual(ref: FlowmeterReferenceOut, valueStr: string) {
    if (!ref.sector_id) return;
    const value = parseFloat(valueStr);
    if (isNaN(value) || value <= 0) return;
    setSaving(ref.sector_id);
    try {
      const updated = await flowmeterApi.setManualReference(ref.sector_id, {
        reference_rate_m3_ha: value,
        tolerance_pct: ref.tolerance_pct,
      });
      onUpdated(updated);
      setEditing(null);
    } catch (e) {
      console.error("Manual reference save failed:", e);
    } finally {
      setSaving(null);
    }
  }

  async function handleRecompute(ref: FlowmeterReferenceOut) {
    if (!ref.sector_id) return;
    setSaving(ref.sector_id);
    try {
      const updated = await flowmeterApi.recomputeReference(ref.sector_id);
      onUpdated(updated);
    } catch (e) {
      console.error("Recompute failed:", e);
    } finally {
      setSaving(null);
    }
  }

  const GRID = "1fr 80px 96px 80px 80px 96px 120px 60px 140px";

  return (
    <div>
      {/* Column headers */}
      <div style={{
        display: "grid",
        gridTemplateColumns: GRID,
        padding: "10px 18px",
        background: "#ece5d5",
        borderBottom: "1px solid #dcd3c2",
        fontFamily: "var(--font-jetbrains, ui-monospace)",
        fontSize: 9.5,
        color: "#8a7f74",
        letterSpacing: "0.14em",
        textTransform: "uppercase",
        gap: 8,
      }}>
        <div>Setor</div>
        <div>Cultura</div>
        <div>Referência</div>
        <div>Tolerância</div>
        <div>Limite inf.</div>
        <div>Limite sup.</div>
        <div>Estado</div>
        <div>Eventos</div>
        <div>Ações</div>
      </div>

      {references.map((ref, i) => {
        const isSaving = saving === ref.sector_id;
        const isEditingManual = editing?.sectorId === ref.sector_id && editing.field === "manual";
        const hasRef = ref.reference_rate_m3_ha !== null && ref.status !== "insufficient";

        return (
          <div
            key={ref.id}
            style={{
              display: "grid",
              gridTemplateColumns: GRID,
              padding: "10px 18px",
              gap: 8,
              alignItems: "center",
              borderBottom: "1px solid #e8e0d0",
              background: i % 2 === 1 ? "rgba(0,0,0,0.015)" : "transparent",
              opacity: isSaving ? 0.6 : 1,
            }}
          >
            {/* Setor */}
            <div style={{ fontFamily: "var(--font-fraunces)", fontSize: 13, fontWeight: 600, color: "#2a2520" }}>
              {ref.sector_name ?? "—"}
            </div>

            {/* Cultura */}
            <div style={{ fontFamily: "var(--font-instrument)", fontStyle: "italic", fontSize: 12, color: "#5a5048" }}>
              {ref.crop_type === "almond" ? "Amendoal" : ref.crop_type === "olive" ? "Olival" : ref.crop_type ?? "—"}
            </div>

            {/* Referência */}
            <div>
              {isEditingManual ? (
                <input
                  autoFocus
                  type="number"
                  step="0.01"
                  defaultValue={ref.reference_rate_m3_ha?.toFixed(2) ?? ""}
                  onBlur={(e) => handleSaveManual(ref, e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") { e.preventDefault(); handleSaveManual(ref, (e.target as HTMLInputElement).value); }
                    if (e.key === "Escape") { e.preventDefault(); setEditing(null); }
                  }}
                  style={{
                    width: 72,
                    padding: "3px 6px",
                    fontFamily: "var(--font-jetbrains, ui-monospace)",
                    fontSize: 12,
                    border: "1px solid #dcd3c2",
                    borderRadius: 4,
                    background: "#fff",
                    color: "#2a2520",
                  }}
                />
              ) : hasRef ? (
                <span style={{ fontFamily: "var(--font-fraunces)", fontSize: 14, fontWeight: 600, color: "#2a2520" }}>
                  {ref.reference_rate_m3_ha!.toFixed(2)}
                  <span style={{ fontFamily: "var(--font-jetbrains, ui-monospace)", fontSize: 9.5, color: "#8a7f74", marginLeft: 3 }}>m³/ha</span>
                  {ref.is_manual_override && (
                    <span style={{ marginLeft: 5, fontSize: 9, color: "#c9a34a", fontFamily: "var(--font-jetbrains, ui-monospace)" }}>manual</span>
                  )}
                </span>
              ) : (
                <span style={{ fontFamily: "var(--font-fraunces)", fontStyle: "italic", fontSize: 12, color: "#8a7f74" }}>—</span>
              )}
            </div>

            {/* Tolerância */}
            <div style={{ fontFamily: "var(--font-jetbrains, ui-monospace)", fontSize: 12, color: "#5a5048" }}>
              ±{ref.tolerance_pct}%
            </div>

            {/* Limite inf. */}
            <div style={{ fontFamily: "var(--font-jetbrains, ui-monospace)", fontSize: 12, color: "#5a5048" }}>
              {ref.lower_limit_m3_ha?.toFixed(2) ?? "—"}
            </div>

            {/* Limite sup. */}
            <div style={{ fontFamily: "var(--font-jetbrains, ui-monospace)", fontSize: 12, color: "#5a5048" }}>
              {ref.upper_limit_m3_ha?.toFixed(2) ?? "—"}
            </div>

            {/* Estado */}
            <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
              <span style={{
                width: 6,
                height: 6,
                borderRadius: 999,
                background: STATUS_COLOR[ref.status] ?? "#8a7f74",
                flexShrink: 0,
              }} />
              <span style={{ fontFamily: "var(--font-dm-sans, system-ui)", fontSize: 11.5, color: "#5a5048" }}>
                {STATUS_LABEL[ref.status] ?? ref.status}
              </span>
            </div>

            {/* Eventos */}
            <div style={{ fontFamily: "var(--font-jetbrains, ui-monospace)", fontSize: 12, color: "#5a5048" }}>
              {ref.num_events_analyzed}
            </div>

            {/* Ações */}
            <div style={{ display: "flex", gap: 6 }}>
              <button
                disabled={isSaving}
                onClick={() => setEditing({ sectorId: ref.sector_id!, field: "manual", value: "" })}
                style={{
                  padding: "4px 8px",
                  fontSize: 11,
                  fontFamily: "var(--font-dm-sans, system-ui)",
                  background: "transparent",
                  border: "1px solid #dcd3c2",
                  borderRadius: 5,
                  cursor: "pointer",
                  color: "#5a5048",
                }}
              >
                Manual
              </button>
              <button
                disabled={isSaving}
                onClick={() => handleRecompute(ref)}
                style={{
                  padding: "4px 8px",
                  fontSize: 11,
                  fontFamily: "var(--font-dm-sans, system-ui)",
                  background: "transparent",
                  border: "1px solid #dcd3c2",
                  borderRadius: 5,
                  cursor: "pointer",
                  color: "#5a5048",
                }}
              >
                {isSaving ? "…" : "Recalc."}
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}
