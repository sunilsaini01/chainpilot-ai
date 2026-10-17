// Render a page inside the app's providers, at a given address.

import { render } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";

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
  body: unknown;
}

/**
 * A fetch stand-in that answers by "METHOD /path" or just "/path", e.g.
 * { "/auth/me": [200, body], "POST /users": [201, body] }. Every request is
 * recorded in `calls`, so a test can check what was sent.
 */
export function fakeApi(routes: Record<string, [number, unknown] | Error>) {
  const calls: Call[] = [];
  const fetchFn = async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const path = new URL(String(input)).pathname;
    const method = init.method ?? "GET";
    calls.push({ method, path, body: init.body ? JSON.parse(String(init.body)) : null });
    const answer = routes[`${method} ${path}`] ?? routes[path];
    if (answer === undefined) return new Response(JSON.stringify({ detail: "Not Found" }), { status: 404 });
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
