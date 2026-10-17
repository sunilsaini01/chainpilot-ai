import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { MANAGER, openPage } from "../testUtils";
import { describeStep } from "./CopilotPage";

const RUN = {
  id: 12,
  question: "Which supplier is unreliable?",
  status: "completed",
  answer: {
    answer: "SYN-SUP04 is at risk (30.8% on time).",
    citations: ["supplier:SYN-SUP04"],
    limitations: "Simulated data.",
    grounded: true,
    unsupported_citations: [],
  },
  trace: [
    { node: "supervisor", next: "supplier", reason: "supplier question" },
    { node: "supplier", tool: "supplier_performance", arguments: {}, ok: true, rows: 6, citations: [], message: null },
    { node: "supplier", note: "SUP04 is at risk." },
    { node: "verify", valid: ["supplier:SYN-SUP04"], unsupported: [], retry: false },
  ],
  model: "groq:qwen/qwen3.8-27b",
  model_calls: 5,
  tool_calls: 1,
  prompt_tokens: 6000,
  completion_tokens: 332,
  duration_ms: 4000,
  error: null,
  created_at: "2026-10-17T09:00:00Z",
};

describe("copilot", () => {
  it("asks, then shows the verified answer, its citations and its steps", async () => {
    const api = openPage("/copilot", { "GET /agents/runs": [200, []], "POST /agents/investigate": [201, RUN] });

    await userEvent.type(await screen.findByLabelText("Your question"), "Which supplier is unreliable?");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));

    const answer = await screen.findByRole("region", { name: "Which supplier is unreliable?" });
    expect(within(answer).getByText(/Verified: every citation was checked/)).toBeInTheDocument();
    expect(within(answer).getByText("supplier:SYN-SUP04")).toBeInTheDocument();
    expect(within(answer).getByText(/supplier specialist used supplier_performance\(\{\}\): 6 rows/)).toBeInTheDocument();
    expect(api.calls.find((c) => c.method === "POST")?.body).toEqual({ question: "Which supplier is unreliable?" });
  });

  it("marks an answer without checked citations as not verified", async () => {
    const unverified = {
      ...RUN,
      answer: { ...RUN.answer, citations: [], grounded: false, unsupported_citations: ["supplier:SYN-SUP99"] },
    };
    openPage("/copilot", { "GET /agents/runs": [200, []], "POST /agents/investigate": [201, unverified] });

    await userEvent.type(await screen.findByLabelText("Your question"), "x");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));

    expect(await screen.findByText(/Not verified/)).toBeInTheDocument();
    expect(screen.getByText(/Removed because no tool returned them: supplier:SYN-SUP99/)).toBeInTheDocument();
  });

  it.each([
    [503, { detail: "not configured" }, "not set up on this server"],
    [429, { detail: "At most 20 investigations per hour" }, "At most 20 investigations per hour. Try again later."],
  ])("explains HTTP %i", async (status, body, text) => {
    openPage("/copilot", { "GET /agents/runs": [200, []], "POST /agents/investigate": [status, body] });

    await userEvent.type(await screen.findByLabelText("Your question"), "x");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(text);
  });

  it("lists earlier questions", async () => {
    openPage("/copilot", { "GET /agents/runs": [200, [RUN]] });
    // The summary line: question, status and time (the full answer is folded inside).
    expect(await screen.findByText("(completed, 2026-10-17 09:00)")).toBeInTheDocument();
  });

  it("describes each kind of step", () => {
    expect(describeStep({ node: "supervisor", next: "finish", reason: "call limit" })).toBe(
      "Supervisor chose: finish (call limit)",
    );
    expect(describeStep({ node: "verify", unsupported: ["x:1"], retry: true })).toBe(
      "Checked the citations: removed x:1 and asked for a corrected answer",
    );
    expect(describeStep({ node: "inventory", tool: "stock_risks", arguments: {}, ok: false, message: "Unknown warehouse" })).toBe(
      "inventory specialist used stock_risks({}): refused: Unknown warehouse",
    );
  });
});

describe("audit log", () => {
  const EVENTS = [
    { id: 2, actor_user_id: 5, actor_email: "manager@example.com", action: "purchase_order.received", entity_type: "purchase_order", entity_id: "210", details: { po_number: "SYN-PO-000210", units: 142 }, created_at: "2026-10-17T09:30:00Z" },
    { id: 1, actor_user_id: null, actor_email: null, action: "seed.loaded", entity_type: "seed", entity_id: null, details: { seed: 42 }, created_at: "2026-10-17T08:00:00Z" },
  ];

  it("shows who did what, with system actions marked, for managers", async () => {
    const api = openPage("/audit", { "/audit-events": [200, EVENTS] }, MANAGER);

    const received = await screen.findByRole("row", { name: /purchase_order.received/ });
    expect(received).toHaveTextContent("manager@example.com");
    expect(received).toHaveTextContent("po number: SYN-PO-000210; units: 142");
    expect(screen.getByRole("row", { name: /seed.loaded/ })).toHaveTextContent("system");

    await userEvent.selectOptions(screen.getByLabelText("Kind of record"), "purchase_order");
    expect(api.calls.filter((c) => c.path === "/audit-events").at(-1)?.params.get("entity_type")).toBe("purchase_order");
  });

  it("is not offered to analysts", async () => {
    openPage("/audit", {});
    expect(await screen.findByRole("alert")).toHaveTextContent("This page is for managers and above.");
    expect(screen.queryByRole("link", { name: "Audit log" })).not.toBeInTheDocument();
  });
});
