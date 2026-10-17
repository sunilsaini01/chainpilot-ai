// The approval queue: proposed reorders and transfers. Nothing is ordered or
// moved until a manager approves it; approving carries it out at once (simulated).

import { useRef, useState, type FormEvent } from "react";

import { api, newIdempotencyKey } from "../api/client";
import type { Approval, Recommendation } from "../api/types";
import { atLeast, useAuth } from "../auth/AuthContext";
import { Badge } from "../components/Badge";
import { Pager } from "../components/Pager";
import { Empty, ErrorMessage, Loading } from "../components/States";
import { useApi } from "../hooks/useApi";
import { useLookups } from "../hooks/useLookups";

const PAGE = 50;
const DECISIONS_PAGE = 10;
const REASONS: Record<string, string> = {
  ordered: "order up to the target",
  raised_to_moq: "raised to the supplier's minimum order",
  limited: "limited by free space",
  transfer_spare_stock: "spare stock at another site",
};
const STATUSES = ["pending", "executed", "failed", "rejected", "superseded"];
const DAY_MS = 24 * 60 * 60 * 1000;

type Lookups = ReturnType<typeof useLookups>;

function from(rec: Recommendation, lookups: Lookups) {
  return rec.kind === "transfer"
    ? `warehouse ${lookups.warehouseCode(rec.source_warehouse_id)}`
    : `supplier ${lookups.supplierCode(rec.supplier_id)}`;
}

/** "today", "1 day ago", "5 days ago": old proposals may no longer fit the stock. */
export function age(createdAt: string, now: Date = new Date()): string {
  const days = Math.floor((now.getTime() - new Date(createdAt).getTime()) / DAY_MS);
  if (days <= 0) return "today";
  return days === 1 ? "1 day ago" : `${days} days ago`;
}

/** One sentence for what happened, shown after a decision and in the history. */
export function describeOutcome(approval: Approval): string {
  const details = approval.outcome_details;
  if (approval.decision === "rejected") return `Rejected: ${approval.comment}`;
  if (approval.outcome === "failed") return `Approved, but it could not be carried out: ${details.error}`;
  if (details.po_number) return `Approved: purchase order ${details.po_number} placed, expected ${details.expected_date}`;
  return `Approved: stock moved (${details.reference})`;
}

function summary(rec: Recommendation, lookups: Lookups): string {
  const sku = rec.details.item?.sku ?? rec.details.destination?.sku ?? lookups.sku(rec.product_id);
  const to = lookups.warehouseCode(rec.warehouse_id);
  return rec.kind === "transfer"
    ? `transfer ${rec.quantity} × ${sku} from ${lookups.warehouseCode(rec.source_warehouse_id)} to ${to}`
    : `order ${rec.quantity} × ${sku} for ${to} from ${lookups.supplierCode(rec.supplier_id)}`;
}

function Generate({ onDone }: { onDone: (message: string) => void }) {
  const [level, setLevel] = useState("95");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const { data } = await api.generateRecommendations(Number(level) / 100);
      onDone(`Made ${data.length} new proposals; the earlier pending ones were replaced.`);
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : "Could not make recommendations.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="filters" onSubmit={submit}>
      <label htmlFor="service-level">Service level (%)</label>
      <input
        id="service-level"
        type="number"
        min={50}
        max={99.9}
        step={0.1}
        value={level}
        onChange={(e) => setLevel(e.target.value)}
      />
      <button type="submit" disabled={busy}>
        {busy ? "Working…" : "Make new recommendations"}
      </button>
      {error && (
        <span className="state-error" role="alert">
          {error}
        </span>
      )}
    </form>
  );
}

/** Approve and Reject buttons for one pending recommendation; Reject asks for a reason. */
function DecisionButtons({
  rec,
  label,
  onDecide,
}: {
  rec: Recommendation;
  label: string;
  onDecide: (rec: Recommendation, decision: "approve" | "reject", comment: string | null) => void;
}) {
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");

  if (rejecting) {
    return (
      <form
        className="inline-form"
        onSubmit={(event) => {
          event.preventDefault();
          onDecide(rec, "reject", reason);
        }}
      >
        <label htmlFor={`reason-${rec.id}`}>Reason for rejecting {label}</label>
        <input id={`reason-${rec.id}`} required maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} />
        <button type="submit">Reject</button>
        <button type="button" className="secondary" onClick={() => setRejecting(false)}>
          Cancel
        </button>
      </form>
    );
  }
  return (
    <>
      {/* The full name tells screen-reader users which row; it starts with the visible word. */}
      <button type="button" aria-label={`Approve ${label}`} onClick={() => onDecide(rec, "approve", null)}>
        Approve
      </button>{" "}
      <button type="button" className="secondary" aria-label={`Reject ${label}`} onClick={() => setRejecting(true)}>
        Reject
      </button>
    </>
  );
}

