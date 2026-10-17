// Suppliers (on-time ratings) and purchase orders. Managers can receive an open order.

import { useState } from "react";

import { api } from "../api/client";
import type { PurchaseOrder } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Badge } from "../components/Badge";
import { Pager } from "../components/Pager";
import { Empty, ErrorMessage, Loading } from "../components/States";
import { useApi } from "../hooks/useApi";
import { useLookups } from "../hooks/useLookups";

const PAGE = 25;
const percent = new Intl.NumberFormat("en-GB", { style: "percent", maximumFractionDigits: 1 });

function SupplierRatings() {
  const { result, error, reload } = useApi(() => api.supplierRisks(), "ratings");
  if (error) return <ErrorMessage message={error.message} onRetry={reload} />;
  if (!result) return <Loading what="supplier ratings" />;
  if (result.data.length === 0) return <Empty>No suppliers yet.</Empty>;
  return (
    <section className="card" aria-labelledby="ratings-heading">
      <h2 id="ratings-heading">Suppliers: on-time delivery, last 90 days</h2>
      <p className="label">Good: at least 90% on time. Watch: 75% to 90%. At risk: under 75%. Not rated: under 5 orders.</p>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th scope="col">Supplier</th>
              <th scope="col">Rating</th>
              <th scope="col">On time</th>
              <th scope="col">Orders received</th>
              <th scope="col">Average days late</th>
              <th scope="col">Open orders</th>
              <th scope="col">Overdue orders</th>
            </tr>
          </thead>
          <tbody>
            {result.data.map((s) => (
              <tr key={s.supplier_id}>
                <td>
                  {s.code} <span className="label">{s.name}</span>
                </td>
                <td>
                  <Badge value={s.rating} />
                </td>
                <td>{s.on_time_rate === null ? "–" : percent.format(s.on_time_rate)}</td>
                <td>{s.received_orders}</td>
                <td>{s.average_days_late ?? "–"}</td>
                <td>{s.open_orders}</td>
                <td>{s.overdue_orders.length ? s.overdue_orders.join(", ") : "none"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function isOverdue(order: PurchaseOrder): boolean {
  return order.status === "open" && order.expected_date < new Date().toISOString().slice(0, 10);
}

function PurchaseOrders() {
  const { user } = useAuth();
  const lookups = useLookups();
  const [status, setStatus] = useState("open");
  const [offset, setOffset] = useState(0);
  const [message, setMessage] = useState<{ text: string; ok: boolean } | null>(null);
  const params = { status, limit: PAGE, offset };
  const { result, error, reload } = useApi(() => api.purchaseOrders(params), JSON.stringify(params));
  const canReceive = user?.role === "manager" || user?.role === "admin";

  async function receive(order: PurchaseOrder) {
    if (!window.confirm(`Receive ${order.po_number}? Every line is booked into stock.`)) return;
    setMessage(null);
    try {
      await api.receiveOrder(order.id);
      setMessage({ text: `${order.po_number} was received and booked into stock.`, ok: true });
      reload();
    } catch (problem) {
      setMessage({ text: problem instanceof Error ? problem.message : "Receiving failed.", ok: false });
    }
  }

  return (
    <section className="card" aria-labelledby="orders-heading">
      <h2 id="orders-heading">Purchase orders</h2>
      <div className="filters">
        <label htmlFor="po-status">Status</label>
        <select
          id="po-status"
          value={status}
          onChange={(e) => {
            setStatus(e.target.value);
            setOffset(0);
          }}
        >
          <option value="open">open</option>
          <option value="received">received</option>
          <option value="">all</option>
        </select>
      </div>
      {message && (
        <p className={message.ok ? "notice" : "state-error"} role={message.ok ? "status" : "alert"}>
          {message.text}
        </p>
      )}
      {error ? (
        <ErrorMessage message={error.message} onRetry={reload} />
      ) : !result ? (
        <Loading what="purchase orders" />
      ) : result.data.length === 0 ? (
        <Empty>No purchase orders with this status.</Empty>
      ) : (
        <>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th scope="col">Order</th>
                  <th scope="col">Supplier</th>
                  <th scope="col">Warehouse</th>
                  <th scope="col">Status</th>
                  <th scope="col">Ordered</th>
                  <th scope="col">Expected</th>
                  <th scope="col">Lines / units</th>
                  {canReceive && <th scope="col">Action</th>}
                </tr>
              </thead>
              <tbody>
                {result.data.map((order) => (
                  <tr key={order.id}>
                    <td>{order.po_number}</td>
                    <td>{lookups.supplierCode(order.supplier_id)}</td>
                    <td>{lookups.warehouseCode(order.warehouse_id)}</td>
                    <td>
                      <Badge value={isOverdue(order) ? "overdue" : order.status} />
                    </td>
                    <td>{order.ordered_date}</td>
                    <td>{order.expected_date}</td>
                    <td>
                      {order.lines.length} / {order.lines.reduce((sum, line) => sum + line.quantity, 0)}
                    </td>
                    {canReceive && (
                      <td>
                        {order.status === "open" && (
                          <button type="button" className="secondary" onClick={() => void receive(order)}>
                            Receive<span className="visually-hidden"> {order.po_number}</span>
                          </button>
                        )}
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pager offset={offset} limit={PAGE} total={result.total ?? result.data.length} onChange={setOffset} />
        </>
      )}
    </section>
  );
}

export function SuppliersPage() {
  return (
    <>
      <h1>Suppliers and orders</h1>
      <p className="label">Simulated suppliers and purchase orders (SYN- codes).</p>
      <SupplierRatings />
      <PurchaseOrders />
    </>
  );
}
