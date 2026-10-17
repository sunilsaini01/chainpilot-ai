// Automatic accessibility check (axe, WCAG 2.1 A and AA) of every page with real data.
// Automatic checks find only part of the problems; they do not replace a manual review.

import { expect, test } from "@playwright/test";

import { expectAccessible, openAs, waitForData } from "./helpers";

test("the login page", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Log in" })).toBeVisible();
  await expectAccessible(page);
});

test("the 'page not found' page", async ({ page }) => {
  await page.goto("/no-such-page");
  await expect(page.getByRole("heading", { name: "Page not found" })).toBeVisible();
  await expectAccessible(page);
});

const PAGES: [string, string][] = [
  ["/", "Overview"],
  ["/risks", "Stock-out risks"],
  ["/recommendations", "Recommendations"],
  ["/suppliers", "Suppliers and orders"],
  ["/forecasts", "Demand forecasts"],
  ["/delivery-risk", "Delivery risk"],
  ["/copilot", "Ask the copilot"],
  ["/audit", "Audit log"],
  ["/users", "Users"],
  ["/account", "My account"],
];

test("every page an admin can open", async ({ page }) => {
  await openAs(page, "admin");
  for (const [path, heading] of PAGES) {
    await test.step(path, async () => {
      await page.goto(path);
      await expect(page.getByRole("heading", { level: 1, name: heading })).toBeVisible();
      await waitForData(page);
      await expectAccessible(page);
    });
  }
});
