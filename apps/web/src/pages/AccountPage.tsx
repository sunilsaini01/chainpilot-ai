// "My account": who you are, and changing your own password.

import { useState, type FormEvent } from "react";

import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";

const MIN_LENGTH = 12; // the API's rule; checked here too for a quicker message

export function AccountPage() {
  const { user } = useAuth();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [repeat, setRepeat] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setDone(false);
    if (next.length < MIN_LENGTH) return setError(`The new password needs at least ${MIN_LENGTH} characters.`);
    if (next !== repeat) return setError("The two new passwords are not the same.");
    setError(null);
    setBusy(true);
    try {
      await api.changePassword(current, next);
      setDone(true);
      setCurrent("");
      setNext("");
      setRepeat("");
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : "The password could not be changed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <h1>My account</h1>
      {user && (
        <dl className="card details">
          <dt>Name</dt>
          <dd>{user.full_name}</dd>
          <dt>Email</dt>
          <dd>{user.email}</dd>
          <dt>Role</dt>
          <dd>{user.role}</dd>
        </dl>
      )}

      <section className="card" aria-labelledby="password-heading">
        <h2 id="password-heading">Change password</h2>
        <p className="label">
          At least {MIN_LENGTH} characters. Your other sessions (other browsers or devices) are signed out; this one
          stays.
        </p>
        <form className="stack" onSubmit={submit}>
          <label htmlFor="current-password">Current password</label>
          <input
            id="current-password"
            type="password"
            autoComplete="current-password"
            required
            value={current}
            onChange={(event) => setCurrent(event.target.value)}
          />
          <label htmlFor="new-password">New password</label>
          <input
            id="new-password"
            type="password"
            autoComplete="new-password"
            required
            value={next}
            onChange={(event) => setNext(event.target.value)}
          />
          <label htmlFor="repeat-password">New password again</label>
          <input
            id="repeat-password"
            type="password"
            autoComplete="new-password"
            required
            value={repeat}
            onChange={(event) => setRepeat(event.target.value)}
          />
          {error && (
            <p className="state-error" role="alert">
              {error}
            </p>
          )}
          {done && (
            <p className="state-ok" role="status">
              Your password was changed.
            </p>
          )}
          <button type="submit" disabled={busy}>
            {busy ? "Saving…" : "Change password"}
          </button>
        </form>
      </section>
    </>
  );
}
