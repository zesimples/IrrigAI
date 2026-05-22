"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { flowmeterApi, ApiError } from "@/lib/api";
import type { IrrigationEventOut } from "@/types";

interface Props { sectorId: string; farmId: string; }

export function FlowmeterInfoCard({ sectorId, farmId }: Props) {
  const [lastEvent, setLastEvent] = useState<IrrigationEventOut | null>(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    flowmeterApi.events(sectorId).then((r) => {
      if (r.events.length > 0) { setLastEvent(r.events[0]); setVisible(true); }
    }).catch((e: unknown) => {
      if (e instanceof ApiError && e.status === 404) return;
      console.error(e);
    });
  }, [sectorId]);

  if (!visible || !lastEvent) return null;

  const date = new Date(lastEvent.start_time).toLocaleDateString("pt-PT", { day: "2-digit", month: "2-digit" });

  return (
    <div className="mt-6 border border-rule-soft rounded-lg px-4 py-3 bg-surface-subtle flex items-center justify-between gap-4">
      <div>
        <p className="text-[10px] font-semibold text-ink-3 uppercase tracking-wide mb-0.5">Caudalímetro</p>
        <p className="text-sm text-ink-2">
          Última rega <span className="font-semibold text-ink-1">{date}</span>
          {" · "}
          <span className="font-semibold text-ink-1">{lastEvent.total_m3_ha.toFixed(1)} m³/ha</span>
        </p>
      </div>
      <Link href={`/farms/${farmId}/caudalimetros`} className="text-sm font-medium text-blue-600 whitespace-nowrap hover:underline">
        Ver histórico completo →
      </Link>
    </div>
  );
}
