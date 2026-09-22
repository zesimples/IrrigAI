// Synthetic HTTP/SSE fixture. No database, credentials or provider access.
import http from "node:http";

http.createServer(async (req, res) => {
  const json = (value) => {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify(value));
  };
  if (req.url.endsWith("/dashboard")) return json({
    farm: { id: "review", name: "Exploração de teste", region: null },
    date: "2026-09-21", sectors_summary: [], active_alerts_count: {},
    weather_today: { forecast_rain_next_48h_mm: 0, et0_mm: null }, sync_status: [],
  });
  if (req.url.endsWith("/conversations")) return json([]);
  if (req.url.endsWith("/chat/stream")) {
    let raw = "";
    for await (const chunk of req) raw += chunk;
    const body = JSON.parse(raw);
    res.writeHead(200, { "Content-Type": "text/event-stream", "Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no" });
    const event = (name, data) => res.write(`event: ${name}\ndata: ${JSON.stringify(data)}\n\n`);
    event("conversation", { conversation_id: "review-conversation", message_id: body.client_message_id });
    event("progress", { stage: "context", label: "A preparar o contexto de teste…" });
    setTimeout(() => {
      event("delta", { text: "A decisão do motor é não regar." });
      if (body.message !== "interromper") event("done", { status: "complete", validation_status: "validated" });
      res.end();
    }, 1200);
    return;
  }
  if (req.url === "/health") return json({ status: "ok" });
  res.writeHead(404);
  res.end();
}).listen(8101, "127.0.0.1");
