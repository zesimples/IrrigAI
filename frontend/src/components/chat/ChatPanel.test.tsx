import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { ChatPanel } from "./ChatPanel";

// jsdom does not implement scrollIntoView
window.HTMLElement.prototype.scrollIntoView = vi.fn() as typeof window.HTMLElement.prototype.scrollIntoView;

vi.mock("@/lib/api", () => ({
  chatApi: {
    streamChat: vi.fn(),
    conversations: vi.fn().mockResolvedValue([]),
    conversation: vi.fn(),
    feedback: vi.fn(),
    quickAction: vi.fn(),
    confirmAction: vi.fn(),
    cancelAction: vi.fn(),
  },
  recommendationsApi: { override: vi.fn(), accept: vi.fn(), reject: vi.fn() },
  sectorsApi: { generateRecommendation: vi.fn() },
  calibrationApi: { run: vi.fn() },
}));

import { chatApi } from "@/lib/api";


function streamReturning(overrides: Record<string, unknown>, deltas: string[] = ["olá!"]) {
  return async (
    _farmId: string,
    _body: unknown,
    callbacks: {
      onDelta: (text: string) => void;
      onProgress?: (label: string, stage: string) => void;
      onConversation?: (conversationId: string, messageId: string) => void;
    },
  ) => {
    callbacks.onProgress?.("A ler o estado hídrico do setor…", "tool");
    callbacks.onConversation?.("conv-1", "msg-1");
    deltas.forEach((delta) => callbacks.onDelta(delta));
    return {
      reply: deltas.join(""),
      conversation_id: "conv-1",
      message_id: "msg-1",
      proposed_action: null,
      degraded: false,
      model_name: "mock",
      evidence: [],
      context_version: "ctx-1",
      contract_version: "a3.1",
      validation_status: "validated" as const,
      status: "complete" as const,
      ...overrides,
    };
  };
}

