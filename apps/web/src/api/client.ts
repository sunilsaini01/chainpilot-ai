// Small typed client for the ChainPilot API.
//
// The login token is kept in sessionStorage: it survives a page reload but is
// gone when the tab closes. (An httpOnly cookie would be safer against script
// injection; that hardening is planned with the approval/security phase.)

import type { DashboardKpis, NewUser, Role, TokenResponse, User } from "./types";

export const API_URL: string = import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000";
const TOKEN_KEY = "chainpilot.token";

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export function getToken(): string | null {
  try {
    return sessionStorage.getItem(TOKEN_KEY);
  } catch {
    return null; // storage blocked (e.g. private mode): behave as logged out
  }
}

function setToken(token: string | null): void {
  try {
    if (token) sessionStorage.setItem(TOKEN_KEY, token);
    else sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    // Storage blocked: the user simply has to log in again after a reload.
  }
}

/** A readable message from an API error body ({"detail": "..."} or a validation list). */
export function errorMessage(body: unknown, status: number): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    return detail
      .map((item: { loc?: unknown[]; msg?: string }) => {
        const field = (item.loc ?? []).filter((part) => part !== "body" && part !== "query").join(".");
        return field ? `${field}: ${item.msg}` : (item.msg ?? "invalid value");
      })
      .join("; ");
  }
  if (status === 0) return "The API cannot be reached. Is it running?";
  return `Request failed (HTTP ${status})`;
}

export interface ApiResult<T> {
  data: T;
  total: number | null; // X-Total-Count, for paged lists
  dataset: string | null; // X-Dataset label, when the endpoint sends one
}

export async function request<T>(path: string, init: RequestInit = {}): Promise<ApiResult<T>> {
  const headers = new Headers(init.headers);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");

  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, { ...init, headers });
  } catch {
    throw new ApiError(0, errorMessage(null, 0));
  }
  const body = response.status === 204 ? null : await response.json().catch(() => null);
  if (!response.ok) {
    if (response.status === 401) setToken(null); // expired or revoked: log in again
    throw new ApiError(response.status, errorMessage(body, response.status));
  }
  const total = response.headers.get("X-Total-Count");
  return {
    data: body as T,
    total: total === null ? null : Number(total),
    dataset: response.headers.get("X-Dataset"),
  };
}

export async function login(email: string, password: string): Promise<User> {
  const { data } = await request<TokenResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  setToken(data.access_token);
  return data.user;
}

export async function logout(): Promise<void> {
  try {
    await request<null>("/auth/logout", { method: "POST" });
  } finally {
    setToken(null); // even if the API is unreachable, forget the token here
  }
}

function post<T>(path: string, body: unknown): Promise<ApiResult<T>> {
  return request<T>(path, { method: "POST", body: JSON.stringify(body) });
}

export const api = {
  me: () => request<User>("/auth/me"),
  kpis: () => request<DashboardKpis>("/dashboard/kpis"),
  changePassword: (currentPassword: string, newPassword: string) =>
    post<null>("/auth/password", { current_password: currentPassword, new_password: newPassword }),
  // Admin only (the API checks the role on every call).
  users: () => request<User[]>("/users?limit=200"),
  createUser: (user: NewUser) => post<User>("/users", user),
  updateUser: (id: number, changes: { role?: Role; is_active?: boolean; full_name?: string }) =>
    request<User>(`/users/${id}`, { method: "PATCH", body: JSON.stringify(changes) }),
  setPassword: (id: number, newPassword: string) =>
    post<null>(`/users/${id}/password`, { new_password: newPassword }),
};
