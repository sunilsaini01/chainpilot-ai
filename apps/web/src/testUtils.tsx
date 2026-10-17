// Render a page inside the app's providers, at a given address.

import { render } from "@testing-library/react";
import { vi } from "vitest";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";

import { App } from "./App";
import { AuthProvider } from "./auth/AuthContext";

export function renderWithApp(ui: ReactNode, path = "/") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>{ui}</AuthProvider>
    </MemoryRouter>,
  );
}

export interface Call {
  method: string;
  path: string;
  params: URLSearchParams; // the query string, e.g. params.get("status")
  body: unknown;
  headers: Headers;
}

/** A fixed answer, a network failure, or a function of the request (e.g. fail once, then succeed). */
export type Answer = [number, unknown] | Error | ((call: Call) => [number, unknown] | Error);

/**
 * A fetch stand-in that answers by "METHOD /path" or just "/path", e.g.
 * { "/auth/me": [200, body], "POST /users": [201, body] }. Every request is
 * recorded in `calls`, so a test can check what was sent.
 */
export function fakeApi(routes: Record<string, Answer>) {
  const calls: Call[] = [];
  const fetchFn = async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = new URL(String(input));
    const path = url.pathname;
    const method = init.method ?? "GET";
    const call = {
      method,
      path,
      params: url.searchParams,
      body: init.body ? JSON.parse(String(init.body)) : null,
      headers: new Headers(init.headers),
    };
    calls.push(call);
    const route = routes[`${method} ${path}`] ?? routes[path];
    if (route === undefined) return new Response(JSON.stringify({ detail: "Not Found" }), { status: 404 });
    const answer = typeof route === "function" ? route(call) : route;
    if (answer instanceof Error) throw answer;
    const [status, body] = answer;
    // 204 No Content must not carry a body.
    const text = status === 204 ? null : JSON.stringify(body);
    return new Response(text, { status, headers: { "Content-Type": "application/json" } });
  };
  return Object.assign(fetchFn, { calls });
}

// Shared example data for the page tests.
export const USER = {
  id: 1,
  email: "analyst@example.com",
  full_name: "Ann Analyst",
  role: "analyst",
  is_active: true,
  created_at: "2026-10-17T08:00:00Z",
};
export const ADMIN = { ...USER, id: 9, email: "admin@example.com", full_name: "Ada Admin", role: "admin" };
export const KPIS = {
  label: "SIMULATED stock",
  inventory: { products: 200, warehouses: 4, units_on_hand: 160712, stock_value: 1234.5 },
  stock_status: { out_of_stock: 146, at_risk: 24, ok: 88, excess: 242, unassessed: 0 },
  stock_status_note: null,
  forecast_run_id: 1,
  pending_recommendations: { reorder: 24, transfer: 150 },
  purchase_orders: { open: 20, overdue: 2 },
  supplier_ratings: { good: 3, watch: 2, at_risk: 1, not_rated: 0 },
};

export const MANAGER = { ...USER, id: 5, email: "manager@example.com", full_name: "Max Manager", role: "manager" };

/** Answers every page needs: who is logged in, and the id-to-code lookups. */
export function baseRoutes(user: unknown = USER): Record<string, [number, unknown]> {
  return {
    "/auth/me": [200, user],
    "/dashboard/kpis": [200, KPIS],
    "/warehouses": [200, [{ id: 1, code: "SYN-WH1", name: "North DC", city: "Leeds", capacity_units: 60000 }]],
    "/suppliers": [200, [{ id: 4, code: "SYN-SUP04", name: "Far-East", country: "China", lead_time_days: 21, lead_time_std_days: "4.00" }]],
    "/products": [200, [{ id: 7, sku: "SYN-0007", name: "Mug", category: "kitchen" }]],
  };
}

/** With a saved session and `routes` as the API, render the app at `path`. */
export function openPage(path: string, routes: Record<string, Answer>, user: unknown = USER) {
  sessionStorage.setItem("chainpilot.token", "saved");
  const api = fakeApi({ ...baseRoutes(user), ...routes });
  vi.stubGlobal("fetch", api);
  renderWithApp(<App />, path);
  return api;
}
