// The approval workflow in a browser, against the real API: a manager makes
// recommendations from the synthetic test forecasts, then approves and rejects them.
// The tests run in order and build on each other (one stack, shared data).

import { expect, test, type Page } from "@playwright/test";

import { expectAccessible, openAs, waitForData } from "./helpers";

test.describe.configure({ mode: "serial" });

/** Shows one kind with the page's filter, then approves its first row, accepting the confirmation. */
async function approveFirst(page: Page, kind: "order" | "transfer"): Promise<string> {
  await page.getByLabel("Kind").selectOption(kind === "order" ? "reorder" : "transfer");
  await waitForData(page);
  const button = page.getByRole("button", { name: new RegExp(`^Approve ${kind} `) }).first();
  const label = ((await button.getAttribute("aria-label")) ?? "").replace(/^Approve /, "");
  page.once("dialog", (dialog) => {
    expect(dialog.message()).toContain(`Approve: ${label}?`);
    void dialog.accept();
  });
  await button.click();
  return label;
}

test("a manager makes recommendations to decide on", async ({ page }) => {
  await openAs(page, "manager", "/recommendations");
  await expect(page.getByText("No pending recommendations.")).toBeVisible();

  await page.getByRole("button", { name: "Make new recommendations" }).click();
  await expect(page.getByRole("status").filter({ hasText: "new proposals" })).toBeVisible();
  await expect(page.getByRole("button", { name: /^Approve transfer / }).first()).toBeVisible();
  await page.getByLabel("Kind").selectOption("reorder");
  await expect(page.getByRole("button", { name: /^Approve order / }).first()).toBeVisible();
  await waitForData(page);
  // The queue with its decision buttons, checked with real rows.
  await expectAccessible(page);
});

test("approving a reorder places a purchase order, seen on the orders page and in the audit log", async ({
  page,
}) => {
  await openAs(page, "manager", "/recommendations");
  const label = await approveFirst(page, "order");

  const done = page.getByRole("status").filter({ hasText: label });
  await expect(done).toContainText("purchase order PO-REC-");
  const poNumber = ((await done.textContent()) ?? "").match(/PO-REC-\d+/)?.[0] ?? "";
  await expect(page.getByRole("button", { name: `Approve ${label}` })).toHaveCount(0);

  await page.getByRole("link", { name: "Suppliers & orders" }).click();
  await expect(page.getByRole("row", { name: new RegExp(poNumber) })).toContainText("open");

  await page.getByRole("link", { name: "Audit log" }).click();
  await page.getByLabel("Kind of record").selectOption("recommendation");
  await expect(page.getByRole("row", { name: /recommendation\.approved/ }).first()).toContainText(
    "e2e-manager@example.com",
  );
});

test("approving a transfer moves the stock", async ({ page }) => {
  await openAs(page, "manager", "/recommendations");
  const label = await approveFirst(page, "transfer");

  await expect(page.getByRole("status").filter({ hasText: label })).toContainText("Approved: stock moved");
  await page.getByLabel("Show").selectOption("executed");
  await page.getByLabel("Kind").selectOption("");
  await expect(page.getByRole("region", { name: "executed recommendations" }).getByRole("row")).toHaveCount(3); // header + 2
});

test("rejecting needs a reason, which the history shows", async ({ page }) => {
  await openAs(page, "manager", "/recommendations");
  const reject = page.getByRole("button", { name: /^Reject / }).first();
  const label = ((await reject.getAttribute("aria-label")) ?? "").replace(/^Reject /, "");
  await reject.click();
  await page.getByLabel(`Reason for rejecting ${label}`).fill("Supplier is on hold this week");
  await page.getByRole("button", { name: "Reject", exact: true }).click();

  await expect(page.getByRole("status").filter({ hasText: label })).toContainText(
    "Rejected: Supplier is on hold this week",
  );
  const history = page.getByRole("region", { name: "Recent decisions" });
  await expect(history).toContainText("Rejected: Supplier is on hold this week");
});

test("a recommendation decided in another window cannot be decided again", async ({ browser, baseURL }) => {
  // Two managers have the queue open; the first approves, then the second tries.
  // Separate browser contexts, so each has its own login.
  const first = await browser.newPage({ baseURL });
  const second = await browser.newPage({ baseURL });
  await openAs(first, "manager", "/recommendations");
  await openAs(second, "admin", "/recommendations");
  await second.getByLabel("Kind").selectOption("reorder");
  await waitForData(second);

  const label = await approveFirst(first, "order");
  await expect(first.getByRole("status").filter({ hasText: label })).toContainText("PO-REC-");

  // The second window still shows the row (its list is from before the approval).
  second.once("dialog", (dialog) => void dialog.accept());
  await second.getByRole("button", { name: `Approve ${label}` }).click();
  await expect(second.getByRole("alert")).toContainText("not pending");
  await first.close();
  await second.close();
});

test("an analyst can read the queue but not decide", async ({ page }) => {
  await openAs(page, "analyst", "/recommendations");
  await expect(page.getByText("Only managers and administrators can approve or reject.")).toBeVisible();
  await expect(page.getByRole("cell", { name: /^SYN-/ }).first()).toBeVisible();
  await expect(page.getByRole("button", { name: /^Approve/ })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Make new recommendations" })).toHaveCount(0);
});
