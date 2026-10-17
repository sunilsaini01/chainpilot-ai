// Proposed reorders and transfers. Nothing is ordered or moved until a manager
// approves it (the approval workflow comes in P7).

import { useState, type FormEvent } from "react";

import { api } from "../api/client";
import type { Recommendation } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Badge } from "../components/Badge";
import { Pager } from "../components/Pager";
import { Empty, ErrorMessage, Loading } from "../components/States";
import { useApi } from "../hooks/useApi";
import { useLookups } from "../hooks/useLookups";

const PAGE = 50;
const REASONS: Record<string, string> = {
  ordered: "order up to the target",
  raised_to_moq: "raised to the supplier's minimum order",
  limited: "limited by free space",
  transfer_spare_stock: "spare stock at another site",
};

function from(rec: Recommendation, lookups: ReturnType<typeof useLookups>) {
  return rec.kind === "transfer"
    ? `warehouse ${lookups.warehouseCode(rec.source_warehouse_id)}`
    : `supplier ${lookups.supplierCode(rec.supplier_id)}`;
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

export function RecommendationsPage() {
  const { user } = useAuth();
  const lookups = useLookups();
  const [kind, setKind] = useState("");
  const [offset, setOffset] = useState(0);
  const [message, setMessage] = useState<string | null>(null);
  const params = { status: "pending", kind, limit: PAGE, offset };
  const { result, error, reload } = useApi(() => api.recommendations(params), JSON.stringify(params));
  const canGenerate = user?.role === "manager" || user?.role === "admin";

  return (
    <>
      <h1>Recommendations</h1>
      <p className="label">
        Proposals only: nothing is ordered or moved until a manager approves it (approvals come in a later step).
        Transfers of spare stock come first, then supplier orders.
      </p>
      {canGenerate && (
        <Generate
          onDone={(done) => {
            setMessage(done);
            setOffset(0);
            reload();
          }}
        />
      )}
      {message && (
        <p className="notice" role="status">
          {message}
        </p>
      )}
      <div className="filters">
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
        <Empty>No pending recommendations.{canGenerate ? " Use the button above to make some." : ""}</Empty>
      ) : (
        <section className="card" aria-label="Pending recommendations">
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
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <Pager offset={offset} limit={PAGE} total={result.total ?? result.data.length} onChange={setOffset} />
        </section>
      )}
    </>
  );
}
