"use client";

import { useEffect, useRef, useState } from "react";
import { chatApi, recommendationsApi, sectorsApi, calibrationApi } from "@/lib/api";
import type { ProposedAction } from "@/types";

interface Message {
  id?: string;
  role: "user" | "assistant";
  text: string;
  proposedAction?: ProposedAction | null;
  actionResolved?: boolean;
  degraded?: boolean;
  feedback?: -1 | 1;
}

interface QuickAction {
  label: string;
  message: string;
  action?: () => Promise<string>;
}

interface ChatPanelProps {
  farmId: string;
  sectorId?: string;
  onClose: () => void;
}

export function ChatPanel({ farmId, sectorId, onClose }: ChatPanelProps) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  // Guards the resume fetch below from clobbering a send that started in this
  // scope before the fetch resolved — without it, the resume's setMessages
  // can overwrite an in-flight/completed turn and fork a second conversation.
  const hasSentRef = useRef(false);

  useEffect(() => {
    let cancelled = false;
    // Farm/sector are the conversation's scope key. Next.js can keep this
    // component mounted across a param-only navigation, so state from the
    // previous scope must not leak into the new one.
    hasSentRef.current = false;
    setConversationId(null);
    setMessages([]);
    if (typeof chatApi.conversations !== "function") return;
    chatApi
      .conversations(farmId)
      .then((rows) =>
        rows.find((row) => row.sector_id === (sectorId ?? null)),
      )
      .then((conversation) => {
        if (!conversation || cancelled || hasSentRef.current) return;
        return chatApi.conversation(farmId, conversation.id).then((detail) => {
          if (cancelled || hasSentRef.current) return;
          setConversationId(detail.id);
          setMessages(
            detail.messages.map((message) => ({
              id: message.id,
              role: message.role,
              text: message.content,
              proposedAction: message.proposed_action,
              degraded: message.degraded,
            })),
          );
        });
      })
      .catch(() => {
        // Chat history is helpful but non-blocking.
      });
    return () => {
      cancelled = true;
    };
  }, [farmId, sectorId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const pushAssistant = (text: string) =>
    setMessages((prev) => [...prev, { role: "assistant", text }]);

  const pushUser = (text: string) =>
    setMessages((prev) => [...prev, { role: "user", text }]);

  async function runAction(userLabel: string, fetchFn: () => Promise<string>) {
    pushUser(userLabel);
    setLoading(true);
    try {
      const reply = await fetchFn();
      pushAssistant(reply);
    } catch (e) {
      const detail = e instanceof Error ? e.message : "Erro desconhecido";
      pushAssistant(`Não foi possível completar esta acção: ${detail}. Tente novamente.`);
    } finally {
      setLoading(false);
    }
  }

  const quickActions: QuickAction[] = [
    {
      label: "Resumo do dia",
      message: "Resumo do dia",
      action: async () => {
        const r = await chatApi.farmSummary(farmId);
        return r.summary;
      },
    },
    ...(sectorId
      ? [
          {
            label: "Explicar recomendação",
            message: "Explicar recomendação deste sector",
            action: async () => {
              const r = await chatApi.explainSector(sectorId);
              return r.explanation;
            },
          },
        ]
      : []),
    {
      label: "O que falta configurar?",
      message: "O que devo configurar a seguir?",
      action: async () => {
        const r = await chatApi.missingDataQuestions(farmId);
        return r.questions.length > 0
          ? r.questions.map((q, i) => `${i + 1}. ${q}`).join("\n")
          : "A configuração está completa!";
      },
    },
  ];

  async function sendMessage() {
    const text = input.trim();
    if (!text || loading) return;
    hasSentRef.current = true;
    setInput("");
    pushUser(text);
    setMessages((prev) => [...prev, { role: "assistant", text: "" }]);
    setLoading(true);
    try {
      const r = await chatApi.streamChat(
        farmId,
        {
          message: text,
          sector_id: sectorId ?? null,
          conversation_id: conversationId,
        },
        {
          onConversation: (nextConversationId, messageId) => {
            setConversationId(nextConversationId);
            setMessages((prev) =>
              prev.map((message, index) =>
                index === prev.length - 1 ? { ...message, id: messageId } : message,
              ),
            );
          },
          onDelta: (delta) => {
            setMessages((prev) =>
              prev.map((message, index) =>
                index === prev.length - 1
                  ? { ...message, text: message.text + delta }
                  : message,
              ),
            );
          },
        },
      );
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
              }
            : message,
        ),
      );
    } catch (e) {
      const detail = e instanceof Error ? e.message : "Erro desconhecido";
      setMessages((prev) =>
        prev.map((message, index) =>
          index === prev.length - 1
            ? {
                ...message,
                text: `Erro ao contactar o assistente: ${detail}. Tente novamente.`,
                degraded: true,
              }
            : message,
        ),
      );
    } finally {
      setLoading(false);
    }
  }

  async function dispatchAction(action: ProposedAction): Promise<string> {
    const p = action.params as Record<string, unknown>;
    switch (action.type) {
      case "override_recommendation":
        await recommendationsApi.override(action.recommendation_id as string, {
          custom_depth_mm: p.custom_depth_mm != null ? Number(p.custom_depth_mm) : undefined,
          override_reason: (p.override_reason as string) ?? "Ajuste via assistente",
        });
        return "Feito — recomendação substituída.";
      case "accept_recommendation":
        await recommendationsApi.accept(action.recommendation_id as string);
        return "Feito — recomendação aceite.";
      case "reject_recommendation":
        await recommendationsApi.reject(action.recommendation_id as string, p.notes as string | undefined);
        return "Feito — recomendação rejeitada.";
      case "regenerate_recommendation":
        await sectorsApi.generateRecommendation(action.sector_id as string);
        return "Feito — nova recomendação gerada.";
      case "run_calibration":
        await calibrationApi.run(action.sector_id as string);
        return "Feito — calibração iniciada.";
      default:
        return "Acção não suportada.";
    }
  }

  function resolveAction(index: number) {
    setMessages((prev) =>
      prev.map((m, i) => (i === index ? { ...m, actionResolved: true } : m)),
    );
  }

  async function confirmAction(index: number, action: ProposedAction) {
    resolveAction(index);
    setLoading(true);
    try {
      const msg = await dispatchAction(action);
      pushAssistant(msg);
    } catch (e) {
      const detail = e instanceof Error ? e.message : "Erro desconhecido";
      pushAssistant(`Não foi possível executar a acção: ${detail}.`);
    } finally {
      setLoading(false);
    }
  }

  function cancelAction(index: number) {
    resolveAction(index);
    pushAssistant("Acção cancelada.");
  }

  async function sendFeedback(index: number, message: Message, rating: -1 | 1) {
    if (!message.id || message.feedback) return;
    setMessages((prev) =>
      prev.map((item, itemIndex) =>
        itemIndex === index ? { ...item, feedback: rating } : item,
      ),
    );
    try {
      await chatApi.feedback({
        surface: "chat",
        rating,
        farm_id: farmId,
        chat_message_id: message.id,
        entity_id: sectorId,
      });
    } catch {
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
          {messages.length > 0 && (
            <button
              type="button"
              onClick={() => {
                setConversationId(null);
                setMessages([]);
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

      {/* Quick actions */}
      {messages.length === 0 && (
        <div className="border-b border-slate-100 px-3 py-3">
          <p className="mb-1.5 text-xs font-medium uppercase tracking-wide text-slate-500">Acções rápidas</p>
          <div className="flex flex-wrap gap-1.5">
            {quickActions.map((qa) => (
              <button
                key={qa.label}
                onClick={() => qa.action && runAction(qa.message, qa.action)}
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
            {msg.role === "assistant" && msg.degraded && (
              <p className="mt-1 max-w-[85%] text-[10px] text-amber-700">
                Resposta de contingência — o serviço de IA não estava disponível.
              </p>
            )}
            {msg.proposedAction && !msg.actionResolved && (
              <div className="mt-2 max-w-[85%] rounded-xl border border-amber-300 bg-amber-50 px-3 py-2 text-sm">
                <p className="mb-2 font-medium text-amber-900">{msg.proposedAction.summary}</p>
                <div className="flex gap-2">
                  <button
                    onClick={() => confirmAction(i, msg.proposedAction!)}
                    disabled={loading}
                    className="rounded-full bg-emerald-700 px-3 py-1 text-xs font-medium text-white hover:bg-emerald-600 disabled:opacity-50"
                  >
                    Confirmar
                  </button>
                  <button
                    onClick={() => cancelAction(i)}
                    disabled={loading}
                    className="rounded-full border border-slate-300 px-3 py-1 text-xs font-medium text-slate-700 hover:bg-slate-100 disabled:opacity-50"
                  >
                    Cancelar
                  </button>
                </div>
              </div>
            )}
            {msg.role === "assistant" && msg.id && msg.text && (
              <div className="mt-1 flex gap-1">
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
                  onClick={() => sendFeedback(i, msg, -1)}
                  className={`rounded px-1.5 py-0.5 text-xs ${
                    msg.feedback === -1 ? "bg-amber-100" : "text-slate-400"
                  }`}
                >
                  👎
                </button>
              </div>
            )}
          </div>
        ))}
        {loading && (
          <div className="flex justify-start">
            <div className="rounded-2xl bg-slate-100 px-3 py-2 text-sm text-slate-500">
              <span className="animate-pulse">A pensar…</span>
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
        <button
          onClick={sendMessage}
          disabled={loading || !input.trim()}
          className="flex h-9 w-9 items-center justify-center rounded-full bg-emerald-700 text-white hover:bg-emerald-600 disabled:opacity-40"
          aria-label="Enviar"
        >
          ↑
        </button>
      </div>
    </div>
  );
}
