// Demand forecasts for one M5 item at one M5 store (public Walmart data).

import { useState, type FormEvent } from "react";

import { api } from "../api/client";
import type { ForecastRow } from "../api/types";
import { Empty, ErrorMessage, Loading } from "../components/States";
import { useApi } from "../hooks/useApi";

const STORES = ["CA_1", "CA_2", "CA_3", "CA_4", "TX_1", "TX_2", "TX_3", "WI_1", "WI_2", "WI_3"];
const numbers = new Intl.NumberFormat("en-GB", { maximumFractionDigits: 2 });

/** Forecast line with its 80% range as a band. Decorative: the table below has the numbers. */
function ForecastChart({ rows }: { rows: ForecastRow[] }) {
  const width = 640;
  const height = 200;
  const pad = 24;
  const top = Math.max(...rows.map((r) => r.upper), 1);
  const x = (i: number) => pad + (i * (width - 2 * pad)) / Math.max(rows.length - 1, 1);
  const y = (v: number) => height - pad - (v / top) * (height - 2 * pad);
  const band = [
    ...rows.map((r, i) => `${x(i)},${y(r.upper)}`),
    ...rows.map((r, i) => `${x(i)},${y(r.lower)}`).reverse(),
  ].join(" ");
  const line = rows.map((r, i) => `${x(i)},${y(r.forecast)}`).join(" ");
  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="chart" aria-hidden="true">
      <polygon points={band} className="chart-band" />
      <polyline points={line} className="chart-line" />
      <line x1={pad} y1={height - pad} x2={width - pad} y2={height - pad} className="chart-axis" />
      <text x={pad} y={14} className="chart-label">
        max {numbers.format(top)} units/day
      </text>
    </svg>
  );
}

export function ForecastsPage() {
  const [store, setStore] = useState("CA_1");
  const [item, setItem] = useState("FOODS_3_090");
  const [chosen, setChosen] = useState({ store: "CA_1", item: "FOODS_3_090" });
  const params = { store_id: chosen.store, item_id: chosen.item, limit: 28 };
  const { result, error, reload } = useApi(() => api.forecasts(params), JSON.stringify(params));

  function show(event: FormEvent) {
    event.preventDefault();
    setChosen({ store, item: item.trim().toUpperCase() });
  }

  return (
    <>
      <h1>Demand forecasts</h1>
      <p className="label">
        Public M5 (Walmart) data, not the simulated products. 28 days per item and store, with an 80% range: in about
        8 of 10 days the real sales fall inside it.
      </p>
      <form className="filters" onSubmit={show}>
        <label htmlFor="fc-store">Store</label>
        <select id="fc-store" value={store} onChange={(e) => setStore(e.target.value)}>
          {STORES.map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
        <label htmlFor="fc-item">Item</label>
        <input id="fc-item" value={item} onChange={(e) => setItem(e.target.value)} placeholder="FOODS_3_090" required />
        <button type="submit">Show</button>
      </form>

      {error?.status === 404 ? (
        <Empty>No forecasts are imported yet.</Empty>
      ) : error ? (
        <ErrorMessage message={error.message} onRetry={reload} />
      ) : !result ? (
        <Loading what="the forecast" />
      ) : result.data.length === 0 ? (
        <Empty>
          No forecast for {chosen.item} at {chosen.store}. Item ids look like FOODS_3_090 or HOBBIES_1_001.
        </Empty>
      ) : (
        <section className="card" aria-label={`Forecast for ${chosen.item} at ${chosen.store}`}>
          <h2>
            {chosen.item} at {chosen.store}
          </h2>
          {result.dataset && <p className="label">{result.dataset}</p>}
          <ForecastChart rows={result.data} />
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th scope="col">Date</th>
                  <th scope="col">Forecast (units)</th>
                  <th scope="col">80% range</th>
                </tr>
              </thead>
              <tbody>
                {result.data.map((r) => (
                  <tr key={r.forecast_date}>
                    <td>{r.forecast_date}</td>
                    <td>{numbers.format(r.forecast)}</td>
                    <td>
                      {numbers.format(r.lower)} – {numbers.format(r.upper)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </>
  );
}
