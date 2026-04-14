"use client";

import { useEffect, useRef, useState } from "react";
import { chatApi } from "@/lib/api";

interface Message {
  role: "user" | "assistant";
  text: string;
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
  const bottomRef = useRef<HTMLDivElement>(null);

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
    } catch {
      pushAssistant("Ocorreu um erro. Tente novamente.");
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
    setInput("");
    pushUser(text);
    setLoading(true);
    try {
      const r = await chatApi.chat(farmId, text, sectorId);
      pushAssistant(r.reply);
    } catch {
      pushAssistant("Ocorreu um erro ao contactar o assistente.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="fixed bottom-20 right-4 z-50 flex h-[min(540px,calc(100vh-7rem))] w-[min(24rem,calc(100vw-2rem))] flex-col rounded-[1.75rem] border border-slate-200 bg-white shadow-2xl sm:right-6">
      {/* Header */}
      <div className="flex items-center justify-between rounded-t-[1.75rem] bg-emerald-700 px-4 py-3">
        <div>
          <p className="text-sm font-semibold text-white">Assistente IrrigAI</p>
          <p className="text-xs text-emerald-200">Powered by GPT-4o</p>
        </div>
        <button
          onClick={onClose}
          className="rounded-full p-1 text-white hover:bg-emerald-600"
          aria-label="Fechar"
        >
          ✕
        </button>
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
          <div
            key={i}
            className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
          >
            <div
              className={`max-w-[85%] rounded-2xl px-3 py-2 text-sm whitespace-pre-wrap ${
                msg.role === "user"
                  ? "bg-emerald-700 text-white"
                  : "bg-slate-100 text-slate-800"
              }`}
            >
              {msg.text}
            </div>
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
