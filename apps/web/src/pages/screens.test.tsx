// The P6-T2 screens against a fake API: what they show and what they ask for.

import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { MANAGER, openPage } from "../testUtils";

const RISK = {
  product_id: 7,
  sku: "SYN-0007",
  warehouse_id: 1,
  warehouse_code: "SYN-WH1",
  status: "out_of_stock",
  on_hand: 0,
  on_order: 12,
  position: 12,
  daily_mean: 3.68,
  reorder_point: 26.52,
  target_level: 60,
  shortfall: 48,
  days_of_cover: 0,
  lead_time_days: 7,
  demand_profile: "HOUSEHOLD_1_294 at CA_1",
};

describe("stock risks", () => {
  it("shows the risks and sends the filters", async () => {
    const api = openPage("/risks", { "/inventory/risks": [200, [RISK]] });

    const table = await screen.findByRole("region", { name: "Stock-out risks" });
    const row = within(table).getByRole("row", { name: /SYN-0007/ });
    expect(row).toHaveTextContent("out of stock");
    expect(row).toHaveTextContent("26.5");

    await userEvent.selectOptions(screen.getByLabelText("Status"), "at_risk");
    const last = api.calls.filter((c) => c.path === "/inventory/risks").at(-1);
    expect(last?.params.get("status")).toBe("at_risk");
    expect(last?.params.get("offset")).toBe("0");
  });

  it("explains an empty list when no forecasts are imported", async () => {
    openPage("/risks", {
      "/inventory/risks": [409, { detail: "No forecast run imported yet (see import-forecasts)" }],
    });
    expect(await screen.findByText(/No risks yet: No forecast run imported yet/)).toBeInTheDocument();
  });
});

describe("recommendations", () => {
  const REC = {
    id: 11,
    kind: "reorder",
    status: "pending",
    product_id: 7,
    warehouse_id: 1,
    source_warehouse_id: null,
    supplier_id: 4,
    quantity: 48,
    reason: "raised_to_moq",
    service_level: "0.950",
    details: { item: { sku: "SYN-0007", warehouse_code: "SYN-WH1", position: 12, target_level: 60 } },
    created_at: "2026-10-17T08:00:00Z",
  };

  it("lists proposals with their reasons, without the button for analysts", async () => {
    openPage("/recommendations", { "/inventory/recommendations": [200, [REC]] });

    const row = await screen.findByRole("row", { name: /SYN-0007/ });
    expect(row).toHaveTextContent("supplier SYN-SUP04");
    expect(row).toHaveTextContent("raised to the supplier's minimum order");
    expect(row).toHaveTextContent("12 → 60");
    expect(screen.queryByRole("button", { name: "Make new recommendations" })).not.toBeInTheDocument();
  });

  it("lets a manager make new recommendations", async () => {
    const api = openPage(
      "/recommendations",
      { "GET /inventory/recommendations": [200, []], "POST /inventory/recommendations": [201, [REC, REC]] },
      MANAGER,
    );

    await userEvent.click(await screen.findByRole("button", { name: "Make new recommendations" }));

    expect(await screen.findByRole("status")).toHaveTextContent("Made 2 new proposals");
    expect(api.calls.find((c) => c.method === "POST")?.body).toEqual({ service_level: 0.95 });
  });
});

