import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { fakeApi, KPIS, renderWithApp } from "../testUtils";
import { OverviewPage } from "./OverviewPage";

describe("overview", () => {
  it("shows the numbers from the API", async () => {
    vi.stubGlobal("fetch", fakeApi({ "/dashboard/kpis": [200, KPIS] }));
    renderWithApp(<OverviewPage />);

    expect(screen.getByRole("status")).toHaveTextContent("Loading the overview");
    const risk = await screen.findByRole("region", { name: "Stock-out risk" });
    expect(within(risk).getByText("Out of stock").nextSibling).toHaveTextContent("146");
    expect(screen.getByText("Units on hand").nextSibling).toHaveTextContent("160,712");
    expect(screen.getByText("Stock value (at cost)").nextSibling).toHaveTextContent("1,234.50");
    expect(screen.getByText("Overdue purchase orders").nextSibling).toHaveTextContent("2");
    expect(screen.getByText("SIMULATED stock")).toBeInTheDocument();
  });

  it("says why risks are missing when no forecasts are imported", async () => {
    const note = "No forecast run imported yet (see import-forecasts)";
    vi.stubGlobal("fetch", fakeApi({ "/dashboard/kpis": [200, { ...KPIS, stock_status: null, stock_status_note: note }] }));
    renderWithApp(<OverviewPage />);

    expect(await screen.findByText(`Not available: ${note}`)).toBeInTheDocument();
  });

  it("shows an error with a working retry", async () => {
    let calls = 0;
    vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
      calls += 1;
      return calls === 1
        ? new Response(JSON.stringify({ detail: "Database is not reachable" }), { status: 503 })
        : fakeApi({ "/dashboard/kpis": [200, KPIS] })(input);
    });
    renderWithApp(<OverviewPage />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Database is not reachable");
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("heading", { name: "Overview" })).toBeInTheDocument();
  });
});
