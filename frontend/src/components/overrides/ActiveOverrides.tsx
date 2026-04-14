"use client";

import { useCallback, useEffect, useState } from "react";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { overridesApi } from "@/lib/api";
import type { SectorOverride } from "@/types";

const TYPE_LABELS: Record<string, string> = {
  fixed_depth: "Dose fixa",
  fixed_runtime: "Duração fixa",
  skip: "Forçar não rega",
  force_irrigate: "Forçar rega",
};

const STRATEGY_LABELS: Record<string, string> = {
  one_time: "Uma vez",
  until_next_stage: "Até próxima fase",
};

interface ActiveOverridesProps {
  sectorId: string;
}

export function ActiveOverrides({ sectorId }: ActiveOverridesProps) {
  const [overrides, setOverrides] = useState<SectorOverride[]>([]);
  const [loading, setLoading] = useState(true);
  const [removing, setRemoving] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await overridesApi.list(sectorId);
      setOverrides(data);
    } catch {
      setOverrides([]);
    } finally {
      setLoading(false);
    }
  }, [sectorId]);

  useEffect(() => { load(); }, [load]);

  async function removeOverride(id: string) {
    setRemoving(id);
    try {
      await overridesApi.remove(id);
      await load();
    } finally {
      setRemoving(null);
    }
  }

  if (loading) return null;
  if (overrides.length === 0) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Substituições activas ({overrides.length})</CardTitle>
      </CardHeader>
      <CardBody>
        <ul className="divide-y divide-gray-50">
          {overrides.map((ov) => (
            <li key={ov.id} className="flex items-start justify-between gap-4 py-3">
              <div className="flex-1 min-w-0">
                <div className="flex flex-wrap items-center gap-1.5 mb-1">
                  <Badge variant="warning">{TYPE_LABELS[ov.override_type] ?? ov.override_type}</Badge>
                  <span className="text-xs text-gray-400">{STRATEGY_LABELS[ov.override_strategy] ?? ov.override_strategy}</span>
                  {ov.value != null && (
                    <span className="text-xs text-gray-600 font-medium">{ov.value} mm</span>
                  )}
                </div>
                <p className="text-sm text-gray-700 truncate">{ov.reason}</p>
                <p className="text-xs text-gray-400 mt-0.5">
                  Criado em {new Date(ov.created_at).toLocaleDateString("pt-PT")}
                  {ov.valid_until && ` · Válido até ${ov.valid_until}`}
                </p>
              </div>
              <Button
                size="sm"
                variant="danger"
                loading={removing === ov.id}
                onClick={() => removeOverride(ov.id)}
              >
                Remover
              </Button>
            </li>
          ))}
        </ul>
      </CardBody>
    </Card>
  );
}
