import { expect, test, type Page } from "@playwright/test";

// Synthetic only: the fixture on :8101 stands in for the backend, behind the real
// Next.js proxy. This proves the proxy layer streams; it says nothing about the
// production Caddy route, which must be verified separately after a deploy.
const FIXTURE = "http://127.0.0.1:8101";
const ANSWER_DELAY_MS = 1200;

async function openAssistant(page: Page) {
  await page.goto("/farms/review");
  await page.getByRole("button", { name: "Abrir assistente" }).click();
  return page.getByPlaceholder(/pergunta/i);
}

test("progress is visible before the answer completes", async ({ page }) => {
  const input = await openAssistant(page);
  await input.fill("estado");
  const sentAt = Date.now();
  await page.getByRole("button", { name: "Enviar", exact: true }).click();

  const progress = page.getByText("A preparar o contexto de teste…");
  const answer = page.getByText("A decisão do motor é não regar.");
  await expect(progress).toBeVisible();
  const progressMs = Date.now() - sentAt;
  await expect(answer).not.toBeVisible();
  await expect(answer).toBeVisible();
  const answerMs = Date.now() - sentAt;

  const timing = `progress ${progressMs} ms, answer ${answerMs} ms (fixture holds the answer ${ANSWER_DELAY_MS} ms)`;
  test.info().annotations.push({ type: "timing", description: timing });
  console.log(`[chat-review] ${timing}`);
  // A buffering proxy delivers both together at ~ANSWER_DELAY_MS.
  expect(progressMs).toBeLessThan(ANSWER_DELAY_MS - 400);
  expect(answerMs - progressMs).toBeGreaterThan(400);
});

test("an interrupted stream keeps its retry identity", async ({ page }) => {
  const input = await openAssistant(page);
  await input.fill("interromper");
  const firstRequest = page.waitForRequest((r) => r.url().endsWith("/chat/stream"));
  await page.getByRole("button", { name: "Enviar", exact: true }).click();
  const first = (await firstRequest).postDataJSON();
  await expect(page.getByText(/Erro ao contactar o assistente/)).toBeVisible();
  await expect(input).toHaveValue("interromper");
  const retryRequest = page.waitForRequest((r) => r.url().endsWith("/chat/stream"));
  await page.getByRole("button", { name: "Enviar", exact: true }).click();
  expect((await retryRequest).postDataJSON().client_message_id).toBe(first.client_message_id);
  await expect(page.getByText("interromper", { exact: true })).toHaveCount(1);
});

test("a confirmation cannot be stranded by switching conversation", async ({ page, request }) => {
  const input = await openAssistant(page);
  await input.fill("calibrar");
  await page.getByRole("button", { name: "Enviar", exact: true }).click();

  // B5: the overwrite of manual soil limits is disclosed before confirming.
  await expect(page.getByText(/substitui os limites de solo definidos manualmente/)).toBeVisible();
  const before = (await (await request.get(`${FIXTURE}/__stats`)).json()).confirmCalls;
  await page.getByRole("button", { name: "Confirmar" }).click();

  // B4: while the write is in flight the transcript cannot be swapped out.
  const history = page.getByRole("button", { name: "Conversas anteriores" });
  await expect(history).toBeDisabled();
  await expect(page.getByText("Acção executada.")).toBeVisible();
  await expect(input).toBeEnabled();
  expect((await (await request.get(`${FIXTURE}/__stats`)).json()).confirmCalls).toBe(before + 1);

  // Once it finishes, switching conversation works again.
  await expect(history).toBeEnabled();
  await history.click();
  await page.getByText("Outra conversa").click();
  await expect(page.getByText("Resposta de uma conversa antiga.")).toBeVisible();
});