describe("ChatPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (chatApi.conversations as any).mockResolvedValue([]);
  });

  it.each([false, true])("reuses retry identity only for unchanged text (changed: %s)", async (changed) => {
    vi.mocked(chatApi.streamChat).mockRejectedValueOnce(new Error("interrompida"))
      .mockImplementationOnce(streamReturning({}));
    render(<ChatPanel farmId="f1" onClose={() => {}} />);
    fireEvent.change(screen.getByPlaceholderText(/pergunta/i), { target: { value: "primeira" } });
    fireEvent.click(screen.getByLabelText("Enviar"));
    await screen.findByText(/Erro ao contactar/);
    expect(screen.getByPlaceholderText(/pergunta/i)).toHaveValue("primeira");
    if (changed) fireEvent.change(screen.getByPlaceholderText(/pergunta/i), { target: { value: "alterada" } });
    fireEvent.click(screen.getByLabelText("Enviar"));
    await screen.findByText("olá!");
    const calls = vi.mocked(chatApi.streamChat).mock.calls;
    expect(calls[0][1].client_message_id === calls[1][1].client_message_id).toBe(!changed);
    expect(screen.getAllByText("primeira")).toHaveLength(1);
  });

  it("ignores conversation detail arriving after a newer send", async () => {
    vi.mocked(chatApi.conversations).mockResolvedValue([{ id: "old", sector_id: null, title: "Antiga", last_message_at: "2026-09-01T10:00:00Z" }] as any);
    let resolve!: (value: any) => void;
    vi.mocked(chatApi.conversation).mockImplementationOnce(() => new Promise((done) => { resolve = done; }));
    vi.mocked(chatApi.streamChat).mockImplementation(streamReturning({}, ["Resposta recente"]));
    render(<ChatPanel farmId="f1" onClose={() => {}} />);
    await waitFor(() => expect(chatApi.conversation).toHaveBeenCalled());
    fireEvent.change(screen.getByPlaceholderText(/pergunta/i), { target: { value: "nova" } });
    fireEvent.click(screen.getByLabelText("Enviar"));
    await screen.findByText("Resposta recente");
    await act(async () => resolve({ id: "old", messages: [{ id: "old-message", role: "assistant", content: "Resposta antiga" }] }));
    expect(screen.queryByText("Resposta antiga")).not.toBeInTheDocument();
    expect(screen.getByText("Resposta recente")).toBeInTheDocument();
  });

  it("retains a pending action when cancellation fails", async () => {
    vi.mocked(chatApi.streamChat).mockImplementation(streamReturning({ proposed_action: {
      type: "run_calibration", summary: "Calibrar setor", action_id: "a1", status: "pending", params: {},
    } }));
    vi.mocked(chatApi.cancelAction).mockRejectedValue(new Error("offline"));
    render(<ChatPanel farmId="f1" onClose={() => {}} />);
    fireEvent.change(screen.getByPlaceholderText(/pergunta/i), { target: { value: "calibrar" } });
    fireEvent.click(screen.getByLabelText("Enviar"));
    fireEvent.click(await screen.findByText("Cancelar"));
    await waitFor(() => expect(chatApi.cancelAction).toHaveBeenCalledWith("f1", "a1"));
    expect(screen.getByText("Confirmar")).toBeInTheDocument();
    expect(screen.queryByText(/Acção cancelada/)).not.toBeInTheDocument();
  });

  it("ignores an action response after navigating to another sector", async () => {
    vi.mocked(chatApi.streamChat).mockImplementation(streamReturning({ proposed_action: {
      type: "run_calibration", summary: "Calibrar setor", action_id: "a1", status: "pending", params: {},
    } }));
    let resolve!: (value: any) => void;
    vi.mocked(chatApi.confirmAction).mockImplementationOnce(() => new Promise((done) => { resolve = done; }));
    const onActionCompleted = vi.fn();
    const view = render(<ChatPanel farmId="f1" sectorId="s1" onClose={() => {}} onActionCompleted={onActionCompleted} />);
    fireEvent.change(screen.getByPlaceholderText(/pergunta/i), { target: { value: "calibrar" } });
    fireEvent.click(screen.getByLabelText("Enviar"));
    fireEvent.click(await screen.findByText("Confirmar"));
    await waitFor(() => expect(chatApi.confirmAction).toHaveBeenCalled());
    view.rerender(<ChatPanel farmId="f1" sectorId="s2" onClose={() => {}} onActionCompleted={onActionCompleted} />);
    await act(async () => resolve({ status: "succeeded", error_detail: null }));
    expect(onActionCompleted).not.toHaveBeenCalled();
    expect(screen.queryByText("Acção executada.")).not.toBeInTheDocument();
  });

  describe("loading a conversation while an action is confirming (review 2026-09-23, B4)", () => {
    // Opening Histórico mid-confirm bumped the generation counter, so the confirm's
    // finally never cleared `loading` and its result was dropped — the panel stuck on
    // "A pensar…" while the server had already committed the write.
    const otherConversation = {
      id: "c-other", title: "Outra conversa", sector_id: "s-other",
      last_message_at: "2026-09-01T10:00:00Z",
    };

    function setUp() {
      (chatApi.conversations as any).mockResolvedValue([otherConversation]);
      vi.mocked(chatApi.conversation).mockResolvedValue({
        id: "c-other", messages: [{ id: "m9", role: "assistant", content: "antiga", created_at: "2026-09-01T10:00:00Z" }],
      } as any);
      vi.mocked(chatApi.streamChat).mockImplementation(streamReturning({ proposed_action: {
        type: "run_calibration", summary: "Calibrar setor", action_id: "a1", status: "pending", params: {},
      } }));
      let resolve!: (value: any) => void;
      vi.mocked(chatApi.confirmAction).mockImplementationOnce(() => new Promise((done) => { resolve = done; }));
      const onActionCompleted = vi.fn();
      render(<ChatPanel farmId="f1" sectorId="s1" onClose={() => {}} onActionCompleted={onActionCompleted} />);
      return { onActionCompleted, resolve: (value: any) => resolve(value) };
    }

    async function askAndConfirm() {
      fireEvent.change(screen.getByPlaceholderText(/pergunta/i), { target: { value: "calibrar" } });
      fireEvent.click(screen.getByLabelText("Enviar"));
      fireEvent.click(await screen.findByText("Confirmar"));
      await waitFor(() => expect(chatApi.confirmAction).toHaveBeenCalled());
    }

    it("reports the committed action instead of stranding the spinner", async () => {
      const { onActionCompleted, resolve } = setUp();
      await askAndConfirm();
      fireEvent.click(await screen.findByLabelText("Conversas anteriores"));
      const row = screen.queryByText("Outra conversa");
      if (row) fireEvent.click(row);
      await act(async () => resolve({ status: "succeeded", error_detail: null }));
      expect(onActionCompleted).toHaveBeenCalled();
      expect(screen.getByPlaceholderText(/pergunta/i)).not.toBeDisabled();
      expect(screen.queryByText(/A pensar/)).not.toBeInTheDocument();
    });

    it("allows switching conversations again once the turn has finished", async () => {
      (chatApi.conversations as any).mockResolvedValue([otherConversation]);
      vi.mocked(chatApi.conversation).mockResolvedValue({
        id: "c-other", messages: [{ id: "m9", role: "assistant", content: "antiga", created_at: "2026-09-01T10:00:00Z" }],
      } as any);
      vi.mocked(chatApi.streamChat).mockImplementation(streamReturning({}));
      render(<ChatPanel farmId="f1" sectorId="s1" onClose={() => {}} />);
      fireEvent.change(screen.getByPlaceholderText(/pergunta/i), { target: { value: "olá" } });
      fireEvent.click(screen.getByLabelText("Enviar"));
      await screen.findByText("olá!");
      fireEvent.click(await screen.findByLabelText("Conversas anteriores"));
      fireEvent.click(screen.getByText("Outra conversa"));
      expect(await screen.findByText("antiga")).toBeInTheDocument();
    });

    it("refuses to swap the transcript from an already-open picker", async () => {
      const { onActionCompleted, resolve } = setUp();
      fireEvent.click(await screen.findByLabelText("Conversas anteriores"));
      await askAndConfirm();
      fireEvent.click(screen.getByText("Outra conversa"));
      await act(async () => resolve({ status: "succeeded", error_detail: null }));
      expect(chatApi.conversation).not.toHaveBeenCalled();
      expect(onActionCompleted).toHaveBeenCalled();
      expect(screen.getByPlaceholderText(/pergunta/i)).not.toBeDisabled();
    });
  });

  it("sends a turn identity so a retry resumes instead of duplicating", async () => {
    (chatApi.streamChat as any).mockImplementation(streamReturning({}));
    render(<ChatPanel farmId="f1" onClose={() => {}} />);
    fireEvent.change(screen.getByPlaceholderText(/pergunta/i), { target: { value: "primeira" } });
    fireEvent.click(screen.getByLabelText("Enviar"));
    await waitFor(() => expect(chatApi.streamChat).toHaveBeenCalled());

    const body = (chatApi.streamChat as any).mock.calls[0][1];
    expect(body).toMatchObject({
      message: "primeira",
      sector_id: null,
      conversation_id: null,
    });
    expect(typeof body.client_message_id).toBe("string");
    expect(body.client_message_id.length).toBeGreaterThan(0);
  });

  it("shows the backend progress label while the turn is running", async () => {
    let release: () => void = () => {};
    (chatApi.streamChat as any).mockImplementation(
      async (
        _farmId: string,
        _body: unknown,
        callbacks: { onDelta: (t: string) => void; onProgress?: (l: string) => void },
      ) => {
        callbacks.onProgress?.("A ler o estado hídrico do setor…");
        await new Promise<void>((resolve) => {
          release = resolve;
        });
        callbacks.onDelta("pronto");
        return {
          reply: "pronto",
          conversation_id: "c",
          message_id: "m",
          proposed_action: null,
          degraded: false,
          model_name: "mock",
        };
      },
    );

    render(<ChatPanel farmId="f1" onClose={() => {}} />);
    fireEvent.change(screen.getByPlaceholderText(/pergunta/i), { target: { value: "estado?" } });
    fireEvent.click(screen.getByLabelText("Enviar"));

    // The label is visible BEFORE any answer content arrives.
    await screen.findByText("A ler o estado hídrico do setor…");
    expect(screen.queryByText("pronto")).not.toBeInTheDocument();
    await act(async () => {
      release();
    });
    await screen.findByText("pronto");
  });

  it("confirms a proposed action through the server, not a direct write", async () => {
    (chatApi.streamChat as any).mockImplementation(
      streamReturning(
        {
          proposed_action: {
            type: "run_calibration",
            summary: "Correr a calibração inteligente.",
            sector_id: "sec-9",
            params: {},
            action_id: "act-1",
            status: "pending",
          },
        },
        ["Proponho calibrar."],
      ),
    );
    (chatApi.confirmAction as any).mockResolvedValue({ status: "succeeded", error_detail: null });
    (chatApi.conversation as any).mockResolvedValue({ id: "conv-1", messages: [] });

    render(<ChatPanel farmId="f1" sectorId="sec-9" onClose={() => {}} />);
    fireEvent.change(screen.getByPlaceholderText(/pergunta/i), { target: { value: "recalibrar" } });
    fireEvent.click(screen.getByLabelText("Enviar"));
    await screen.findByText("Correr a calibração inteligente.");
    fireEvent.click(screen.getByText("Confirmar"));

    await waitFor(() => expect(chatApi.confirmAction).toHaveBeenCalledWith("f1", "act-1"));
    await screen.findByText("Acção executada.");
    expect(screen.queryByText("Confirmar")).not.toBeInTheDocument();
  });

  it("does not re-offer a completed action when the conversation is reopened", async () => {
    (chatApi.conversations as any).mockResolvedValue([
      { id: "conv-1", sector_id: null, title: "Antiga", last_message_at: "2026-09-01T10:00:00Z" },
    ]);
    (chatApi.conversation as any).mockResolvedValue({
      id: "conv-1",
      messages: [
        {
          id: "m1",
          role: "assistant",
          content: "Proponho aceitar.",
          degraded: false,
          created_at: "2026-09-01T10:00:00Z",
          proposed_action: {
            type: "accept_recommendation",
            summary: "Aceitar a recomendação atual.",
            params: {},
            action_id: "act-9",
            status: "succeeded",
          },
        },
      ],
    });

    render(<ChatPanel farmId="f1" onClose={() => {}} />);
    await screen.findByText("Aceitar a recomendação atual.");
    expect(screen.getByText("Acção executada.")).toBeInTheDocument();
    expect(screen.queryByText("Confirmar")).not.toBeInTheDocument();
  });

  it("shows a failed action as failed and keeps it retryable", async () => {
    (chatApi.streamChat as any).mockImplementation(
      streamReturning(
        {
          proposed_action: {
            type: "run_calibration",
            summary: "Correr a calibração inteligente.",
            sector_id: "sec-9",
            params: {},
            action_id: "act-2",
            status: "pending",
          },
        },
        ["Proponho calibrar."],
      ),
    );
    (chatApi.confirmAction as any).mockResolvedValue({
      status: "failed",
      error_detail: "calibration_unavailable",
    });
    (chatApi.conversation as any).mockResolvedValue({ id: "conv-1", messages: [] });

    render(<ChatPanel farmId="f1" sectorId="sec-9" onClose={() => {}} />);
    fireEvent.change(screen.getByPlaceholderText(/pergunta/i), { target: { value: "recalibrar" } });
    fireEvent.click(screen.getByLabelText("Enviar"));
    await screen.findByText("Correr a calibração inteligente.");
    fireEvent.click(screen.getByText("Confirmar"));

    await screen.findByText(/A acção falhou/);
    expect(screen.getByText("Confirmar")).toBeInTheDocument();
  });

  it("never offers to confirm a legacy proposal with no recorded outcome", async () => {
    (chatApi.conversations as any).mockResolvedValue([
      { id: "conv-1", sector_id: null, title: "Antiga", last_message_at: "2026-08-01T10:00:00Z" },
    ]);
    (chatApi.conversation as any).mockResolvedValue({
      id: "conv-1",
      messages: [
        {
          id: "m1",
          role: "assistant",
          content: "Proponho aceitar.",
          degraded: false,
          created_at: "2026-08-01T10:00:00Z",
          proposed_action: {
            type: "accept_recommendation",
            summary: "Aceitar a recomendação atual.",
            params: {},
            action_id: null,
            status: "legacy",
          },
        },
      ],
    });

    render(<ChatPanel farmId="f1" onClose={() => {}} />);
    await screen.findByText(/Proposta anterior/);
    expect(screen.queryByText("Confirmar")).not.toBeInTheDocument();
  });

  it("marks a deterministic fallback answer as such", async () => {
    (chatApi.streamChat as any).mockImplementation(
      streamReturning({ validation_status: "fallback" }, ["A decisão do motor é não regar."]),
    );
    render(<ChatPanel farmId="f1" onClose={() => {}} />);
    fireEvent.change(screen.getByPlaceholderText(/pergunta/i), { target: { value: "quanto rego?" } });
    fireEvent.click(screen.getByLabelText("Enviar"));
    await screen.findByText(/não ficou sustentada pelos dados/);
  });

  it("runs quick actions on the server so the result is persisted", async () => {
    (chatApi.quickAction as any).mockResolvedValue({
      reply: "Resumo do dia.",
      conversation_id: "conv-q",
      message_id: "msg-q",
      proposed_action: null,
      degraded: false,
      model_name: "mock",
    });
    render(<ChatPanel farmId="f1" onClose={() => {}} />);
    fireEvent.click(screen.getByText("Resumo do dia"));
    await waitFor(() =>
      expect(chatApi.quickAction).toHaveBeenCalledWith("f1", {
        kind: "farm_summary",
        sector_id: null,
        conversation_id: null,
      }),
    );
    await screen.findByText("Resumo do dia.");
  });

  it("sends a feedback reason and the answer version it was cast against", async () => {
    (chatApi.streamChat as any).mockImplementation(streamReturning({}, ["resposta"]));
    (chatApi.feedback as any).mockResolvedValue({ id: "fb" });
    render(<ChatPanel farmId="f1" onClose={() => {}} />);
    fireEvent.change(screen.getByPlaceholderText(/pergunta/i), { target: { value: "olá" } });
    fireEvent.click(screen.getByLabelText("Enviar"));
    await screen.findByText("resposta");

    fireEvent.click(screen.getByLabelText("Resposta pouco útil"));
    fireEvent.click(await screen.findByText("Dados errados"));

    await waitFor(() =>
      expect(chatApi.feedback).toHaveBeenCalledWith(
        expect.objectContaining({
          rating: -1,
          reason: "wrong_data",
          context_version: "ctx-1",
          contract_version: "a3.1",
        }),
      ),
    );
  });

  it("offers a picker over previous conversations with their dates", async () => {
    (chatApi.conversations as any).mockResolvedValue([
      { id: "conv-1", sector_id: null, title: "Conversa antiga", last_message_at: "2026-09-01T10:00:00Z" },
      { id: "conv-2", sector_id: null, title: "Outra", last_message_at: "2026-08-20T10:00:00Z" },
    ]);
    (chatApi.conversation as any).mockResolvedValue({ id: "conv-2", messages: [] });

    render(<ChatPanel farmId="f1" onClose={() => {}} />);
    fireEvent.click(await screen.findByLabelText("Conversas anteriores"));
    fireEvent.click(await screen.findByText("Outra"));
    await waitFor(() => expect(chatApi.conversation).toHaveBeenCalledWith("f1", "conv-2"));
  });

  it("does not let a slow conversation-resume overwrite a message the user already sent", async () => {
    let resolveConversations: (rows: unknown[]) => void = () => {};
    (chatApi.conversations as any).mockReturnValue(
      new Promise((resolve) => {
        resolveConversations = resolve;
      }),
    );
    (chatApi.streamChat as any).mockImplementation(streamReturning({}, ["resposta rápida"]));

    render(<ChatPanel farmId="f1" onClose={() => {}} />);
    fireEvent.change(screen.getByPlaceholderText(/pergunta/i), { target: { value: "primeira" } });
    fireEvent.click(screen.getByLabelText("Enviar"));
    await screen.findByText("resposta rápida");

    await act(async () => {
      resolveConversations([
        { id: "conv-old", sector_id: null, title: null, last_message_at: "2026-01-01T00:00:00Z" },
      ]);
      (chatApi.conversation as any).mockResolvedValue({
        id: "conv-old",
        messages: [
          { id: "old-1", role: "user", content: "mensagem antiga", proposed_action: null, degraded: false },
        ],
      });
      await Promise.resolve();
    });

    expect(screen.getByText("primeira")).toBeInTheDocument();
    expect(screen.getByText("resposta rápida")).toBeInTheDocument();
    expect(screen.queryByText("mensagem antiga")).not.toBeInTheDocument();
  });

  it("clears the transcript when the active sector changes", async () => {
    (chatApi.conversations as any).mockResolvedValue([]);
    const { rerender } = render(<ChatPanel farmId="f1" sectorId="sec-1" onClose={() => {}} />);
    (chatApi.streamChat as any).mockImplementation(streamReturning({}, ["resposta do sector 1"]));

    fireEvent.change(screen.getByPlaceholderText(/pergunta/i), {
      target: { value: "pergunta do sector 1" },
    });
    fireEvent.click(screen.getByLabelText("Enviar"));
    await screen.findByText("resposta do sector 1");

    rerender(<ChatPanel farmId="f1" sectorId="sec-2" onClose={() => {}} />);

    await waitFor(() => {
      expect(screen.queryByText("pergunta do sector 1")).not.toBeInTheDocument();
      expect(screen.queryByText("resposta do sector 1")).not.toBeInTheDocument();
    });
  });
});
