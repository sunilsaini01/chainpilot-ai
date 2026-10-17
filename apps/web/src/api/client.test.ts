import { describe, expect, it, vi } from "vitest";

import { API_URL, ApiError, api, errorMessage, getToken, login, logout } from "./client";

function respond(status: number, body: unknown, headers: Record<string, string> = {}) {
  return vi.fn().mockResolvedValue(
    new Response(body === null ? null : JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json", ...headers },
    }),
  );
}

describe("api client", () => {
  it("logs in, keeps the token and sends it afterwards", async () => {
    const user = { id: 1, email: "a@x.com", full_name: "A", role: "analyst" };
    vi.stubGlobal("fetch", respond(200, { access_token: "t-123", token_type: "bearer", expires_at: "", user }));

    expect(await login("a@x.com", "secret-password")).toEqual(user);
    expect(getToken()).toBe("t-123");

    const fetchKpis = respond(200, { label: "x" }, { "X-Total-Count": "7", "X-Dataset": "SIMULATED" });
    vi.stubGlobal("fetch", fetchKpis);
    const result = await api.kpis();
    const [url, init] = fetchKpis.mock.calls[0];
    expect(url).toBe(`${API_URL}/dashboard/kpis`);
    expect(new Headers(init.headers).get("Authorization")).toBe("Bearer t-123");
    expect(result).toMatchObject({ total: 7, dataset: "SIMULATED" });
  });

  it("forgets the token when the API says 401", async () => {
    sessionStorage.setItem("chainpilot.token", "old");
    vi.stubGlobal("fetch", respond(401, { detail: "Not authenticated" }));

    await expect(api.me()).rejects.toMatchObject({ status: 401, message: "Not authenticated" });
    expect(getToken()).toBeNull();
  });

  it("forgets the token on logout even if the API is down", async () => {
    sessionStorage.setItem("chainpilot.token", "t");
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    await expect(logout()).rejects.toBeInstanceOf(ApiError);
    expect(getToken()).toBeNull();
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
