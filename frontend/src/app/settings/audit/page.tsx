"use client";

import { useCallback, useEffect, useState } from "react";
import { auditApi } from "@/lib/api";
import { AppHeader } from "@/components/ui/AppHeader";
import { Card, CardBody } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ChevronDown, ChevronUp } from "lucide-react";
import type { AuditLog, PaginatedResponse } from "@/types";

const ACTION_LABELS: Record<string, string> = {
  recommendation_generated: "Recomendação gerada",
  recommendation_accepted: "Recomendação aceite",
  recommendation_rejected: "Recomendação rejeitada",
  recommendation_overridden: "Recomendação substituída",
  irrigation_logged: "Rega registada",
  sector_updated: "Sector actualizado",
  alert_acknowledged: "Alerta reconhecido",
  alert_resolved: "Alerta resolvido",
  override_created: "Substituição criada",
  override_removed: "Substituição removida",
  data_ingested: "Dados ingeridos",
};

const ENTITY_FILTERS = [
  { value: "", label: "Todos" },
  { value: "recommendation", label: "Recomendações" },
  { value: "alert", label: "Alertas" },
  { value: "sector_override", label: "Substituições" },
  { value: "irrigation_event", label: "Rega" },
];

export default function AuditLogPage() {
  const [data, setData] = useState<PaginatedResponse<AuditLog> | null>(null);
  const [loading, setLoading] = useState(true);
  const [entityType, setEntityType] = useState("");
  const [page, setPage] = useState(1);
  const [expanded, setExpanded] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const result = await auditApi.list({
        entity_type: entityType || undefined,
        page,
      });
      setData(result);
    } catch {
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [entityType, page]);

  useEffect(() => {
    load();
  }, [load]);

  function toggleExpand(id: string) {
    setExpanded((prev) => (prev === id ? null : id));
  }

  const totalPages = data ? Math.ceil(data.total / data.page_size) : 1;

  return (
    <div className="min-h-screen">
      <AppHeader crumbs={[{ label: "Auditoria" }]} />

      <main className="mx-auto max-w-5xl space-y-5 px-4 py-6 sm:px-6 animate-fade-in-up">
        <div>
          <h1 className="text-xl font-bold text-slate-900">
            Registo de auditoria
          </h1>
          <p className="mt-0.5 text-sm text-slate-500">
            Histórico de todas as acções realizadas no sistema.
          </p>
        </div>

        {/* Filters */}
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs font-semibold uppercase tracking-wide text-slate-400">
            Filtrar:
          </span>
          {ENTITY_FILTERS.map((f) => (
            <button
              key={f.value}
              onClick={() => {
                setEntityType(f.value);
                setPage(1);
              }}
              className={[
                "rounded-full px-3 py-1.5 text-xs font-semibold transition-colors",
                entityType === f.value
                  ? "bg-emerald-700 text-white"
                  : "border border-slate-200 bg-white text-slate-600 hover:bg-slate-50",
              ].join(" ")}
            >
              {f.label}
            </button>
          ))}
          {data && (
            <span className="ml-auto text-xs text-slate-400">
              {data.total} entradas
            </span>
          )}
        </div>

        <Card>
          <CardBody className="p-0">
            {loading ? (
              <div className="space-y-px p-4">
                {Array.from({ length: 8 }).map((_, i) => (
                  <div
                    key={i}
                    className="h-10 animate-pulse rounded-xl bg-slate-100"
                  />
                ))}
              </div>
            ) : !data || data.items.length === 0 ? (
              <p className="py-12 text-center text-sm text-slate-500">
                Sem entradas no registo de auditoria.
              </p>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-100">
                    <th className="px-5 pb-3 pt-4 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
                      Data/Hora
                    </th>
                    <th className="px-5 pb-3 pt-4 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
                      Acção
                    </th>
                    <th className="hidden px-5 pb-3 pt-4 text-left text-xs font-semibold uppercase tracking-wide text-slate-500 sm:table-cell">
                      Entidade
                    </th>
                    <th className="hidden px-5 pb-3 pt-4 text-left text-xs font-semibold uppercase tracking-wide text-slate-500 md:table-cell">
                      Utilizador
                    </th>
                    <th className="px-5 pb-3 pt-4 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
                      Detalhes
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-50">
                  {data.items.map((entry) => (
                    <>
                      <tr
                        key={entry.id}
                        className="transition-colors hover:bg-slate-50/60"
                      >
                        <td className="whitespace-nowrap px-5 py-3 text-xs text-slate-500">
                          {new Date(entry.created_at).toLocaleString("pt-PT", {
                            day: "numeric",
                            month: "short",
                            hour: "2-digit",
                            minute: "2-digit",
                          })}
                        </td>
                        <td className="px-5 py-3 font-medium text-slate-800">
                          {ACTION_LABELS[entry.action] ?? entry.action}
                        </td>
                        <td className="hidden px-5 py-3 sm:table-cell">
                          <Badge variant="muted">{entry.entity_type}</Badge>
                        </td>
                        <td className="hidden px-5 py-3 text-xs text-slate-500 md:table-cell">
                          {entry.user_id
                            ? entry.user_id.slice(0, 8) + "…"
                            : "Sistema"}
                        </td>
                        <td className="px-5 py-3">
                          {(entry.before_data || entry.after_data) && (
                            <button
                              onClick={() => toggleExpand(entry.id)}
                              className="inline-flex items-center gap-1 text-xs font-semibold text-emerald-700 hover:text-emerald-800"
                            >
                              {expanded === entry.id ? (
                                <>
                                  Ocultar
                                  <ChevronUp className="h-3.5 w-3.5" />
                                </>
                              ) : (
                                <>
                                  Ver
                                  <ChevronDown className="h-3.5 w-3.5" />
                                </>
                              )}
                            </button>
                          )}
                        </td>
                      </tr>
                      {expanded === entry.id && (
                        <tr key={`${entry.id}-detail`}>
                          <td colSpan={5} className="bg-slate-50/60 px-5 pb-4 pt-0">
                            <div className="grid gap-3 sm:grid-cols-2">
                              {entry.before_data && (
                                <div className="rounded-xl border border-red-100 bg-red-50 p-3">
                                  <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500">
                                    Antes
                                  </p>
                                  <pre className="overflow-auto text-xs text-slate-700">
                                    {JSON.stringify(entry.before_data, null, 2)}
                                  </pre>
                                </div>
                              )}
                              {entry.after_data && (
                                <div className="rounded-xl border border-emerald-100 bg-emerald-50 p-3">
                                  <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500">
                                    Depois
                                  </p>
                                  <pre className="overflow-auto text-xs text-slate-700">
                                    {JSON.stringify(entry.after_data, null, 2)}
                                  </pre>
                                </div>
                              )}
                            </div>
                          </td>
                        </tr>
                      )}
                    </>
                  ))}
                </tbody>
              </table>
            )}
          </CardBody>
        </Card>

        {/* Pagination */}
        {totalPages > 1 && (
          <div className="flex items-center justify-center gap-3">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page === 1}
              className="rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40"
            >
              ← Anterior
            </button>
            <span className="text-sm font-medium text-slate-500">
              {page} / {totalPages}
            </span>
            <button
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page === totalPages}
              className="rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40"
            >
              Seguinte →
            </button>
          </div>
        )}
      </main>
    </div>
  );
}
