"use client";

import { useCallback, useEffect, useState } from "react";
import { probesApi } from "@/lib/api";
import type { ProbeReadingsResponse } from "@/types";

interface UseProbeReadingsParams {
  probeId: string | null;
  since?: string;
  until?: string;
  depthCm?: string;
  interval?: string;
}

export function useProbeReadings({
  probeId,
  since,
  until,
  depthCm,
  interval,
}: UseProbeReadingsParams) {
  const [data, setData] = useState<ProbeReadingsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetch = useCallback(async () => {
    if (!probeId) return;
    setLoading(true);
    setError(null);
    try {
      const d = await probesApi.readings(probeId, {
        since,
        until,
        depth_cm: depthCm,
        interval,
      });
      setData(d);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao carregar leituras");
    } finally {
      setLoading(false);
    }
  }, [probeId, since, until, depthCm, interval]);

  useEffect(() => {
    fetch();
  }, [fetch]);

  return { data, loading, error, refetch: fetch };
}
