// Users (admins only): create accounts, change roles, deactivate, set a temporary password.
// There is no public sign-up: an admin creates each account and gives the person a
// temporary password, which they change on "My account".

import { useCallback, useEffect, useState, type FormEvent } from "react";

import { api } from "../api/client";
import { ROLES, type Role, type User } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Empty, ErrorMessage, Loading } from "../components/States";

const MIN_LENGTH = 12;

function NewUserForm({ onCreated }: { onCreated: (user: User) => void }) {
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [role, setRole] = useState<Role>("analyst");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (password.length < MIN_LENGTH) return setError(`The password needs at least ${MIN_LENGTH} characters.`);
    setError(null);
    setBusy(true);
    try {
      const { data } = await api.createUser({ email, full_name: fullName, role, password });
      onCreated(data);
      setEmail("");
      setFullName("");
      setRole("analyst");
      setPassword("");
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : "The account could not be created.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card" aria-labelledby="new-user-heading">
      <h2 id="new-user-heading">Add a user</h2>
      <form className="grid-form" onSubmit={submit}>
        <label htmlFor="new-email">Email</label>
        <input id="new-email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        <label htmlFor="new-name">Full name</label>
        <input id="new-name" required value={fullName} onChange={(e) => setFullName(e.target.value)} />
        <label htmlFor="new-role">Role</label>
        <select id="new-role" value={role} onChange={(e) => setRole(e.target.value as Role)}>
          {ROLES.map((r) => (
            <option key={r}>{r}</option>
          ))}
        </select>
        <label htmlFor="new-password">Temporary password</label>
        <input
          id="new-password"
          type="text"
          autoComplete="off"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        {error && (
          <p className="state-error wide" role="alert">
            {error}
          </p>
        )}
        <button type="submit" className="wide" disabled={busy}>
          {busy ? "Adding…" : "Add user"}
        </button>
      </form>
    </section>
  );
}

function TemporaryPassword({ user, onDone }: { user: User; onDone: (message: string) => void }) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (password.length < MIN_LENGTH) return setError(`At least ${MIN_LENGTH} characters.`);
    try {
      await api.setPassword(user.id, password);
      onDone(`Temporary password set for ${user.email}. They were signed out everywhere.`);
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : "Could not set the password.");
    }
  }

  return (
    <form className="inline-form" onSubmit={submit}>
      <label htmlFor={`temp-${user.id}`}>New temporary password for {user.email}</label>
      <input id={`temp-${user.id}`} type="text" autoComplete="off" value={password} onChange={(e) => setPassword(e.target.value)} />
      <button type="submit">Save</button>
      <button type="button" className="secondary" onClick={() => onDone("")}>
        Cancel
      </button>
      {error && (
        <span className="state-error" role="alert">
          {error}
        </span>
      )}
    </form>
  );
}

export function UsersPage() {
  const { user: me } = useAuth();
  const [users, setUsers] = useState<User[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [resetFor, setResetFor] = useState<number | null>(null);

  const load = useCallback(() => {
    setError(null);
    api
      .users()
      .then(({ data }) => setUsers(data))
      .catch((problem: Error) => setError(problem.message));
  }, []);
  useEffect(load, [load]);

  async function change(target: User, changes: { role?: Role; is_active?: boolean }, done: string) {
    setMessage(null);
    try {
      const { data } = await api.updateUser(target.id, changes);
      setUsers((list) => list?.map((u) => (u.id === data.id ? data : u)) ?? null);
      setMessage(done);
    } catch (problem) {
      setMessage(problem instanceof Error ? problem.message : "The change failed.");
    }
  }

  if (error) return <ErrorMessage message={error} onRetry={load} />;
  if (!users) return <Loading what="users" />;

  return (
    <>
      <h1>Users</h1>
      <p className="label">
        There is no public sign-up: add each person here with a temporary password and give it to them. They change
        it on their "My account" page.
      </p>
      <NewUserForm
        onCreated={(created) => {
          setUsers((list) => [...(list ?? []), created]);
          setMessage(`Added ${created.email} as ${created.role}.`);
        }}
      />
      {message && (
        <p className="notice" role="status">
          {message}
        </p>
      )}
      <section className="card" aria-labelledby="list-heading">
        <h2 id="list-heading">All users</h2>
        {users.length === 0 ? (
          <Empty>No users yet.</Empty>
        ) : (
          <table>
            <thead>
              <tr>
                <th scope="col">Name</th>
                <th scope="col">Email</th>
                <th scope="col">Role</th>
                <th scope="col">Status</th>
                <th scope="col">Actions</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id}>
                  <td>{u.full_name}</td>
                  <td>{u.email}</td>
                  <td>
                    <label className="visually-hidden" htmlFor={`role-${u.id}`}>
                      Role for {u.email}
                    </label>
                    <select
                      id={`role-${u.id}`}
                      value={u.role}
                      onChange={(e) => void change(u, { role: e.target.value as Role }, `${u.email} is now ${e.target.value}.`)}
                    >
                      {ROLES.map((r) => (
                        <option key={r}>{r}</option>
                      ))}
                    </select>
                  </td>
                  <td>{u.is_active ? "Active" : "Deactivated"}</td>
                  <td className="actions">
                    {/* No button to deactivate yourself: that would lock you out. */}
                    {u.id !== me?.id && (
                      <button
                        type="button"
                        className="secondary"
                        onClick={() =>
                          void change(
                            u,
                            { is_active: !u.is_active },
                            `${u.email} was ${u.is_active ? "deactivated" : "reactivated"}.`,
                          )
                        }
                      >
                        {u.is_active ? "Deactivate" : "Reactivate"}
                        <span className="visually-hidden"> {u.email}</span>
                      </button>
                    )}
                    <button type="button" className="secondary" onClick={() => setResetFor(u.id)}>
                      Set temporary password<span className="visually-hidden"> for {u.email}</span>
                    </button>
                    {resetFor === u.id && (
                      <TemporaryPassword
                        user={u}
                        onDone={(done) => {
                          setResetFor(null);
                          if (done) setMessage(done);
                        }}
                      />
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </>
  );
}
