import { FormEvent, useState } from "react";

type WorkflowReport = {
  goal: string;
  state: string;
  values: Record<string, unknown>;
  citations: string[];
  query_hashes: string[];
  confidence: number | null;
  trace_id: string;
  critique: {
    state: string;
    reason: string;
    confidence: number | null;
  } | null;
};

type WorkflowResponse = {
  trace_id: string;
  report: WorkflowReport;
};

const apiBase = import.meta.env.VITE_CONTROL_API_BASE_URL ?? "";

export default function App() {
  const [goal, setGoal] = useState("");
  const [report, setReport] = useState<WorkflowReport | null>(null);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function submitGoal(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setReport(null);
    setSubmitting(true);
    try {
      const response = await fetch(`${apiBase}/api/workflows`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ goal }),
      });
      const payload = (await response.json()) as
        | WorkflowResponse
        | { error?: string };
      if (!response.ok) {
        throw new Error("error" in payload ? payload.error : "Workflow failed.");
      }
      setReport((payload as WorkflowResponse).report);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Workflow failed.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="shell">
      <header className="hero">
        <p className="eyebrow">Governed data workspace</p>
        <h1>Ask a question. Get an evidence-backed answer.</h1>
        <p className="lede">
          Orqestra plans and executes read-only workflows through tenant policy,
          budgets, masking, and audit controls.
        </p>
      </header>

      <section className="card" aria-labelledby="goal-heading">
        <h2 id="goal-heading">What do you want to understand?</h2>
        <form onSubmit={submitGoal}>
          <label htmlFor="goal">Your goal</label>
          <textarea
            id="goal"
            value={goal}
            onChange={(event) => setGoal(event.target.value)}
            placeholder="Compare monthly revenue for the last six months"
            required
            rows={4}
          />
          <button type="submit" disabled={submitting || !goal.trim()}>
            {submitting ? "Running governed workflow…" : "Run workflow"}
          </button>
        </form>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
      </section>

      {report && (
        <section className="card report" aria-labelledby="report-heading">
          <div className="report-heading">
            <div>
              <p className="eyebrow">Evidence-backed report</p>
              <h2 id="report-heading">{report.goal}</h2>
            </div>
            <span className={`status status-${report.state}`}>
              {report.state}
            </span>
          </div>
          <dl className="metrics">
            {Object.entries(report.values).map(([key, value]) => (
              <div key={key}>
                <dt>{key}</dt>
                <dd>{String(value)}</dd>
              </div>
            ))}
            <div>
              <dt>Confidence</dt>
              <dd>
                {report.confidence === null
                  ? "Not available"
                  : `${Math.round(report.confidence * 100)}%`}
              </dd>
            </div>
          </dl>
          <h3>Evidence</h3>
          <ul>
            {report.citations.map((citation) => (
              <li key={citation}>{citation}</li>
            ))}
          </ul>
          <p className="trace">Trace: {report.trace_id}</p>
        </section>
      )}
    </main>
  );
}
