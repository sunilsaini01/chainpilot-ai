// Keyboard only (P9-T5): a manager logs in, opens the approval queue, makes
// recommendations and approves one with Tab, Enter and Space only; every control
// reached on the way must show a visible focus outline.

import { expect, test, type Page } from "@playwright/test";

import { account } from "./helpers";

/** Presses Tab until the focused element matches, checking the outline at every stop. */
async function tabTo(page: Page, matches: (el: { tag: string; text: string; label: string }) => boolean, limit = 40) {
  for (let i = 0; i < limit; i++) {
    await page.keyboard.press("Tab");
    const focused = await page.evaluate(() => {
      const el = document.activeElement as HTMLElement | null;
      if (!el || el === document.body) return null;
      const style = getComputedStyle(el);
      return {
        tag: el.tagName.toLowerCase(),
        text: (el.textContent ?? "").trim(),
        label: el.getAttribute("aria-label") ?? "",
        outline: style.outlineStyle !== "none" && parseFloat(style.outlineWidth) > 0,
      };
    });
    if (!focused) continue;
    expect(focused.outline, `visible focus on <${focused.tag}> "${focused.label || focused.text}"`).toBe(true);
    if (matches(focused)) return;
  }
  throw new Error("The control was not reached with Tab");
}

test("a manager approves a recommendation with the keyboard only", async ({ page }) => {
  const { email, password } = account("manager");
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Log in" })).toBeVisible();

  await tabTo(page, (el) => el.tag === "input"); // the email field
  await page.keyboard.type(email);
  await page.keyboard.press("Tab");
  await page.keyboard.type(password);
  await page.keyboard.press("Enter");
  await expect(page.getByRole("button", { name: "Log out" })).toBeVisible();

  await tabTo(page, (el) => el.tag === "a" && el.text === "Approval queue");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { level: 1, name: "Approval queue" })).toBeVisible();

  await tabTo(page, (el) => el.text.startsWith("Make new recommendations"));
  await page.keyboard.press("Space");
  await expect(page.getByRole("status").filter({ hasText: "new proposals" })).toBeVisible();

  page.once("dialog", (dialog) => void dialog.accept()); // the confirmation, answered by the test
  await tabTo(page, (el) => el.label.startsWith("Approve "));
  await page.keyboard.press("Enter");
  await expect(page.getByRole("status").filter({ hasText: /Approved:/ })).toBeVisible();
});
