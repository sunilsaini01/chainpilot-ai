// Stock-out risks: every product at every warehouse, most urgent first.

import { useState } from "react";

import { api } from "../api/client";
import type { StockStatus } from "../api/types";
import { Badge } from "../components/Badge";
import { Pager } from "../components/Pager";
import { Empty, ErrorMessage, Loading } from "../components/States";
import { useApi } from "../hooks/useApi";
import { useLookups } from "../hooks/useLookups";

const PAGE = 50;
const STATUSES: StockStatus[] = ["out_of_stock", "at_risk", "ok", "excess"];
const numbers = new Intl.NumberFormat("en-GB", { maximumFractionDigits: 1 });

export function RisksPage() {
  const { warehouses } = useLookups();
  const [warehouseId, setWarehouseId] = useState("");
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);
  const params = { warehouse_id: warehouseId, status, limit: PAGE, offset };
  const { result, error, reload } = useApi(() => api.risks(params), JSON.stringify(params));

  function filter(change: () => void) {
    change();
    setOffset(0); // new filters start at the first page
  }

  return (
    <>
      <h1>Stock-out risks</h1>
      <p className="label">
        Every product at every warehouse: stock on hand plus open orders compared with the reorder point and the
        target level (95% service level). Most urgent first.
      </p>
      <div className="filters">
        <label htmlFor="risk-warehouse">Warehouse</label>
        <select id="risk-warehouse" value={warehouseId} onChange={(e) => filter(() => setWarehouseId(e.target.value))}>
          <option value="">All</option>
          {warehouses.map((w) => (
            <option key={w.id} value={w.id}>
              {w.code} – {w.name}
            </option>
          ))}
        </select>
        <label htmlFor="risk-status">Status</label>
        <select id="risk-status" value={status} onChange={(e) => filter(() => setStatus(e.target.value))}>
          <option value="">All</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {s.replaceAll("_", " ")}
            </option>
          ))}
        </select>
      </div>

      {error?.status === 409 ? (
        <Empty>No risks yet: {error.message}. An administrator imports the forecasts and links the demand profiles.</Empty>
      ) : error ? (
        <ErrorMessage message={error.message} onRetry={reload} />
      ) : !result ? (
        <Loading what="stock risks" />
      ) : result.data.length === 0 ? (
        <Empty>No product matches these filters.</Empty>
      ) : (
        <section className="card" aria-label="Stock-out risks">
          {result.dataset && <p className="label">{result.dataset}</p>}
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th scope="col">SKU</th>
                  <th scope="col">Warehouse</th>
                  <th scope="col">Status</th>
                  <th scope="col">On hand</th>
                  <th scope="col">On order</th>
                  <th scope="col">Demand / day</th>
                  <th scope="col">Reorder point</th>
                  <th scope="col">Target</th>
                  <th scope="col">Short by</th>
                  <th scope="col">Days of cover</th>
                </tr>
              </thead>
              <tbody>
                {result.data.map((r) => (
                  <tr key={`${r.product_id}-${r.warehouse_id}`}>
                    <td>{r.sku}</td>
                    <td>{r.warehouse_code}</td>
                    <td>
                      <Badge value={r.status} />
                    </td>
                    <td>{r.on_hand}</td>
                    <td>{r.on_order}</td>
                    <td>{numbers.format(r.daily_mean)}</td>
                    <td>{numbers.format(r.reorder_point)}</td>
                    <td>{r.target_level}</td>
                    <td>{r.shortfall}</td>
                    <td>{r.days_of_cover === null ? "no demand" : numbers.format(r.days_of_cover)}</td>
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
