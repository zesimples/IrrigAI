// Synthetic HTTP/SSE fixture. No database, credentials or provider access.
import http from "node:http";

// Delays are fixed so the browser test can tell streamed progress from a buffered
// response: buffered, progress and answer arrive together at ANSWER_DELAY_MS.
const ANSWER_DELAY_MS = 1200;
const CONFIRM_DELAY_MS = 1500;
const stats = { confirmCalls: 0 };

// Both farm-level, i.e. in the scope of the farm page under test (the panel lists
// only same-scope conversations). Newest first: that one is auto-resumed on open.
const currentConversation = {
  id: "review-current", title: "Conversa actual", sector_id: null,
  last_message_at: "2026-09-02T10:00:00Z",
};
const otherConversation = {
  id: "review-other", title: "Outra conversa", sector_id: null,
  last_message_at: "2026-09-01T10:00:00Z",
};

http.createServer(async (req, res) => {
  const json = (value) => {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify(value));
  };
  const url = req.url ?? "";
  if (url.endsWith("/dashboard")) return json({
    farm: { id: "review", name: "Exploração de teste", region: null },
    date: "2026-09-21", sectors_summary: [], active_alerts_count: {},
    weather_today: { forecast_rain_next_48h_mm: 0, et0_mm: null }, sync_status: [],
  });
  if (url.endsWith("/chat/conversations")) return json([currentConversation, otherConversation]);
  if (url.endsWith("/chat/conversations/review-current")) return json({ ...currentConversation, messages: [] });
  if (url.endsWith("/chat/conversations/review-other")) return json({
    ...otherConversation,
    messages: [{ id: "old-1", role: "assistant", content: "Resposta de uma conversa antiga.",
      created_at: "2026-09-01T10:00:00Z" }],
  });
  if (url.endsWith("/chat/stream")) {
    let raw = "";
    for await (const chunk of req) raw += chunk;
    const body = JSON.parse(raw);
    res.writeHead(200, { "Content-Type": "text/event-stream", "Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no" });
    const event = (name, data) => res.write(`event: ${name}\ndata: ${JSON.stringify(data)}\n\n`);
    event("conversation", { conversation_id: "review-conversation", message_id: body.client_message_id });
    event("progress", { stage: "context", label: "A preparar o contexto de teste…" });
    setTimeout(() => {
      if (body.message === "calibrar") {
        event("delta", { text: "Posso correr a calibração deste setor." });
        event("done", {
          status: "complete", validation_status: "validated",
          proposed_action: {
            type: "run_calibration", action_id: "review-action", status: "pending", params: {},
            summary: "Correr a calibração inteligente do setor Setor de teste. Atenção: isto "
              + "substitui os limites de solo definidos manualmente (CC/PMP) pelos valores "
              + "calculados a partir da sonda.",
          },
        });
        return res.end();
      }
      event("delta", { text: "A decisão do motor é não regar." });
      if (body.message !== "interromper") event("done", { status: "complete", validation_status: "validated" });
      res.end();
    }, ANSWER_DELAY_MS);
    return;
  }
  if (url.endsWith("/chat/actions/review-action/confirm")) {
    stats.confirmCalls += 1;
    return setTimeout(() => json({ id: "review-action", status: "succeeded", error_detail: null }), CONFIRM_DELAY_MS);
  }
  if (url === "/__stats") return json(stats);
  if (url === "/health") return json({ status: "ok" });
  res.writeHead(404);
  res.end();
}).listen(8101, "127.0.0.1");
