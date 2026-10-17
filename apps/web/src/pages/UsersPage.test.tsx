import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { App } from "../App";
import { ADMIN, fakeApi, KPIS, renderWithApp, USER } from "../testUtils";

async function openUsers(routes: Parameters<typeof fakeApi>[0] = {}) {
  const api = fakeApi({
    "/auth/me": [200, ADMIN],
    "/dashboard/kpis": [200, KPIS],
    "GET /users": [200, [ADMIN, USER]],
    ...routes,
  });
  vi.stubGlobal("fetch", api);
  renderWithApp(<App />, "/users");
  await screen.findByRole("heading", { name: "Users" });
  return api;
}

function rowOf(email: string) {
  return screen.getByRole("cell", { name: email }).closest("tr") as HTMLElement;
}

describe("users page", () => {
  it("is offered to admins only", async () => {
      vi.stubGlobal("fetch", fakeApi({ "/auth/me": [200, USER], "/dashboard/kpis": [200, KPIS] }));
    renderWithApp(<App />, "/users");

    expect(await screen.findByRole("alert")).toHaveTextContent("This page is for administrators.");
    expect(screen.queryByRole("link", { name: "Users" })).not.toBeInTheDocument();
  });

  it("lists users, and an admin cannot deactivate themselves", async () => {
    await openUsers();

    expect(screen.getByRole("link", { name: "Users" })).toBeInTheDocument();
    expect(within(rowOf("admin@example.com")).queryByRole("button", { name: /Deactivate/ })).not.toBeInTheDocument();
    expect(within(rowOf("analyst@example.com")).getByRole("button", { name: /Deactivate/ })).toBeInTheDocument();
  });

  it("adds a user with a role and a temporary password", async () => {
    const created = { ...USER, id: 3, email: "priya@example.com", full_name: "Priya", role: "manager" };
    const api = await openUsers({ "POST /users": [201, created] });

    await userEvent.type(screen.getByLabelText("Email"), "priya@example.com");
    await userEvent.type(screen.getByLabelText("Full name"), "Priya");
    await userEvent.selectOptions(screen.getByLabelText("Role"), "manager");
    await userEvent.type(screen.getByLabelText("Temporary password"), "welcome-to-chainpilot");
    await userEvent.click(screen.getByRole("button", { name: "Add user" }));

    expect(await screen.findByRole("status")).toHaveTextContent("Added priya@example.com as manager.");
    expect(api.calls.find((c) => c.method === "POST" && c.path === "/users")?.body).toEqual({
      email: "priya@example.com",
      full_name: "Priya",
      role: "manager",
      password: "welcome-to-chainpilot",
    });
    expect(rowOf("priya@example.com")).toBeInTheDocument();
  });

  it("shows the API's reason when an email is taken", async () => {
    await openUsers({ "POST /users": [409, { detail: "A user with email analyst@example.com already exists" }] });

    await userEvent.type(screen.getByLabelText("Email"), "analyst@example.com");
    await userEvent.type(screen.getByLabelText("Full name"), "Again");
    await userEvent.type(screen.getByLabelText("Temporary password"), "welcome-to-chainpilot");
    await userEvent.click(screen.getByRole("button", { name: "Add user" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("already exists");
  });

  it("changes a role and deactivates a user", async () => {
    const api = await openUsers({
      "PATCH /users/1": [200, { ...USER, role: "manager" }],
    });

    await userEvent.selectOptions(screen.getByLabelText("Role for analyst@example.com"), "manager");
    expect(await screen.findByRole("status")).toHaveTextContent("analyst@example.com is now manager.");
    expect(api.calls.find((c) => c.method === "PATCH")?.body).toEqual({ role: "manager" });

    await userEvent.click(within(rowOf("analyst@example.com")).getByRole("button", { name: /Deactivate/ }));
    expect(api.calls.filter((c) => c.method === "PATCH").at(-1)?.body).toEqual({ is_active: false });
  });

  it("sets a temporary password", async () => {
    const api = await openUsers({ "POST /users/1/password": [204, null] });

    await userEvent.click(within(rowOf("analyst@example.com")).getByRole("button", { name: /Set temporary password/ }));
    await userEvent.type(screen.getByLabelText("New temporary password for analyst@example.com"), "reset-password-2026");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByRole("status")).toHaveTextContent("Temporary password set for analyst@example.com");
    expect(api.calls.find((c) => c.path === "/users/1/password")?.body).toEqual({ new_password: "reset-password-2026" });
  });

  it("shows an error with retry when the list cannot load", async () => {
    await openUsers({ "GET /users": [403, { detail: "Not enough permissions" }] }).catch(() => undefined);
    expect(await screen.findByRole("alert")).toHaveTextContent("Not enough permissions");
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});
