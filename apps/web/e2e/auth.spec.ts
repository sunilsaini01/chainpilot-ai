// Logging in and out, and what each role is allowed to see.

import { expect, test } from "@playwright/test";

import { API_URL, account, logIn, openAs } from "./helpers";

test("a wrong password is refused with a clear message", async ({ page }) => {
  await page.goto("/");
  await logIn(page, "nobody@example.com", "not-the-right-password");
  await expect(page.getByRole("alert")).toHaveText("Incorrect email or password.");
  await expect(page.getByRole("button", { name: "Log out" })).toHaveCount(0);
});

test("logging in works with the keyboard alone", async ({ page }) => {
  const { email, password } = account("analyst");
  await page.goto("/");
  await page.getByLabel("Email").focus();
  await page.keyboard.type(email);
  await page.keyboard.press("Tab");
  await page.keyboard.type(password);
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
});

test("a deep link returns to its page after login, and survives a reload", async ({ page }) => {
  await openAs(page, "analyst", "/suppliers");
  await expect(page.getByRole("heading", { name: "Suppliers and orders" })).toBeVisible();

  await page.reload();
  await expect(page.getByRole("heading", { name: "Suppliers and orders" })).toBeVisible();
});

test("logging out ends the session", async ({ page }) => {
  await openAs(page, "analyst");
  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page.getByRole("button", { name: "Log in" })).toBeVisible();

  await page.goto("/risks");
  await expect(page.getByRole("button", { name: "Log in" })).toBeVisible();
});

test("an analyst sees no manager or admin pages or actions", async ({ page }) => {
  await openAs(page, "analyst");
  const nav = page.getByRole("navigation", { name: "Main" });
  await expect(nav.getByRole("link", { name: "Ask the copilot" })).toBeVisible();
  await expect(nav.getByRole("link", { name: "Audit log" })).toHaveCount(0);
  await expect(nav.getByRole("link", { name: "Users" })).toHaveCount(0);

  await page.goto("/users");
  await expect(page.getByRole("alert")).toHaveText("This page is for administrators.");

  await page.goto("/suppliers");
  await expect(page.getByRole("heading", { name: "Purchase orders" })).toBeVisible();
  await expect(page.getByRole("cell", { name: /SYN-PO-/ }).first()).toBeVisible();
  await expect(page.getByRole("button", { name: /^Receive/ })).toHaveCount(0);
});

test("a manager sees the audit log but not the users page", async ({ page }) => {
  await openAs(page, "manager");
  const nav = page.getByRole("navigation", { name: "Main" });
  await expect(nav.getByRole("link", { name: "Audit log" })).toBeVisible();
  await expect(nav.getByRole("link", { name: "Users" })).toHaveCount(0);
});

test("the session is an httpOnly cookie that page scripts cannot read", async ({ page, context }) => {
  await openAs(page, "analyst");

  const [session] = (await context.cookies()).filter((c) => c.name === "chainpilot_session");
  expect(session).toMatchObject({ httpOnly: true, sameSite: "Strict" });
  expect(await page.evaluate(() => document.cookie)).not.toContain("chainpilot_session");
  expect(await page.evaluate(() => sessionStorage.length + localStorage.length)).toBe(0);
});

test("a change sent with the cookie but without the CSRF token is refused", async ({ page }) => {
  await openAs(page, "analyst");
  // What a script on another page of this site could try: the cookie goes along,
  // but it cannot know the CSRF token.
  const status = await page.evaluate(
    (api) => fetch(`${api}/auth/logout`, { method: "POST", credentials: "include" }).then((r) => r.status),
    API_URL,
  );
  expect(status).toBe(403);
  await page.reload();
  await expect(page.getByRole("button", { name: "Log out" })).toBeVisible(); // still logged in
});
