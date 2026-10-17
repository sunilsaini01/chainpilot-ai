import { describe, expect, it, vi } from "vitest";

import { API_URL, ApiError, api, errorMessage, getCsrfToken, login, logout } from "./client";

function respond(status: number, body: unknown, headers: Record<string, string> = {}) {
  return vi.fn().mockResolvedValue(
    new Response(body === null ? null : JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json", ...headers },
    }),
  );
}

describe("api client", () => {
  it("logs in with the cookie: credentials on every request, CSRF token only on changes", async () => {
    const user = { id: 1, email: "a@x.com", full_name: "A", role: "analyst" };
    const loginAnswer = { access_token: "t-123", token_type: "bearer", expires_at: "", csrf_token: "c-9", user };
    vi.stubGlobal("fetch", respond(200, loginAnswer));

    expect(await login("a@x.com", "secret-password")).toEqual(user);
    expect(getCsrfToken()).toBe("c-9");
    expect(sessionStorage.length).toBe(0); // the session is the httpOnly cookie, not stored here

    const fetchKpis = respond(200, { label: "x" }, { "X-Total-Count": "7", "X-Dataset": "SIMULATED" });
    vi.stubGlobal("fetch", fetchKpis);
    const result = await api.kpis();
    const [url, init] = fetchKpis.mock.calls[0];
    expect(url).toBe(`${API_URL}/dashboard/kpis`);
    expect(init.credentials).toBe("include");
    const readHeaders = new Headers(init.headers);
    expect(readHeaders.get("X-CSRF-Token")).toBeNull(); // a read needs no CSRF token
    expect(readHeaders.get("Authorization")).toBeNull(); // the token is never sent by script
    expect(result).toMatchObject({ total: 7, dataset: "SIMULATED" });

    const fetchReceive = respond(200, {});
    vi.stubGlobal("fetch", fetchReceive);
    await api.receiveOrder(5);
    const [, postInit] = fetchReceive.mock.calls[0];
    expect(postInit.credentials).toBe("include");
    expect(new Headers(postInit.headers).get("X-CSRF-Token")).toBe("c-9");
  });

  it("gets the CSRF token back from /auth/me after a reload", async () => {
    vi.stubGlobal("fetch", respond(200, { id: 1, email: "a@x.com", csrf_token: "c-reload" }));
    await api.me();
    expect(getCsrfToken()).toBe("c-reload");
  });

  it("forgets the CSRF token when the API says 401", async () => {
    vi.stubGlobal("fetch", respond(200, { id: 1, csrf_token: "old" }));
    await api.me();
    vi.stubGlobal("fetch", respond(401, { detail: "Not authenticated" }));

    await expect(api.me()).rejects.toMatchObject({ status: 401, message: "Not authenticated" });
    expect(getCsrfToken()).toBeNull();
  });

  it("forgets the session on logout even if the API is down", async () => {
    vi.stubGlobal("fetch", respond(200, { id: 1, csrf_token: "c" }));
    await api.me();
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    await expect(logout()).rejects.toBeInstanceOf(ApiError);
    expect(getCsrfToken()).toBeNull();
  });

  it("says when the API cannot be reached", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    await expect(api.kpis()).rejects.toMatchObject({ status: 0, message: "The API cannot be reached. Is it running?" });
  });
});

describe("errorMessage", () => {
  it("reads plain and validation errors", () => {
    expect(errorMessage({ detail: "At most 20 investigations per hour" }, 429)).toBe(
      "At most 20 investigations per hour",
    );
    expect(
      errorMessage({ detail: [{ loc: ["body", "question"], msg: "String should have at least 1 character" }] }, 422),
    ).toBe("question: String should have at least 1 character");
    expect(errorMessage(null, 500)).toBe("Request failed (HTTP 500)");
  });
});
