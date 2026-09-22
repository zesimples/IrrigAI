import { afterEach, describe, expect, it, vi } from "vitest";
import { chatApi } from "@/lib/api";

afterEach(() => { vi.unstubAllGlobals(); });

describe("chat stream completion", () => {
  it.each([false, true])("requires the done event (present: %s)", async (complete) => {
    Object.defineProperty(window, "localStorage", { configurable: true, value: { getItem: () => null } });
    const body = 'event: conversation\ndata: {"conversation_id":"c","message_id":"m"}\n\n'
      + 'event: delta\ndata: {"text":"Resposta parcial"}\n\n'
      + (complete ? 'event: done\ndata: {"status":"complete"}\n\n' : "");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(body)));
    const onDelta = vi.fn();
    const result = chatApi.streamChat("farm", { message: "estado" }, { onDelta });
    if (complete) {
      await expect(result).resolves.toMatchObject({ status: "complete", message_id: "m" });
    } else {
      await expect(result).rejects.toThrow(/interrompida/);
    }
    expect(onDelta).toHaveBeenCalledWith("Resposta parcial");
  });
});
