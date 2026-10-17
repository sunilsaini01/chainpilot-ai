// Ask the AI copilot. It reads the system's data through fixed read-only tools,
// answers with citations, and cannot approve, order or change anything.

import { useState, type FormEvent } from "react";

import { api, ApiError } from "../api/client";
import type { AgentRun } from "../api/types";
import { Empty, ErrorMessage, Loading } from "../components/States";
import { useApi } from "../hooks/useApi";

const MAX_CHARS = 500;
const EXAMPLES = [
  "Which suppliers are unreliable, and which of their purchase orders are overdue?",
  "Which products are out of stock at warehouse SYN-WH1, and what is recommended for them?",
  "Who is allowed to approve a purchase order?",
];

/** One step of the run's trace as a sentence a person can check. */
export function describeStep(step: Record<string, unknown>): string {
  const node = String(step.node ?? "");
  if (node === "supervisor") return `Supervisor chose: ${step.next} (${step.reason})`;
  if (node === "verify") {
    const removed = (step.unsupported as string[] | undefined) ?? [];
    return removed.length
      ? `Checked the citations: removed ${removed.join(", ")}${step.retry ? " and asked for a corrected answer" : ""}`
      : "Checked the citations: all found in the tool results";
  }
  if (node === "answer") return step.retry ? `Answer: ${step.retry}` : `Wrote answer (attempt ${step.attempt})`;
  if ("tool" in step) {
    const outcome = step.ok ? `${step.rows} rows` : `refused: ${step.message}`;
    return `${node} specialist used ${step.tool}(${JSON.stringify(step.arguments ?? {})}): ${outcome}`;
  }
  if ("note" in step) return `${node} specialist noted: ${step.note}`;
  return JSON.stringify(step);
}

function RunView({ run }: { run: AgentRun }) {
  const answer = run.answer;
  return (
    <section className="card" aria-labelledby={`run-${run.id}`}>
      <h2 id={`run-${run.id}`}>{run.question}</h2>
      {run.status === "failed" ? (
        <p className="state-error" role="alert">
          The copilot could not answer: {run.error}
        </p>
      ) : !answer ? (
        <p className="state-empty">No answer: the run stopped at its limit.</p>
      ) : (
        <>
          <p className={answer.grounded ? "notice" : "state-error"}>
            {answer.grounded
              ? "Verified: every citation was checked against this run's tool results."
              : "Not verified: no checked citation supports this answer. Treat it with care."}
          </p>
          <p className="answer">{answer.answer}</p>
          <h3>Citations</h3>
          {answer.citations.length ? (
            <ul className="citations">
              {answer.citations.map((c) => (
                <li key={c} className="mono">
                  {c}
                </li>
              ))}
            </ul>
          ) : (
            <p className="state-empty">None.</p>
          )}
          {!!answer.unsupported_citations?.length && (
            <p className="label">Removed because no tool returned them: {answer.unsupported_citations.join(", ")}</p>
          )}
          {answer.limitations && <p className="label">Limitations: {answer.limitations}</p>}
        </>
      )}
      <details>
        <summary>
          How it was answered ({run.model_calls} model calls, {run.tool_calls} tool calls,{" "}
          {run.prompt_tokens + run.completion_tokens} tokens, {(run.duration_ms / 1000).toFixed(1)} s, {run.model})
        </summary>
        <ol className="steps">
          {run.trace.map((step, index) => (
            <li key={index}>{describeStep(step)}</li>
          ))}
        </ol>
      </details>
    </section>
  );
}

export function CopilotPage() {
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [latest, setLatest] = useState<AgentRun | null>(null);
  const history = useApi(() => api.agentRuns({ limit: 10 }), latest ? `after-${latest.id}` : "first");

  async function ask(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setProblem(null);
    try {
      const { data } = await api.investigate(question.trim());
      setLatest(data);
    } catch (error) {
      if (error instanceof ApiError && error.status === 503) {
        setProblem("The copilot is not set up on this server (no model provider key). Ask an administrator.");
      } else if (error instanceof ApiError && error.status === 429) {
        setProblem(`${error.message}. Try again later.`);
      } else {
        setProblem(error instanceof Error ? error.message : "The question could not be sent.");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <h1>Ask the copilot</h1>
      <p className="label">
        The copilot reads stock, suppliers, orders, forecasts and policies through read-only tools and answers with
        citations. It cannot approve, order or change anything. Each question calls the AI model provider and may take
        a minute.
      </p>
      <form className="stack wide-form" onSubmit={ask}>
        <label htmlFor="question">Your question</label>
        <textarea
          id="question"
          rows={3}
          maxLength={MAX_CHARS}
          required
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
        />
        <span className="label">
          {question.length}/{MAX_CHARS} characters
        </span>
        <div className="filters">
          {EXAMPLES.map((example) => (
            <button key={example} type="button" className="secondary" onClick={() => setQuestion(example)}>
              {example}
            </button>
          ))}
        </div>
        <button type="submit" disabled={busy || !question.trim()}>
          {busy ? "Investigating… this can take a minute" : "Ask"}
        </button>
      </form>
      {busy && <Loading what="the answer" />}
      {problem && <ErrorMessage message={problem} />}
      {latest && <RunView run={latest} />}

      <h2>Earlier questions</h2>
      {history.error ? (
        <ErrorMessage message={history.error.message} onRetry={history.reload} />
      ) : !history.result ? (
        <Loading what="earlier questions" />
      ) : history.result.data.filter((run) => run.id !== latest?.id).length === 0 ? (
        <Empty>No earlier questions.</Empty>
      ) : (
        history.result.data
          .filter((run) => run.id !== latest?.id)
          .map((run) => (
            <details key={run.id} className="card">
              <summary>
                {run.question} <span className="label">({run.status}, {run.created_at.slice(0, 16).replace("T", " ")})</span>
              </summary>
              <RunView run={run} />
            </details>
          ))
      )}
    </>
  );
}
