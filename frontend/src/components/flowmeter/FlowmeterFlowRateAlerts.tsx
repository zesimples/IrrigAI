"use client";

import type { FlowmeterFlowRateAlert } from "@/types";

import { formatDecimal } from "@/lib/utils";

interface Props {
  alerts: FlowmeterFlowRateAlert[];
  loading: boolean;
}

function fmtDate(iso: string | null): string {
  if (!iso) return "";
  return new Date(iso).toLocaleString("pt-PT", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function AlertRow({ alert }: { alert: FlowmeterFlowRateAlert }) {
  const isWarning = alert.severity === "warning";
  const isHigh = alert.alert_type === "flowmeter_flow_rate_high";
  const isLow = alert.alert_type === "flowmeter_flow_rate_low";

  const icon = isWarning ? "⚠" : "ℹ";
  const color = isWarning ? "#b84a2a" : "#6b7280";
  const bgColor = isWarning ? "rgba(184,74,42,0.04)" : "rgba(107,114,128,0.04)";

  const deviationLabel =
    isHigh && alert.data?.deviation_pct
      ? `Caudal ${alert.data.deviation_pct > 0 ? "+" : ""}${formatDecimal(alert.data.deviation_pct, 1)}% vs ref. ${(alert.data.reference_rate_m3_ha != null ? formatDecimal(alert.data.reference_rate_m3_ha, 2) : undefined)} m³/ha`
      : isLow && alert.data?.deviation_pct
      ? `Caudal ${formatDecimal(alert.data.deviation_pct, 1)}% vs ref. ${(alert.data.reference_rate_m3_ha != null ? formatDecimal(alert.data.reference_rate_m3_ha, 2) : undefined)} m³/ha`
      : alert.data?.zero_count
      ? `${alert.data.zero_count} leitura(s) a zero`
      : "";

  return (
    <div style={{
      padding: "12px 16px",
      borderBottom: "1px solid #ece5d5",
      background: bgColor,
      display: "grid",
      gridTemplateColumns: "20px 1fr auto",
      gap: 10,
      alignItems: "start",
    }}>
      <span style={{ fontSize: 14, color, marginTop: 1 }}>{icon}</span>
      <div>
        <div style={{
          fontFamily: "var(--font-dm-sans, system-ui)",
          fontSize: 13,
          fontWeight: 500,
          color: "#2a2520",
          marginBottom: 2,
        }}>
          {alert.title_pt}
        </div>
        {deviationLabel && (
          <div style={{
            fontFamily: "var(--font-jetbrains, ui-monospace)",
            fontSize: 11,
            color,
            marginBottom: 3,
          }}>
            {deviationLabel}
          </div>
        )}
        <div style={{
          fontFamily: "var(--font-dm-sans, system-ui)",
          fontSize: 11.5,
          color: "#6b5f54",
          lineHeight: 1.4,
        }}>
          {alert.description_pt}
        </div>
      </div>
      <div style={{
        fontFamily: "var(--font-jetbrains, ui-monospace)",
        fontSize: 10.5,
        color: "#8a7f74",
        whiteSpace: "nowrap",
        paddingTop: 2,
      }}>
        {fmtDate(alert.data?.event_start_time ?? alert.created_at)}
      </div>
    </div>
  );
}

export function FlowmeterFlowRateAlerts({ alerts, loading }: Props) {
  if (loading) {
    return (
      <div style={{ padding: "24px", color: "#8a7f74", fontFamily: "var(--font-dm-sans, system-ui)", fontSize: 13 }}>
        A carregar alertas…
      </div>
    );
  }

  if (alerts.length === 0) {
    return (
      <div style={{ padding: "24px 16px", textAlign: "center" }}>
        <span style={{ fontFamily: "var(--font-fraunces)", fontStyle: "italic", fontSize: 13, color: "#8a7f74" }}>
          Nenhum alerta de caudal nos últimos 30 dias.
        </span>
      </div>
    );
  }

  return (
    <div>
      {alerts.map((a) => <AlertRow key={a.id} alert={a} />)}
    </div>
  );
}
