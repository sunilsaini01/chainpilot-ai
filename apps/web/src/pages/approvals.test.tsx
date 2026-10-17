import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { Approval } from "../api/types";
import { MANAGER, openPage, type Call } from "../testUtils";
import { age, describeOutcome } from "./RecommendationsPage";

const REC = {
  id: 11,
  kind: "reorder",
  status: "pending",
  product_id: 7,
  warehouse_id: 1,
  source_warehouse_id: null,
  supplier_id: 4,
  quantity: 48,
  reason: "ordered",
  service_level: "0.950",
  details: { item: { sku: "SYN-0007", warehouse_code: "SYN-WH1", position: 12, target_level: 60 } },
  created_at: "2026-10-17T08:00:00Z",
};

const APPROVED: Approval = {
  id: 3,
  recommendation_id: 11,
  decision: "approved",
  comment: null,
  decided_by_user_id: 5,
  decided_by_email: "manager@example.com",
  outcome: "executed",
  outcome_details: { po_number: "PO-REC-000011", expected_date: "2026-11-07" },
  purchase_order_id: 211,
  created_at: "2026-10-17T09:00:00Z",
};

const decisions = (calls: Call[]) => calls.filter((c) => c.method === "POST" && c.path.endsWith("/decision"));

describe("approval queue", () => {
  it("lets a manager approve after confirming, with an Idempotency-Key", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    const api = openPage(
      "/recommendations",
      {
        "/inventory/recommendations": [200, [REC]],
        "/approvals": [200, []],
        "POST /inventory/recommendations/11/decision": [201, APPROVED],
      },
      MANAGER,
    );

    await userEvent.click(await screen.findByRole("button", { name: /^Approve order 48 × SYN-0007/ }));

    expect(confirm).toHaveBeenCalledWith(
      "Approve: order 48 × SYN-0007 for SYN-WH1 from SYN-SUP04? A purchase order is placed now.",
    );
    const [call] = decisions(api.calls);
    expect(call.body).toEqual({ decision: "approve", comment: null });
    expect(call.headers.get("Idempotency-Key")).toMatch(/.{8,}/);
    expect(await screen.findByRole("status")).toHaveTextContent(
      "purchase order PO-REC-000011 placed, expected 2026-11-07",
    );
    // The history is asked again after the decision.
    expect(api.calls.filter((c) => c.path === "/approvals").length).toBe(2);
  });

  it("does nothing when the confirmation is cancelled", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(false);
    const api = openPage("/recommendations", { "/inventory/recommendations": [200, [REC]], "/approvals": [200, []] }, MANAGER);

    await userEvent.click(await screen.findByRole("button", { name: /^Approve/ }));

    expect(decisions(api.calls)).toEqual([]);
  });

  it("sends the same key again when the first answer was lost", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    let attempts = 0;
    const api = openPage(
      "/recommendations",
      {
        "/inventory/recommendations": [200, [REC]],
        "/approvals": [200, []],
        "POST /inventory/recommendations/11/decision": () =>
          ++attempts === 1 ? new TypeError("Failed to fetch") : [200, APPROVED],
      },
      MANAGER,
    );

    const approve = await screen.findByRole("button", { name: /^Approve/ });
    await userEvent.click(approve);
    expect(await screen.findByRole("alert")).toHaveTextContent("The API cannot be reached");
    await userEvent.click(approve);

    const [first, second] = decisions(api.calls);
    expect(second.headers.get("Idempotency-Key")).toBe(first.headers.get("Idempotency-Key"));
    expect(await screen.findByRole("status")).toHaveTextContent("PO-REC-000011");
  });

  it("asks for a reason to reject and sends it", async () => {
    const rejected = { ...APPROVED, decision: "rejected", outcome: null, outcome_details: {}, comment: "On hold" };
    const api = openPage(
      "/recommendations",
      {
        "/inventory/recommendations": [200, [REC]],
        "/approvals": [200, []],
        "POST /inventory/recommendations/11/decision": [201, rejected],
      },
      MANAGER,
    );

    await userEvent.click(await screen.findByRole("button", { name: /^Reject/ }));
    const reason = screen.getByLabelText(/^Reason for rejecting/);
    expect(reason).toBeRequired();
    await userEvent.type(reason, "On hold");
    await userEvent.click(screen.getByRole("button", { name: "Reject" }));

    expect(decisions(api.calls)[0].body).toEqual({ decision: "reject", comment: "On hold" });
    expect(await screen.findByRole("status")).toHaveTextContent("Rejected: On hold");
  });

  it("shows a failed execution as a problem", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const failed = { ...APPROVED, outcome: "failed", outcome_details: { error: "Insufficient stock: 3 on hand" } };
    openPage(
      "/recommendations",
      {
        "/inventory/recommendations": [200, [REC]],
        "/approvals": [200, []],
        "POST /inventory/recommendations/11/decision": [201, failed],
      },
      MANAGER,
    );

    await userEvent.click(await screen.findByRole("button", { name: /^Approve/ }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Approved, but it could not be carried out: Insufficient stock: 3 on hand",
    );
  });

  it("is read-only for analysts and lists recent decisions", async () => {
    openPage("/recommendations", { "/inventory/recommendations": [200, [REC]], "/approvals": [200, [APPROVED]] });

    await screen.findByRole("row", { name: /SYN-0007/ });
    expect(screen.queryByRole("button", { name: /^Approve/ })).not.toBeInTheDocument();
    expect(screen.getByText(/Only managers and administrators can approve or reject/)).toBeInTheDocument();
    const history = screen.getByRole("region", { name: "Recent decisions" });
    expect(await within(history).findByText("manager@example.com")).toBeInTheDocument();
  });

  it("can show decided recommendations, without decision buttons", async () => {
    const api = openPage(
      "/recommendations",
      { "/inventory/recommendations": [200, [{ ...REC, status: "executed" }]], "/approvals": [200, []] },
      MANAGER,
    );

    await userEvent.selectOptions(await screen.findByLabelText("Show"), "executed");

    await screen.findByRole("region", { name: "executed recommendations" });
    expect(api.calls.filter((c) => c.path === "/inventory/recommendations").at(-1)?.params.get("status")).toBe(
      "executed",
    );
    expect(screen.queryByRole("button", { name: /^Approve/ })).not.toBeInTheDocument();
  });
});

describe("approval queue helpers", () => {
  it("says how old a proposal is", () => {
    const now = new Date("2026-10-20T12:00:00Z");
    expect(age("2026-10-20T08:00:00Z", now)).toBe("today");
    expect(age("2026-10-19T08:00:00Z", now)).toBe("1 day ago");
    expect(age("2026-10-15T08:00:00Z", now)).toBe("5 days ago");
  });

  it("describes a transfer's outcome", () => {
    expect(
      describeOutcome({ ...APPROVED, purchase_order_id: null, outcome_details: { reference: "REC-12" } }),
    ).toBe("Approved: stock moved (REC-12)");
  });
});
