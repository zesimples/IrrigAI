"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { chatApi } from "@/lib/api";
import type {
  AgronomicEvidence,
  ChatConversation,
  FeedbackReason,
  ProposedActionOut,
} from "@/types";

interface Message {
  id?: string;
  role: "user" | "assistant";
  text: string;
  proposedAction?: ProposedActionOut | null;
  degraded?: boolean;
  feedback?: -1 | 1;
  evidence?: AgronomicEvidence[];
  contextVersion?: string | null;
  contractVersion?: string | null;
  validationStatus?: "validated" | "repaired" | "fallback";
  status?: "complete" | "interrupted" | "failed";
  /** Historical turns keep the date they were answered on. */
  createdAt?: string;
}

interface QuickAction {
  label: string;
  kind: "farm_summary" | "explain_sector" | "missing_data";
}

interface ChatPanelProps {
  farmId: string;
  sectorId?: string;
  onClose: () => void;
  /** Fired after a confirmed action actually wrote, so the page can re-read the
   *  recommendation it changed. The transcript itself is updated in place. */
  onActionCompleted?: () => void;
}

const FEEDBACK_REASONS: { value: FeedbackReason; label: string }[] = [
  { value: "wrong_data", label: "Dados errados" },
  { value: "stale_answer", label: "Resposta desactualizada" },
  { value: "unclear_explanation", label: "Explicação pouco clara" },
  { value: "unhelpful_next_step", label: "Próximo passo inútil" },
];

/** Statuses that must never render a Confirmar button again. */
const RESOLVED_ACTION_STATUSES = new Set([
  "succeeded",
  "cancelled",
  "invalidated",
  "legacy",
  "confirmed",
]);

const ACTION_STATUS_LABEL: Record<string, string> = {
  succeeded: "Acção executada.",
  failed: "A acção falhou — podes tentar novamente.",
  cancelled: "Acção cancelada.",
  invalidated: "Proposta já não válida — pede uma nova ao assistente.",
  confirmed: "A executar…",
  legacy: "Proposta anterior — o resultado não ficou registado. Pede uma nova.",
};

