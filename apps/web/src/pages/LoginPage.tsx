import { useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";

import { ApiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { DataBadge } from "../components/DataBadge";

export function LoginPage() {
  const { user, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const goTo = (location.state as { from?: string } | null)?.from ?? "/";

  if (user) return <Navigate to={goTo} replace />;

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email, password);
      navigate(goTo, { replace: true });
    } catch (problem) {
      setError(
        problem instanceof ApiError && problem.status === 401
          ? "Incorrect email or password."
          : problem instanceof Error
            ? problem.message
            : "Login failed.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="login">
      <h1>ChainPilot AI</h1>
      <DataBadge />
      <form onSubmit={submit} aria-label="Log in">
        <label htmlFor="email">Email</label>
        <input
          id="email"
          type="email"
          autoComplete="username"
          required
          value={email}
          onChange={(event) => setEmail(event.target.value)}
        />
        <label htmlFor="password">Password</label>
        <input
          id="password"
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />
        {error && (
          <p className="state-error" role="alert">
            {error}
          </p>
        )}
        <button type="submit" disabled={busy}>
          {busy ? "Logging in…" : "Log in"}
        </button>
      </form>
    </main>
  );
}
