"use client";

import { useCallback, useEffect, useState } from "react";
import { farmsApi } from "@/lib/api";
import type { DashboardResponse } from "@/types";

export function useFarmDashboard(farmId: string | null) {
  const [data, setData] = useState<DashboardResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetch = useCallback(async () => {
    if (!farmId) return;
    setLoading(true);
    setError(null);
    try {
      const d = await farmsApi.dashboard(farmId);
      setData(d);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao carregar dashboard");
    } finally {
      setLoading(false);
    }
  }, [farmId]);

  useEffect(() => {
    fetch();
  }, [fetch]);

  return { data, loading, error, refetch: fetch };
}
