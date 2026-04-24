"use client";

import { useCallback, useEffect, useState } from "react";
import { farmsApi, ApiError } from "@/lib/api";
import type { DashboardResponse } from "@/types";

const TIMEOUT_MS = 15_000;
const MAX_RETRIES = 2;

function withTimeout<T>(p: Promise<T>, ms: number): Promise<T> {
  return Promise.race([
    p,
    new Promise<never>((_, reject) =>
      setTimeout(() => reject(new Error("Tempo limite de resposta atingido")), ms),
    ),
  ]);
}

export function useFarmDashboard(farmId: string | null) {
  const [data, setData] = useState<DashboardResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetch = useCallback(async () => {
    if (!farmId) return;
    setLoading(true);
    setError(null);
    let lastErr = "Erro ao carregar dashboard";
    for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
      try {
        const d = await withTimeout(farmsApi.dashboard(farmId), TIMEOUT_MS);
        setData(d);
        setLoading(false);
        return;
      } catch (e) {
        lastErr = e instanceof Error ? e.message : lastErr;
        // Only retry on network failures or 5xx; stop on 4xx (auth, not found, etc.)
        const isRetryable = !(e instanceof ApiError) || e.status >= 500;
        if (isRetryable && attempt < MAX_RETRIES) {
          await new Promise((r) => setTimeout(r, 1200 * (attempt + 1)));
        } else {
          break;
        }
      }
    }
    setError(lastErr);
    setLoading(false);
  }, [farmId]);

  useEffect(() => {
    fetch();
  }, [fetch]);

  return { data, loading, error, refetch: fetch };
}