function newTurnId(): string {
  return `turn-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

export function ChatPanel({
  farmId,
  sectorId,
  onClose,
  onActionCompleted,
}: ChatPanelProps) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [progress, setProgress] = useState<string>("");
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [conversations, setConversations] = useState<ChatConversation[]>([]);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [feedbackFor, setFeedbackFor] = useState<number | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  // Guards the resume fetch below from clobbering a send that started in this
  // scope before the fetch resolved — without it, the resume's setMessages
  // can overwrite an in-flight/completed turn and fork a second conversation.
  const hasSentRef = useRef(false);
  // A turn identity the server can dedupe on, so a retry after a dropped
  // connection resumes the same turn instead of asking the model twice.
  const pendingTurnRef = useRef<{ id: string; text: string } | null>(null);
  const generationRef = useRef(0);
  const abortRef = useRef<AbortController | null>(null);

  const loadConversation = useCallback(
    async (id: string) => {
      const generation = ++generationRef.current;
      const detail = await chatApi.conversation(farmId, id);
      if (generation !== generationRef.current) return;
      pendingTurnRef.current = null;
      setConversationId(detail.id);
      setMessages(
        detail.messages.map((message) => ({
          id: message.id,
          role: message.role,
          text: message.content,
          proposedAction: message.proposed_action,
          degraded: message.degraded,
          evidence: message.evidence,
          contextVersion: message.context_version,
          contractVersion: message.contract_version,
          validationStatus: message.validation_status,
          status: message.status,
          createdAt: message.created_at,
        })),
      );
    },
    [farmId],
  );

  useEffect(() => {
    let cancelled = false;
    // Farm/sector are the conversation's scope key. Next.js can keep this
    // component mounted across a param-only navigation, so state from the
    // previous scope must not leak into the new one.
    hasSentRef.current = false;
    generationRef.current += 1;
    pendingTurnRef.current = null;
    setLoading(false);
    setConversationId(null);
    setMessages([]);
    setConversations([]);
    setPickerOpen(false);
    if (typeof chatApi.conversations !== "function") return;
    chatApi
      .conversations(farmId)
      .then((rows) => {
        if (cancelled) return;
        setConversations(rows);
        const scoped = rows.find((row) => row.sector_id === (sectorId ?? null));
        if (!scoped || hasSentRef.current) return;
        return loadConversation(scoped.id).catch(() => {});
      })
      .catch(() => {
        // Chat history is helpful but non-blocking.
      });
    return () => {
      cancelled = true;
      generationRef.current += 1;
      // Navigating away must not leave a stream writing into a dead component.
      abortRef.current?.abort();
    };
  }, [farmId, sectorId, loadConversation]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const pushAssistant = (text: string) =>
    setMessages((prev) => [...prev, { role: "assistant", text }]);

  const pushUser = (text: string) =>
    setMessages((prev) => [...prev, { role: "user", text }]);

  const quickActions: QuickAction[] = [
    { label: "Resumo do dia", kind: "farm_summary" },
    ...(sectorId
      ? [{ label: "Explicar recomendação", kind: "explain_sector" as const }]
      : []),
    { label: "O que falta configurar?", kind: "missing_data" },
  ];

  async function runQuickAction(action: QuickAction) {
    if (loading) return;
    hasSentRef.current = true;
    const generation = ++generationRef.current;
    pushUser(action.label);
    setLoading(true);
    try {
      // Quick actions run server-side so their result lands in the conversation
      // with its context, degraded status, and feedback — not only in this tab.
      const result = await chatApi.quickAction(farmId, {
        kind: action.kind,
        sector_id: sectorId ?? null,
        conversation_id: conversationId,
      });
      if (generation !== generationRef.current) return;
      setConversationId(result.conversation_id);
      setMessages((prev) => [
        ...prev,
        {
          id: result.message_id,
          role: "assistant",
          text: result.reply,
          degraded: result.degraded,
          evidence: result.evidence,
          contextVersion: result.context_version,
          contractVersion: result.contract_version,
        },
      ]);
    } catch (e) {
      if (generation !== generationRef.current) return;
      const detail = e instanceof Error ? e.message : "Erro desconhecido";
      pushAssistant(`Não foi possível completar esta acção: ${detail}. Tente novamente.`);
    } finally {
      if (generation === generationRef.current) setLoading(false);
    }
  }

  async function sendMessage() {
    const text = input.trim();
    if (!text || loading) return;
    hasSentRef.current = true;
    const generation = ++generationRef.current;
    const retry = pendingTurnRef.current?.text === text;
    const turnId = retry ? pendingTurnRef.current!.id : newTurnId();
    pendingTurnRef.current = { id: turnId, text };
    setInput("");
    if (!retry) pushUser(text);
    setMessages((prev) => retry
      ? [...prev.slice(0, -1), { role: "assistant", text: "" }]
      : [...prev, { role: "assistant", text: "" }]);
    setLoading(true);
    setProgress("");
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      const r = await chatApi.streamChat(
        farmId,
        {
          message: text,
          sector_id: sectorId ?? null,
          conversation_id: conversationId,
          client_message_id: turnId,
        },
        {
          onConversation: (nextConversationId, messageId) => {
            if (generation !== generationRef.current) return;
            setConversationId(nextConversationId);
            setMessages((prev) =>
              prev.map((message, index) =>
                index === prev.length - 1 ? { ...message, id: messageId } : message,
              ),
            );
          },
          onProgress: (label) => { if (generation === generationRef.current) setProgress(label); },
          onDelta: (delta) => {
            if (generation !== generationRef.current) return;
            setMessages((prev) =>
              prev.map((message, index) =>
                index === prev.length - 1
                  ? { ...message, text: message.text + delta }
                  : message,
              ),
            );
          },
        },
        controller.signal,
      );
      if (generation !== generationRef.current) return;
      // The turn completed; a later send starts a new identity.
      pendingTurnRef.current = null;
      setConversationId(r.conversation_id);
      setMessages((prev) =>
        prev.map((message, index) =>
          index === prev.length - 1
            ? {
                ...message,
                id: r.message_id,
                text: r.reply || message.text,
                proposedAction: r.proposed_action,
                degraded: r.degraded,
                evidence: r.evidence,
                contextVersion: r.context_version,
                contractVersion: r.contract_version,
                validationStatus: r.validation_status,
                status: r.status,
              }
            : message,
        ),
      );
    } catch (e) {
      if (generation !== generationRef.current) return;
      setInput(text);
      const aborted = e instanceof DOMException && e.name === "AbortError";
      const detail = e instanceof Error ? e.message : "Erro desconhecido";
      setMessages((prev) =>
        prev.map((message, index) =>
          index === prev.length - 1
            ? {
                ...message,
                text: aborted
                  ? "Resposta interrompida. Envia de novo para retomar."
                  : `Erro ao contactar o assistente: ${detail}. Tente novamente.`,
                degraded: true,
                status: "interrupted",
              }
            : message,
        ),
      );
    } finally {
      if (generation === generationRef.current) {
        setLoading(false);
        setProgress("");
        abortRef.current = null;
      }
    }
  }

  function updateAction(index: number, action: ProposedActionOut) {
    setMessages((prev) =>
      prev.map((m, i) => (i === index ? { ...m, proposedAction: action } : m)),
    );
  }

  async function confirmAction(index: number, action: ProposedActionOut) {
    if (!action.action_id) return;
    const generation = generationRef.current;
    setLoading(true);
    try {
      // The server revalidates permissions, scope and recommendation freshness,
      // executes once, and records the outcome. The client only reports it.
      const result = await chatApi.confirmAction(farmId, action.action_id);
      if (generation !== generationRef.current) return;
      // The card carries the outcome; the server has already persisted the
      // matching conversation event, so a reopened transcript shows it too.
      updateAction(index, { ...action, status: result.status, error_detail: result.error_detail });
      if (result.status === "succeeded") onActionCompleted?.();
    } catch (e) {
      if (generation !== generationRef.current) return;
      const body = (e as { body?: { status?: ProposedActionOut["status"] } }).body;
      const detail = e instanceof Error ? e.message : "Erro desconhecido";
      updateAction(index, { ...action, status: body?.status ?? "failed", error_detail: detail });
    } finally {
      if (generation === generationRef.current) setLoading(false);
    }
  }

  async function cancelAction(index: number, action: ProposedActionOut) {
    const generation = generationRef.current;
    if (!action.action_id) {
      updateAction(index, { ...action, status: "cancelled" });
      return;
    }
    try {
      const result = await chatApi.cancelAction(farmId, action.action_id);
      if (generation !== generationRef.current) return;
      updateAction(index, { ...action, status: result.status });
    } catch (e) {
      if (generation !== generationRef.current) return;
      const body = (e as { body?: { status?: ProposedActionOut["status"] } }).body;
      updateAction(index, { ...action, status: body?.status ?? action.status, error_detail: e instanceof Error ? e.message : "Não foi possível cancelar. Tenta novamente." });
    }
  }

  async function sendFeedback(
    index: number,
    message: Message,
    rating: -1 | 1,
    reason?: FeedbackReason,
  ) {
    if (!message.id || message.feedback) return;
    const generation = generationRef.current;
    setMessages((prev) =>
      prev.map((item, itemIndex) =>
        itemIndex === index ? { ...item, feedback: rating } : item,
      ),
    );
    setFeedbackFor(null);
    try {
      await chatApi.feedback({
        surface: "chat",
        rating,
        farm_id: farmId,
        chat_message_id: message.id,
        entity_id: sectorId,
        reason,
        // Ties the vote to the exact answer version it was cast against.
        context_version: message.contextVersion ?? undefined,
        contract_version: message.contractVersion ?? undefined,
      });
    } catch {
      if (generation !== generationRef.current) return;
      setMessages((prev) =>
        prev.map((item, itemIndex) =>
          itemIndex === index ? { ...item, feedback: undefined } : item,
        ),
      );
    }
  }

  return (
    <div className="fixed bottom-20 right-4 z-50 flex h-[min(540px,calc(100vh-7rem))] w-[min(24rem,calc(100vw-2rem))] flex-col rounded-[1.75rem] border border-slate-200 bg-white shadow-2xl sm:right-6">
      {/* Header */}
      <div className="flex items-center justify-between rounded-t-[1.75rem] bg-emerald-700 px-4 py-3">
        <div>
          <p className="text-sm font-semibold text-white">Assistente IrrigAI</p>
          <p className="text-xs text-emerald-200">Dados da exploração em contexto</p>
        </div>
        <div className="flex items-center gap-1">
          {conversations.length > 0 && (
            <button
              type="button"
              onClick={() => setPickerOpen((open) => !open)}
              aria-label="Conversas anteriores"
              className="rounded-full px-2 py-1 text-xs text-emerald-100 hover:bg-emerald-600"
            >
              Histórico
            </button>
          )}
          {messages.length > 0 && (
            <button
              type="button"
              onClick={() => {
                setConversationId(null);
                setMessages([]);
                pendingTurnRef.current = null;
              }}
              className="rounded-full px-2 py-1 text-xs text-emerald-100 hover:bg-emerald-600"
            >
              Nova
            </button>
          )}
          <button
            onClick={onClose}
            className="rounded-full p-1 text-white hover:bg-emerald-600"
            aria-label="Fechar"
          >
            ✕
          </button>
        </div>
      </div>

      {/* Conversation picker */}
      {pickerOpen && (
        <div className="max-h-40 overflow-y-auto border-b border-slate-100 bg-slate-50 px-3 py-2">
          <p className="mb-1 text-[10px] font-medium uppercase tracking-wide text-slate-500">
            Conversas anteriores
          </p>
          <ul className="space-y-1">
            {conversations.map((conversation) => (
              <li key={conversation.id}>
                <button
                  type="button"
                  onClick={() => {
                    hasSentRef.current = true;
                    setPickerOpen(false);
                    loadConversation(conversation.id).catch(() => {});
                  }}
                  className="w-full rounded-lg px-2 py-1 text-left text-xs text-slate-700 hover:bg-white"
                >
                  <span className="block truncate">{conversation.title ?? "Conversa"}</span>
                  <span className="text-[10px] text-slate-400">
                    {new Date(conversation.last_message_at).toLocaleDateString("pt-PT")}
                    {conversation.sector_id ? " · sector" : " · exploração"}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Quick actions */}
      {messages.length === 0 && (
        <div className="border-b border-slate-100 px-3 py-3">
          <p className="mb-1.5 text-xs font-medium uppercase tracking-wide text-slate-500">Acções rápidas</p>
          <div className="flex flex-wrap gap-1.5">
            {quickActions.map((qa) => (
              <button
                key={qa.label}
                onClick={() => runQuickAction(qa)}
                disabled={loading}
                className="rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-1.5 text-xs font-medium text-emerald-800 hover:bg-emerald-100 disabled:opacity-50"
              >
                {qa.label}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Messages */}
      <div className="flex-1 space-y-3 overflow-y-auto px-3 py-3">
        {messages.length === 0 && (
          <p className="mt-6 text-center text-xs text-slate-400">
            Faça uma pergunta ou escolha uma acção rápida acima.
          </p>
        )}
        {messages.map((msg, i) => (
          <div key={i} className={`flex flex-col ${msg.role === "user" ? "items-end" : "items-start"}`}>
            <div
              className={`max-w-[85%] rounded-2xl px-3 py-2 text-sm whitespace-pre-wrap ${
                msg.role === "user" ? "bg-emerald-700 text-white" : "bg-slate-100 text-slate-800"
              }`}
            >
              {msg.text || "A preparar resposta…"}
            </div>
            {msg.role === "assistant" && msg.createdAt && (
              <p className="mt-0.5 text-[10px] text-slate-400">
                {new Date(msg.createdAt).toLocaleString("pt-PT")}
              </p>
            )}
            {msg.role === "assistant" && msg.status === "interrupted" && (
              <p className="mt-1 max-w-[85%] text-[10px] text-amber-700">
                Resposta interrompida — não é uma resposta completa.
              </p>
            )}
            {msg.role === "assistant" && msg.validationStatus === "fallback" && (
              <p className="mt-1 max-w-[85%] text-[10px] text-amber-700">
                Resposta determinística — a explicação gerada não ficou sustentada pelos dados.
              </p>
            )}
            {msg.role === "assistant" && msg.degraded && (
              <p className="mt-1 max-w-[85%] text-[10px] text-amber-700">
                Resposta de contingência — o serviço de IA não estava disponível.
              </p>
            )}
            {msg.role === "assistant" && msg.evidence && msg.evidence.length > 0 && (
              <ul className="mt-1 max-w-[85%] space-y-0.5">
                {msg.evidence.map((ev) => (
                  <li key={ev.evidence_id || ev.source} className="text-[10px] text-slate-500">
                    <span className="font-medium text-slate-600">{ev.label}:</span> {ev.value}
                  </li>
                ))}
              </ul>
            )}
            {msg.proposedAction && (
              <div className="mt-2 max-w-[85%] rounded-xl border border-amber-300 bg-amber-50 px-3 py-2 text-sm">
                <p className="mb-2 font-medium text-amber-900">{msg.proposedAction.summary}</p>
                {RESOLVED_ACTION_STATUSES.has(msg.proposedAction.status) ? (
                  <p className="text-xs text-amber-800">
                    {ACTION_STATUS_LABEL[msg.proposedAction.status] ?? msg.proposedAction.status}
                  </p>
                ) : (
                  <>
                    {msg.proposedAction.status === "failed" && (
                      <p className="mb-1 text-xs text-red-700">
                        {ACTION_STATUS_LABEL.failed}
                        {msg.proposedAction.error_detail
                          ? ` (${msg.proposedAction.error_detail})`
                          : ""}
                      </p>
                    )}
                    <div className="flex gap-2">
                      <button
                        onClick={() => confirmAction(i, msg.proposedAction!)}
                        disabled={loading || !msg.proposedAction.action_id}
                        className="rounded-full bg-emerald-700 px-3 py-1 text-xs font-medium text-white hover:bg-emerald-600 disabled:opacity-50"
                      >
                        Confirmar
                      </button>
                      <button
                        onClick={() => cancelAction(i, msg.proposedAction!)}
                        disabled={loading}
                        className="rounded-full border border-slate-300 px-3 py-1 text-xs font-medium text-slate-700 hover:bg-slate-100 disabled:opacity-50"
                      >
                        Cancelar
                      </button>
                    </div>
                  </>
                )}
              </div>
            )}
            {msg.role === "assistant" && msg.id && msg.text && (
              <div className="mt-1 flex flex-wrap items-center gap-1">
                <button
                  type="button"
                  aria-label="Resposta útil"
                  onClick={() => sendFeedback(i, msg, 1)}
                  className={`rounded px-1.5 py-0.5 text-xs ${
                    msg.feedback === 1 ? "bg-emerald-100" : "text-slate-400"
                  }`}
                >
                  👍
                </button>
                <button
                  type="button"
                  aria-label="Resposta pouco útil"
                  onClick={() => setFeedbackFor(feedbackFor === i ? null : i)}
                  className={`rounded px-1.5 py-0.5 text-xs ${
                    msg.feedback === -1 ? "bg-amber-100" : "text-slate-400"
                  }`}
                >
                  👎
                </button>
                {feedbackFor === i && (
                  <div className="flex flex-wrap gap-1">
                    {FEEDBACK_REASONS.map((reason) => (
                      <button
                        key={reason.value}
                        type="button"
                        onClick={() => sendFeedback(i, msg, -1, reason.value)}
                        className="rounded-full border border-slate-200 px-2 py-0.5 text-[10px] text-slate-600 hover:bg-slate-100"
                      >
                        {reason.label}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
        {loading && (
          <div className="flex justify-start">
            <div className="rounded-2xl bg-slate-100 px-3 py-2 text-sm text-slate-500">
              <span className="animate-pulse">{progress || "A pensar…"}</span>
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="flex items-center gap-2 border-t border-slate-100 px-3 py-3">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && sendMessage()}
          placeholder="Escreva uma pergunta…"
          disabled={loading}
          className="flex-1 rounded-full border border-slate-200 bg-slate-50 px-3 py-2 text-sm outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500 disabled:opacity-50"
        />
        {loading ? (
          <button
            onClick={() => abortRef.current?.abort()}
            className="flex h-9 w-9 items-center justify-center rounded-full border border-slate-300 text-slate-600 hover:bg-slate-100"
            aria-label="Cancelar"
          >
            ✕
          </button>
        ) : (
          <button
            onClick={sendMessage}
            disabled={!input.trim()}
            className="flex h-9 w-9 items-center justify-center rounded-full bg-emerald-700 text-white hover:bg-emerald-600 disabled:opacity-40"
            aria-label="Enviar"
          >
            ↑
          </button>
        )}
      </div>
    </div>
  );
}