describe("suppliers and orders", () => {
  const ORDER = {
    id: 3,
    po_number: "SYN-PO-000169",
    supplier_id: 4,
    warehouse_id: 1,
    status: "open",
    ordered_date: "2020-01-01",
    expected_date: "2020-01-22",
    received_date: null,
    lines: [{ product_id: 7, quantity: 239, unit_cost: "5.00" }],
  };
  const RATING = {
    supplier_id: 4,
    code: "SYN-SUP04",
    name: "Far-East",
    rating: "at_risk",
    on_time_rate: 0.3077,
    received_orders: 26,
    on_time_orders: 8,
    average_days_late: 4.38,
    open_orders: 2,
    overdue_orders: ["SYN-PO-000169"],
  };

  it("shows ratings and marks overdue orders", async () => {
    openPage("/suppliers", { "/suppliers/risks": [200, [RATING]], "/purchase-orders": [200, [ORDER]] });

    const rating = await screen.findByRole("row", { name: /SYN-SUP04 Far-East/ });
    expect(rating).toHaveTextContent("at risk");
    expect(rating).toHaveTextContent("30.8%");
    const order = await screen.findByRole("row", { name: /SYN-PO-000169 SYN-SUP04/ });
    expect(order).toHaveTextContent("overdue");
    expect(order).toHaveTextContent("1 / 239");
  });

  it("lets a manager receive an order and shows a refusal", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    openPage(
      "/suppliers",
      {
        "/suppliers/risks": [200, [RATING]],
        "/purchase-orders": [200, [ORDER]],
        "POST /purchase-orders/3/receive": [409, { detail: "Warehouse capacity exceeded: 59990 of 60000 units used" }],
      },
      MANAGER,
    );

    await userEvent.click(await screen.findByRole("button", { name: /Receive/ }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Warehouse capacity exceeded");
  });
});

describe("forecasts", () => {
  const ROWS = [1, 2].map((step) => ({
    series_id: "FOODS_3_090_CA_1_validation",
    store_id: "CA_1",
    item_id: "FOODS_3_090",
    forecast_date: `2016-04-2${4 + step}`,
    step,
    forecast: 40 + step,
    lower: 35,
    upper: 48,
  }));

  it("shows one item at one store, labelled as M5 data", async () => {
    const api = openPage("/forecasts", { "/forecasts": [200, ROWS] });

    expect(await screen.findByRole("row", { name: /2016-04-25 41 35 – 48/ })).toBeInTheDocument();
    expect(screen.getByText(/Public M5 \(Walmart\) data/)).toBeInTheDocument();
    const call = api.calls.find((c) => c.path === "/forecasts");
    expect([call?.params.get("store_id"), call?.params.get("item_id")]).toEqual(["CA_1", "FOODS_3_090"]);
  });

  it("says when an item has no forecast", async () => {
    openPage("/forecasts", { "/forecasts": [200, []] });
    await userEvent.clear(await screen.findByLabelText("Item"));
    await userEvent.type(screen.getByLabelText("Item"), "foods_9_999");
    await userEvent.click(screen.getByRole("button", { name: "Show" }));
    expect(await screen.findByText(/No forecast for FOODS_9_999 at CA_1/)).toBeInTheDocument();
  });
});

describe("delivery risk", () => {
  const RUN = {
    id: 1,
    name: "olist",
    dataset: "Olist",
    model: "logistic",
    period_start: "2018-04-02",
    period_end: "2018-08-31",
    row_count: 32422,
  };
  const ALERT = {
    order_id: "b4892e6954a2c805cd6512033cc048ef",
    dispatch_date: "2018-08-31",
    probability: 0.7013,
    day_percentile: 1,
    tier: "high",
    alert: true,
    reasons: [{ feature: "handling_days", value: 15.6, effect: 1.6 }],
  };

  it("starts on the last scored day and shows its alerts", async () => {
    const api = openPage("/delivery-risk", {
      "/delivery-risk/runs": [200, [RUN]],
      "/delivery-risk/alerts": [200, [ALERT]],
    });

    const row = await screen.findByRole("row", { name: /b4892e6954a2/ });
    expect(row).toHaveTextContent("high");
    expect(row).toHaveTextContent("70.1%");
    expect(row).toHaveTextContent("handling days");
    expect(api.calls.find((c) => c.path === "/delivery-risk/alerts")?.params.get("date")).toBe("2018-08-31");
    expect(screen.getByText(/Public Olist/)).toBeInTheDocument();
  });

  it("says when nothing is imported", async () => {
    openPage("/delivery-risk", { "/delivery-risk/runs": [200, []] });
    expect(await screen.findByText("No delivery-risk scores are imported yet.")).toBeInTheDocument();
  });
});