function Decisions({ refresh }: { refresh: number }) {
  const [offset, setOffset] = useState(0);
  const params = { limit: DECISIONS_PAGE, offset };
  const { result, error, reload } = useApi(() => api.approvals(params), `${JSON.stringify(params)}-${refresh}`);
  const time = new Intl.DateTimeFormat("en-GB", { dateStyle: "medium", timeStyle: "short" });

  return (
    <section className="card" aria-labelledby="decisions-heading">
      <h2 id="decisions-heading">Recent decisions</h2>
      {error ? (
        <ErrorMessage message={error.message} onRetry={reload} />
      ) : !result ? (
        <Loading what="decisions" />
      ) : result.data.length === 0 ? (
        <Empty>No decisions yet.</Empty>
      ) : (
        <>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th scope="col">When</th>
                  <th scope="col">Who</th>
                  <th scope="col">Recommendation</th>
                  <th scope="col">Result</th>
                </tr>
              </thead>
              <tbody>
                {result.data.map((approval) => (
                  <tr key={approval.id}>
                    <td>{time.format(new Date(approval.created_at))}</td>
                    <td>{approval.decided_by_email}</td>
                    <td>#{approval.recommendation_id}</td>
                    <td>
                      <Badge value={approval.outcome ?? approval.decision} /> {describeOutcome(approval)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pager offset={offset} limit={DECISIONS_PAGE} total={result.total ?? result.data.length} onChange={setOffset} />
        </>
      )}
    </section>
  );
}

export function RecommendationsPage() {
  const { user } = useAuth();
  const lookups = useLookups();
  const [status, setStatus] = useState("pending");
  const [kind, setKind] = useState("");
  const [offset, setOffset] = useState(0);
  const [message, setMessage] = useState<{ text: string; ok: boolean } | null>(null);
  const [decided, setDecided] = useState(0); // bumps the decision history after each decision
  // One key per recommendation and decision: clicking again after a lost answer
  // sends the same key, so the API returns the first result instead of acting twice.
  const keys = useRef(new Map<string, string>());
  const params = { status, kind, limit: PAGE, offset };
  const { result, error, reload } = useApi(() => api.recommendations(params), JSON.stringify(params));
  const canDecide = !!user && atLeast(user.role, "manager");

  async function decide(rec: Recommendation, decision: "approve" | "reject", comment: string | null) {
    const label = summary(rec, lookups);
    if (decision === "approve") {
      const effect = rec.kind === "transfer" ? "The stock is moved now." : "A purchase order is placed now.";
      if (!window.confirm(`Approve: ${label}? ${effect}`)) return;
    }
    const keyName = `${rec.id}-${decision}`;
    if (!keys.current.has(keyName)) keys.current.set(keyName, newIdempotencyKey());
    setMessage(null);
    try {
      const { data } = await api.decide(rec.id, decision, comment, keys.current.get(keyName)!);
      setMessage({ text: `${label}: ${describeOutcome(data)}`, ok: data.outcome !== "failed" });
      setDecided((n) => n + 1);
      reload();
    } catch (problem) {
      setMessage({ text: problem instanceof Error ? problem.message : "The decision was not saved.", ok: false });
    }
  }

  return (
    <>
      <h1>Approval queue</h1>
      <p className="label">
        Proposed transfers and supplier orders. Nothing is ordered or moved until a manager approves it; approving
        carries it out at once (simulated). Transfers of spare stock come first, then supplier orders.
        {canDecide ? "" : " Only managers and administrators can approve or reject."}
      </p>
      {canDecide && (
        <Generate
          onDone={(done) => {
            setMessage({ text: done, ok: true });
            setStatus("pending");
            setOffset(0);
            reload();
          }}
        />
      )}
      {message && (
        <p className={message.ok ? "notice" : "state-error"} role={message.ok ? "status" : "alert"}>
          {message.text}
        </p>
      )}
      <div className="filters">
        <label htmlFor="rec-status">Show</label>
        <select
          id="rec-status"
          value={status}
          onChange={(e) => {
            setStatus(e.target.value);
            setOffset(0);
          }}
        >
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <label htmlFor="rec-kind">Kind</label>
        <select
          id="rec-kind"
          value={kind}
          onChange={(e) => {
            setKind(e.target.value);
            setOffset(0);
          }}
        >
          <option value="">All</option>
          <option value="reorder">reorder</option>
          <option value="transfer">transfer</option>
        </select>
      </div>

      {error ? (
        <ErrorMessage message={error.message} onRetry={reload} />
      ) : !result ? (
        <Loading what="recommendations" />
      ) : result.data.length === 0 ? (
        <Empty>
          No {status} recommendations.{canDecide && status === "pending" ? " Use the button above to make some." : ""}
        </Empty>
      ) : (
        <section className="card" aria-label={`${status} recommendations`}>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th scope="col">Kind</th>
                  <th scope="col">SKU</th>
                  <th scope="col">To warehouse</th>
                  <th scope="col">From</th>
                  <th scope="col">Quantity</th>
                  <th scope="col">Why</th>
                  <th scope="col">Stock + on order → target</th>
                  <th scope="col">Made</th>
                  {status === "pending" && canDecide && <th scope="col">Decision</th>}
                </tr>
              </thead>
              <tbody>
                {result.data.map((rec) => {
                  const item = rec.details.item ?? rec.details.destination ?? {};
                  return (
                    <tr key={rec.id}>
                      <td>
                        <Badge value={rec.kind} />
                      </td>
                      <td>{item.sku ?? lookups.sku(rec.product_id)}</td>
                      <td>{item.warehouse_code ?? lookups.warehouseCode(rec.warehouse_id)}</td>
                      <td>{from(rec, lookups)}</td>
                      <td>{rec.quantity}</td>
                      <td>{REASONS[rec.reason] ?? rec.reason}</td>
                      <td>
                        {item.position ?? "?"} → {item.target_level ?? "?"}
                      </td>
                      <td>{age(rec.created_at)}</td>
                      {status === "pending" && canDecide && (
                        <td>
                          <DecisionButtons rec={rec} label={summary(rec, lookups)} onDecide={decide} />
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <Pager offset={offset} limit={PAGE} total={result.total ?? result.data.length} onChange={setOffset} />
        </section>
      )}
      <Decisions refresh={decided} />
    </>
  );
}
