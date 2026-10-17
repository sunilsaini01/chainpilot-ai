import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { App } from "../App";
import { fakeApi, KPIS, renderWithApp, USER } from "../testUtils";

async function openAccount(routes: Parameters<typeof fakeApi>[0]) {
  sessionStorage.setItem("chainpilot.token", "saved");
  const api = fakeApi({ "/auth/me": [200, USER], "/dashboard/kpis": [200, KPIS], ...routes });
  vi.stubGlobal("fetch", api);
  renderWithApp(<App />, "/account");
  await screen.findByRole("heading", { name: "My account" });
  return api;
}

async function fill(current: string, next: string, repeat: string) {
  await userEvent.type(screen.getByLabelText("Current password"), current);
  await userEvent.type(screen.getByLabelText("New password"), next);
  await userEvent.type(screen.getByLabelText("New password again"), repeat);
  await userEvent.click(screen.getByRole("button", { name: "Change password" }));
}

describe("my account", () => {
  it("shows who is logged in", async () => {
    await openAccount({});
    expect(screen.getByText("analyst@example.com")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "My account" })).toBeInTheDocument();
  });

  it("changes the password and clears the form", async () => {
    const api = await openAccount({ "POST /auth/password": [204, null] });

    await fill("old-password-123", "a-brand-new-password", "a-brand-new-password");

    expect(await screen.findByRole("status")).toHaveTextContent("Your password was changed.");
    const call = api.calls.find((c) => c.path === "/auth/password");
    expect(call?.body).toEqual({ current_password: "old-password-123", new_password: "a-brand-new-password" });
    expect(screen.getByLabelText("New password")).toHaveValue("");
  });

  it("checks length and the repeated password before asking the API", async () => {
    const api = await openAccount({});

    await fill("old-password-123", "short", "short");
    expect(screen.getByRole("alert")).toHaveTextContent("at least 12 characters");
    // The current password is still filled in; only the new ones change.
    await userEvent.clear(screen.getByLabelText("New password"));
    await userEvent.type(screen.getByLabelText("New password"), "a-brand-new-password");
    await userEvent.clear(screen.getByLabelText("New password again"));
    await userEvent.type(screen.getByLabelText("New password again"), "a-different-password");
    await userEvent.click(screen.getByRole("button", { name: "Change password" }));
    expect(screen.getByRole("alert")).toHaveTextContent("not the same");
    expect(api.calls.some((c) => c.path === "/auth/password")).toBe(false);
  });

  it("shows the API's answer to a wrong current password", async () => {
    await openAccount({ "POST /auth/password": [400, { detail: "The current password is incorrect" }] });

    await fill("wrong-password-1", "a-brand-new-password", "a-brand-new-password");

    expect(await screen.findByRole("alert")).toHaveTextContent("The current password is incorrect");
  });
});
