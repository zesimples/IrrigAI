import { expect, test } from "@playwright/test";

test("Next proxy delivers progress before completion and EOF preserves retry identity", async ({ page }) => {
  await page.goto("/farms/review");
  await page.getByRole("button", { name: "Abrir assistente" }).click();
  const input = page.getByPlaceholder(/pergunta/i);
  await input.fill("estado");
  await page.getByRole("button", { name: "Enviar", exact: true }).click();
  await expect(page.getByText("A preparar o contexto de teste…")).toBeVisible();
  await expect(page.getByText("A decisão do motor é não regar.")).not.toBeVisible();
  await expect(page.getByText("A decisão do motor é não regar.")).toBeVisible();

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
