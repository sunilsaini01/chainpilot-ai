// Empty and error states in the real app. The test stack has only a few synthetic
// forecasts, no delivery-risk scores and no AI key, so those pages must say so plainly.

import { expect, test } from "@playwright/test";

import { openAs } from "./helpers";

test("forecasts show their data label, or say when an item has none", async ({ page }) => {
  await openAs(page, "analyst", "/forecasts");
  // The default item is not in the synthetic test forecasts.
  await expect(page.getByText(/No forecast for FOODS_3_090 at CA_1/)).toBeVisible();

  await page.getByLabel("Item").fill("FOODS_3_001");
  await page.getByRole("button", { name: "Show" }).click();
  const chart = page.getByRole("region", { name: "Forecast for FOODS_3_001 at CA_1" });
  await expect(chart).toContainText("SYNTHETIC test forecasts for browser tests");
});

test("delivery risk explains that nothing is imported yet", async ({ page }) => {
  await openAs(page, "analyst", "/delivery-risk");
  await expect(page.getByText("No delivery-risk scores are imported yet.")).toBeVisible();
});

test("the copilot explains that it is not set up", async ({ page }) => {
  await openAs(page, "analyst", "/copilot");
  await page.getByLabel("Your question").fill("Which suppliers are unreliable?");
  await page.getByRole("button", { name: "Ask" }).click();
  await expect(page.getByRole("alert")).toContainText("not set up on this server");
});

test("a failed request shows an error, and 'Try again' recovers", async ({ page }) => {
  await openAs(page, "analyst", "/risks");
  // Make the next calls fail as if the API were unreachable, then open the overview.
  await page.route("**/dashboard/kpis", (route) => route.abort("connectionrefused"));
  await page.getByRole("link", { name: "Overview" }).click();
  const error = page.getByRole("alert");
  await expect(error).toBeVisible();
  await expect(page.getByRole("button", { name: "Try again" })).toBeVisible();

  await page.unroute("**/dashboard/kpis");
  await page.getByRole("button", { name: "Try again" }).click();
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
  await expect(error).toHaveCount(0);
});

test("an unknown address shows a 'not found' page with a way back", async ({ page }) => {
  // nginx answers every path with the app; the app itself says the page does not exist.
  const response = await page.goto("/no-such-page");
  expect(response?.status()).toBe(200);
  await expect(page.getByRole("heading", { name: "Page not found" })).toBeVisible();
  await page.getByRole("link", { name: "Go to the overview" }).click();
  await expect(page.getByRole("button", { name: "Log in" })).toBeVisible();
});
