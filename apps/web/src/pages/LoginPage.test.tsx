import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { App } from "../App";
import { fakeApi, KPIS, renderWithApp, USER } from "../testUtils";

async function logIn(email: string, password: string) {
  await userEvent.type(screen.getByLabelText("Email"), email);
  await userEvent.type(screen.getByLabelText("Password"), password);
  await userEvent.click(screen.getByRole("button", { name: "Log in" }));
}

describe("login", () => {
  it("sends visitors without a session to the login page", () => {
    renderWithApp(<App />, "/");
    expect(screen.getByRole("form", { name: "Log in" })).toBeInTheDocument();
    expect(screen.getByText("Simulated data")).toBeInTheDocument();
  });

  it("logs in and shows the overview with the user's name", async () => {
    vi.stubGlobal(
      "fetch",
      fakeApi({
        "/auth/login": [200, { access_token: "t", token_type: "bearer", expires_at: "", user: USER }],
        "/dashboard/kpis": [200, KPIS],
      }),
    );
    renderWithApp(<App />, "/");

    await logIn("analyst@example.com", "correct-horse-battery");

    expect(await screen.findByRole("heading", { name: "Overview" })).toBeInTheDocument();
    expect(screen.getByText(/Ann Analyst/)).toBeInTheDocument();
  });

  it("explains a wrong password without leaving the page", async () => {
    vi.stubGlobal("fetch", fakeApi({ "/auth/login": [401, { detail: "Incorrect email or password" }] }));
    renderWithApp(<App />, "/login");

    await logIn("analyst@example.com", "wrong-password-here");

    expect(await screen.findByRole("alert")).toHaveTextContent("Incorrect email or password.");
    expect(screen.getByRole("button", { name: "Log in" })).toBeEnabled();
  });

  it("explains when the API is down", async () => {
    vi.stubGlobal("fetch", fakeApi({ "/auth/login": new TypeError("Failed to fetch") }));
    renderWithApp(<App />, "/login");

    await logIn("analyst@example.com", "any-password-here");

    expect(await screen.findByRole("alert")).toHaveTextContent("The API cannot be reached");
  });

  it("keeps a saved session and logs out", async () => {
    sessionStorage.setItem("chainpilot.token", "saved");
    vi.stubGlobal("fetch", fakeApi({ "/auth/me": [200, USER], "/dashboard/kpis": [200, KPIS], "/auth/logout": [204, null] }));
    renderWithApp(<App />, "/");

    expect(await screen.findByRole("heading", { name: "Overview" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Log out" }));

    expect(await screen.findByRole("form", { name: "Log in" })).toBeInTheDocument();
    expect(sessionStorage.getItem("chainpilot.token")).toBeNull();
  });
});


describe("logout when the API is down", () => {
  it("still logs out in this browser, without an unhandled error", async () => {
    sessionStorage.setItem("chainpilot.token", "saved");
    vi.stubGlobal(
      "fetch",
      fakeApi({ "/auth/me": [200, USER], "/dashboard/kpis": [200, KPIS], "/auth/logout": new TypeError("Failed to fetch") }),
    );
    renderWithApp(<App />, "/");

    await screen.findByRole("heading", { name: "Overview" });
    await userEvent.click(screen.getByRole("button", { name: "Log out" }));

    expect(await screen.findByRole("form", { name: "Log in" })).toBeInTheDocument();
    expect(sessionStorage.getItem("chainpilot.token")).toBeNull();
  });
});
