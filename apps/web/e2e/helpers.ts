// Shared steps for the browser tests. The users are created by run-e2e.sh with
// fresh random passwords, which it passes in through environment variables.

import AxeBuilder from "@axe-core/playwright";
import { expect, type Page } from "@playwright/test";

export type Role = "admin" | "manager" | "analyst";

export function account(role: Role): { email: string; password: string } {
  const password = process.env[`E2E_${role.toUpperCase()}_PASSWORD`];
  if (!password) throw new Error(`E2E_${role.toUpperCase()}_PASSWORD is not set: run the tests with e2e/run-e2e.sh`);
  return { email: `e2e-${role}@example.com`, password };
}

export async function logIn(page: Page, email: string, password: string): Promise<void> {
  // Wait for the login form itself: right after "Log out" the old page (which may
  // have its own "Email" field, like the users page) can still be on screen.
  const form = page.getByRole("form", { name: "Log in" });
  await expect(form).toBeVisible();
  await form.getByLabel("Email").fill(email);
  await form.getByLabel("Password").fill(password);
  await form.getByRole("button", { name: "Log in" }).click();
}

/** Opens the app as this role and waits for the overview. */
export async function openAs(page: Page, role: Role, path = "/"): Promise<void> {
  const { email, password } = account(role);
  await page.goto(path);
  await logIn(page, email, password);
  await expect(page.getByRole("button", { name: "Log out" })).toBeVisible();
}

/** Waits until no "Loading …" message is left on the page. */
export async function waitForData(page: Page): Promise<void> {
  await expect(page.getByRole("status").filter({ hasText: /^Loading/ })).toHaveCount(0);
}

/** Fails with a readable list if axe finds WCAG 2.1 A or AA problems on the page. */
export async function expectAccessible(page: Page): Promise<void> {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
  const problems = results.violations.map(
    (v) => `${v.id} (${v.impact}): ${v.help} at ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`,
  );
  expect(problems, `accessibility problems on ${page.url()}`).toEqual([]);
}
