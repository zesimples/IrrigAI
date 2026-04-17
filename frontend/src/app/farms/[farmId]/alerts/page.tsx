"use client";

import { useEffect, useState } from "react";
import { alertsApi } from "@/lib/api";
import type { Alert } from "@/types";
import { Button } from "@/components/ui/button";
import { AppHeader } from "@/components/ui/AppHeader";
import {
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  Info,
  RefreshCw,
} from "lucide-react";

interface Props {
  params: { farmId: string };
}

const SEVERITY_CONFIG = {
  critical: {
    Icon: AlertCircle,
    border: "border-l-red-500",
    iconBg: "bg-red-100",
    iconColor: "text-red-600",
    label: "Crítico",
    badge: "bg-red-100 text-red-700",
  },
  warning: {
    Icon: AlertTriangle,
    border: "border-l-amber-400",
    iconBg: "bg-amber-100",
    iconColor: "text-amber-600",
    label: "Aviso",
    badge: "bg-amber-100 text-amber-700",
  },
  info: {
    Icon: Info,
    border: "border-l-blue-400",
    iconBg: "bg-blue-100",
    iconColor: "text-blue-600",
    label: "Info",
    badge: "bg-blue-100 text-blue-700",
  },
};

export default function AlertsPage({ params }: Props) {
  const { farmId } = params;
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [loading, setLoading] = useState(true);
  const [resolving, setResolving] = useState<string | null>(null);
  const [resolvingAll, setResolvingAll] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    try {
      setError(null);
      const data = await alertsApi.listFarm(farmId);
      setAlerts(data.items.filter((a) => a.is_active));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao carregar alertas.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, [farmId]); // eslint-disable-line react-hooks/exhaustive-deps

  async function resolve(id: string) {
    setResolving(id);
    try {
      await alertsApi.resolve(id);
      setAlerts((prev) => prev.filter((a) => a.id !== id));
    } finally {
      setResolving(null);
    }
  }

  async function resolveAll() {
    setResolvingAll(true);
    try {
      await alertsApi.resolveAll(farmId);
      setAlerts([]);
    } finally {
      setResolvingAll(false);
    }
  }

  return (
    <div className="min-h-screen">
      <AppHeader
        crumbs={[
          { label: "Dashboard", href: `/farms/${farmId}` },
          { label: "Alertas" },
        ]}
      />

      <main className="mx-auto max-w-3xl px-4 py-6 sm:px-6 animate-fade-in-up">
        {/* Page title */}
        <div className="mb-6">
          <h1 className="text-xl font-bold text-slate-900">Alertas activos</h1>
          <p className="mt-0.5 text-sm text-slate-500">
            Acompanhe e resolva os alertas operacionais desta exploração.
          </p>
        </div>

        {/* Loading */}
        {loading && (
          <div className="space-y-3">
            {[0, 1, 2].map((i) => (
              <div
                key={i}
                className="h-24 animate-pulse rounded-2xl bg-white/90 shadow-sm"
              />
            ))}
          </div>
        )}

        {/* Error */}
        {!loading && error && (
          <div className="rounded-2xl border border-red-200 bg-red-50 px-5 py-5">
            <p className="font-semibold text-red-900">
              Não foi possível carregar os alertas
            </p>
            <p className="mt-0.5 text-sm text-red-700">{error}</p>
            <Button
              variant="secondary"
              size="sm"
              className="mt-3"
              onClick={() => {
                setLoading(true);
                load();
              }}
            >
              <RefreshCw className="h-3.5 w-3.5" />
              Tentar novamente
            </Button>
          </div>
        )}

        {/* Empty state */}
        {!loading && !error && alerts.length === 0 && (
          <div className="rounded-3xl border-2 border-dashed border-slate-200 bg-white/60 px-6 py-16 text-center">
            <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-emerald-50">
              <CheckCircle2 className="h-7 w-7 text-emerald-600" />
            </div>
            <p className="font-semibold text-slate-900">Sem alertas activos</p>
            <p className="mt-1 text-sm text-slate-500">
              Tudo em ordem para esta exploração.
            </p>
          </div>
        )}

        {/* Alert list */}
        {!loading && !error && alerts.length > 0 && (
          <div className="space-y-3">
            {alerts.length > 1 && (
              <div className="flex justify-end">
                <Button
                  variant="secondary"
                  size="sm"
                  loading={resolvingAll}
                  onClick={resolveAll}
                >
                  Resolver todos ({alerts.length})
                </Button>
              </div>
            )}

            {alerts.map((a) => {
              const sev =
                SEVERITY_CONFIG[
                  a.severity as keyof typeof SEVERITY_CONFIG
                ] ?? SEVERITY_CONFIG.info;
              const SevIcon = sev.Icon;

              return (
                <div
                  key={a.id}
                  className={`flex items-start gap-4 overflow-hidden rounded-2xl border border-slate-200 border-l-4 bg-white px-5 py-4 shadow-sm ${sev.border}`}
                >
                  <div
                    className={`mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl ${sev.iconBg}`}
                  >
                    <SevIcon className={`h-4.5 w-4.5 ${sev.iconColor}`} />
                  </div>

                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span
                        className={`rounded-full px-2 py-0.5 text-xs font-semibold ${sev.badge}`}
                      >
                        {sev.label}
                      </span>
                      <p className="font-semibold text-slate-900">{a.title_pt}</p>
                    </div>
                    {a.description_pt && (
                      <p className="mt-1.5 text-sm text-slate-600">
                        {a.description_pt}
                      </p>
                    )}
                    <p className="mt-2 text-xs text-slate-400">
                      {new Date(a.created_at).toLocaleString("pt-PT", {
                        day: "numeric",
                        month: "short",
                        hour: "2-digit",
                        minute: "2-digit",
                      })}
                    </p>
                  </div>

                  <Button
                    size="sm"
                    variant="secondary"
                    loading={resolving === a.id}
                    onClick={() => resolve(a.id)}
                    className="shrink-0"
                  >
                    Resolver
                  </Button>
                </div>
              );
            })}
          </div>
        )}
      </main>
    </div>
  );
}
