// Overview: the headline numbers from GET /dashboard/kpis.

import { useCallback, useEffect, useState } from "react";

import { api } from "../api/client";
import type { DashboardKpis } from "../api/types";
import { ErrorMessage, Loading } from "../components/States";

const numbers = new Intl.NumberFormat("en-GB");
// The simulated data has no currency, so values are shown as plain amounts.
const money = new Intl.NumberFormat("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

function Kpi({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="kpi">
      <dt>{label}</dt>
      <dd>{typeof value === "number" ? numbers.format(value) : value}</dd>
    </div>
  );
}

export function OverviewPage() {
  const [kpis, setKpis] = useState<DashboardKpis | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setError(null);
    setKpis(null);
    api
      .kpis()
      .then(({ data }) => setKpis(data))
      .catch((problem: Error) => setError(problem.message));
  }, []);

  useEffect(load, [load]);

  if (error) return <ErrorMessage message={error} onRetry={load} />;
  if (!kpis) return <Loading what="the overview" />;

  const status = kpis.stock_status;
  return (
    <>
      <h1>Overview</h1>
      <p className="label">{kpis.label}</p>

      <section aria-labelledby="stock-heading" className="card">
        <h2 id="stock-heading">Stock</h2>
        <dl className="kpis">
          <Kpi label="Products" value={kpis.inventory.products} />
          <Kpi label="Warehouses" value={kpis.inventory.warehouses} />
          <Kpi label="Units on hand" value={kpis.inventory.units_on_hand} />
          <Kpi label="Stock value (at cost)" value={money.format(kpis.inventory.stock_value)} />
        </dl>
      </section>

      <section aria-labelledby="risk-heading" className="card">
        <h2 id="risk-heading">Stock-out risk</h2>
        {status ? (
          <dl className="kpis">
            <Kpi label="Out of stock" value={status.out_of_stock} />
            <Kpi label="At risk" value={status.at_risk} />
            <Kpi label="OK" value={status.ok} />
            <Kpi label="Excess" value={status.excess} />
            <Kpi label="Not assessed" value={status.unassessed} />
          </dl>
        ) : (
          <p className="state-empty">Not available: {kpis.stock_status_note}</p>
        )}
      </section>

      <section aria-labelledby="action-heading" className="card">
        <h2 id="action-heading">Waiting for action</h2>
        <dl className="kpis">
          <Kpi label="Proposed reorders" value={kpis.pending_recommendations.reorder} />
          <Kpi label="Proposed transfers" value={kpis.pending_recommendations.transfer} />
          <Kpi label="Open purchase orders" value={kpis.purchase_orders.open} />
          <Kpi label="Overdue purchase orders" value={kpis.purchase_orders.overdue} />
        </dl>
      </section>

      <section aria-labelledby="supplier-heading" className="card">
        <h2 id="supplier-heading">Suppliers (last 90 days)</h2>
        <dl className="kpis">
          <Kpi label="Good" value={kpis.supplier_ratings.good} />
          <Kpi label="Watch" value={kpis.supplier_ratings.watch} />
          <Kpi label="At risk" value={kpis.supplier_ratings.at_risk} />
          <Kpi label="Not rated" value={kpis.supplier_ratings.not_rated} />
        </dl>
      </section>
    </>
  );
}
