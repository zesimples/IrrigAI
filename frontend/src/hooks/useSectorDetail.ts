"use client";

import { useCallback, useEffect, useState } from "react";
import { sectorsApi } from "@/lib/api";
import type { SectorStatus } from "@/types";

export function useSectorStatus(sectorId: string | null) {
  const [data, setData] = useState<SectorStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetch = useCallback(async () => {
    if (!sectorId) return;
    setLoading(true);
    setError(null);
    try {
      const d = await sectorsApi.getStatus(sectorId);
      setData(d);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao carregar sector");
    } finally {
      setLoading(false);
    }
  }, [sectorId]);

  useEffect(() => {
    fetch();
  }, [fetch]);

  return { data, loading, error, refetch: fetch };
}
