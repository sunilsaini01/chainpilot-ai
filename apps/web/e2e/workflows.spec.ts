// Actions that change data, checked all the way to the audit log.

import { expect, test } from "@playwright/test";

import { logIn, openAs, waitForData } from "./helpers";

test("a manager receives an order, and the audit log names them", async ({ page }) => {
  await openAs(page, "manager", "/suppliers");
  const receive = page.getByRole("button", { name: /^Receive SYN-PO-/ }).first();
  const label = (await receive.textContent()) ?? "";
  const poNumber = label.replace("Receive", "").trim();
  expect(poNumber).toMatch(/^SYN-PO-\d+$/);

  // The page asks for confirmation before booking stock.
  page.once("dialog", (dialog) => void dialog.accept());
  await receive.click();
  await expect(page.getByRole("status").filter({ hasText: "booked into stock" })).toHaveText(
    `${poNumber} was received and booked into stock.`,
  );
  await expect(page.getByRole("button", { name: `Receive ${poNumber}` })).toHaveCount(0);

  await page.getByRole("link", { name: "Audit log" }).click();
  await page.getByLabel("Kind of record").selectOption("purchase_order");
  const row = page.getByRole("row", { name: new RegExp(poNumber) });
  await expect(row).toContainText("e2e-manager@example.com");
  await expect(row).toContainText("purchase_order.received");
});

test("cancelling the confirmation receives nothing", async ({ page }) => {
  await openAs(page, "manager", "/suppliers");
  const receive = page.getByRole("button", { name: /^Receive SYN-PO-/ }).first();
  const name = (await receive.textContent()) ?? "";

  page.once("dialog", (dialog) => void dialog.dismiss());
  await receive.click();
  await expect(page.getByRole("button", { name })).toBeVisible();
  await expect(page.getByRole("status").filter({ hasText: "booked into stock" })).toHaveCount(0);
});

test("an admin adds a user, who can then log in", async ({ page }) => {
  const email = `new-analyst-${Date.now()}@example.com`;
  const password = "temporary-password-123";

  await openAs(page, "admin", "/users");
  await page.getByLabel("Email", { exact: true }).fill(email);
  await page.getByLabel("Full name", { exact: true }).fill("New Analyst");
  await page.getByLabel("Role", { exact: true }).selectOption("analyst");
  await page.getByLabel("Temporary password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Add user" }).click();
  await expect(page.getByRole("row", { name: new RegExp(email) })).toBeVisible();

  await page.getByRole("button", { name: "Log out" }).click();
  await logIn(page, email, password);
  await expect(page.getByText("New Analyst")).toBeVisible();
  await waitForData(page);
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
});
