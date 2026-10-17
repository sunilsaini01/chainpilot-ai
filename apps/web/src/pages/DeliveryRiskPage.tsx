// Late-delivery alerts for one dispatch day (public Olist marketplace data).

import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { DeliveryRiskRun } from "../api/types";
import { Badge } from "../components/Badge";
import { Empty, ErrorMessage, Loading } from "../components/States";
import { useApi } from "../hooks/useApi";

const percent = new Intl.NumberFormat("en-GB", { style: "percent", maximumFractionDigits: 1 });

function Alerts({ date }: { date: string }) {
  const { result, error, reload } = useApi(() => api.deliveryAlerts(date), date);
  if (error) return <ErrorMessage message={error.message} onRetry={reload} />;
  if (!result) return <Loading what="alerts" />;
  if (result.data.length === 0) return <Empty>No orders were dispatched on {date}.</Empty>;
  return (
    <section className="card" aria-label={`Alerts for ${date}`}>
      {result.dataset && <p className="label">{result.dataset}</p>}
      <p>
        {result.total ?? result.data.length} alerts: the riskiest 10% of the orders dispatched that day. An alert means
        "check this shipment", not "this will be late".
      </p>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th scope="col">Order</th>
              <th scope="col">Tier</th>
              <th scope="col">Day orders at or below this risk</th>
              <th scope="col">Chance of being late (approximate)</th>
              <th scope="col">Main reasons</th>
            </tr>
          </thead>
          <tbody>
            {result.data.map((s) => (
              <tr key={s.order_id}>
                <td className="mono">{s.order_id.slice(0, 12)}…</td>
                <td>
                  <Badge value={s.tier} />
                </td>
                <td>{percent.format(s.day_percentile)}</td>
                <td>{percent.format(s.probability)}</td>
                <td>{s.reasons.map((r) => r.feature.replaceAll("_", " ")).join(", ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export function DeliveryRiskPage() {
  const runs = useApi(() => api.deliveryRuns(), "runs");
  const [date, setDate] = useState("");
  const run: DeliveryRiskRun | undefined = runs.result?.data[0];

  // Start on the last day of the scored period.
  useEffect(() => {
    if (run && !date) setDate(run.period_end);
  }, [run, date]);

  return (
    <>
      <h1>Delivery risk</h1>
      <p className="label">
        Public Olist (Brazilian marketplace) orders from 2018, not ChainPilot's simulated suppliers. Each order was
        scored when it was handed to the carrier.
      </p>
      {runs.error ? (
        <ErrorMessage message={runs.error.message} onRetry={runs.reload} />
      ) : !runs.result ? (
        <Loading what="the scoring run" />
      ) : !run ? (
        <Empty>No delivery-risk scores are imported yet.</Empty>
      ) : (
        <>
          <div className="filters">
            <label htmlFor="dispatch-day">Dispatch day</label>
            <input
              id="dispatch-day"
              type="date"
              min={run.period_start}
              max={run.period_end}
              value={date}
              onChange={(e) => setDate(e.target.value)}
            />
            <span className="label">
              Scored days: {run.period_start} to {run.period_end}
            </span>
          </div>
          {date && <Alerts date={date} />}
        </>
      )}
    </>
  );
}
