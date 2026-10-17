// Audit timeline (managers and admins): who did what, when. Newest first.

import { useState } from "react";

import { api } from "../api/client";
import type { AuditEvent } from "../api/types";
import { Pager } from "../components/Pager";
import { Empty, ErrorMessage, Loading } from "../components/States";
import { useApi } from "../hooks/useApi";

const PAGE = 50;
const KINDS = [
  "user",
  "inventory_movement",
  "purchase_order",
  "recommendation",
  "agent_run",
  "product",
  "warehouse",
  "seed",
  "forecast_run",
  "delivery_risk_run",
  "policy",
  "demand_profile",
];
const time = new Intl.DateTimeFormat("en-GB", { dateStyle: "medium", timeStyle: "short" });

/** The event's details as short "key: value" text (they never contain passwords). */
function summary(event: AuditEvent): string {
  return Object.entries(event.details)
    .map(([key, value]) => `${key.replaceAll("_", " ")}: ${typeof value === "object" ? JSON.stringify(value) : value}`)
    .join("; ");
}

export function AuditPage() {
  const [kind, setKind] = useState("");
  const [offset, setOffset] = useState(0);
  const params = { entity_type: kind, limit: PAGE, offset };
  const { result, error, reload } = useApi(() => api.auditEvents(params), JSON.stringify(params));

  return (
    <>
      <h1>Audit log</h1>
      <p className="label">
        Every login, stock movement, receipt, import, user change and copilot question, with who did it. Records are
        never edited or deleted.
      </p>
      <div className="filters">
        <label htmlFor="audit-kind">Kind of record</label>
        <select
          id="audit-kind"
          value={kind}
          onChange={(e) => {
            setKind(e.target.value);
            setOffset(0);
          }}
        >
          <option value="">All</option>
          {KINDS.map((k) => (
            <option key={k} value={k}>
              {k.replaceAll("_", " ")}
            </option>
          ))}
        </select>
      </div>
      {error ? (
        <ErrorMessage message={error.message} onRetry={reload} />
      ) : !result ? (
        <Loading what="the audit log" />
      ) : result.data.length === 0 ? (
        <Empty>No events of this kind yet.</Empty>
      ) : (
        <section className="card" aria-label="Audit events">
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th scope="col">When</th>
                  <th scope="col">Who</th>
                  <th scope="col">What</th>
                  <th scope="col">Record</th>
                  <th scope="col">Details</th>
                </tr>
              </thead>
              <tbody>
                {result.data.map((event) => (
                  <tr key={event.id}>
                    <td>{time.format(new Date(event.created_at))}</td>
                    <td>{event.actor_email ?? "system"}</td>
                    <td className="mono">{event.action}</td>
                    <td>
                      {event.entity_type.replaceAll("_", " ")}
                      {event.entity_id ? ` #${event.entity_id}` : ""}
                    </td>
                    <td className="details-cell">{summary(event)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pager offset={offset} limit={PAGE} total={result.total ?? result.data.length} onChange={setOffset} />
        </section>
      )}
    </>
  );
}
