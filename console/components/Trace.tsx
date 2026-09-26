"use client";

import type { AgentRun, TraceStep } from "@/lib/api";
import { CHANNEL_LABEL, OUTCOME_LABEL, clock } from "@/lib/format";

const cap = (t: string) => t.charAt(0).toUpperCase() + t.slice(1);

type Row = { key: string; kind: string; bad?: boolean; title: string; body: React.ReactNode; raw?: unknown };

const TOOL_LABEL: Record<string, string> = {
  create_payment_request: "Created payment request",
  get_payment_status: "Read payment status",
  get_last_payment: "Looked up last payment",
  get_today_summary: "Totalled today's payments",
  find_payments: "Searched the ledger",
  open_exception_case: "Opened dispute case",
  get_device_status: "Checked terminal",
  get_merchant_health: "Scored merchant health",
  draft_intervention: "Drafted intervention for approval",
};

function describeArgs(args: Record<string, unknown> | undefined): string {
  if (!args) return "";
  const parts: string[] = [];
  if (typeof args.amount_rupees === "number") parts.push(`PKR ${args.amount_rupees.toLocaleString("en-PK")}`);
  if (typeof args.window_min === "number") parts.push(`last ${args.window_min} min`);
  if (typeof args.case_type === "string") parts.push(args.case_type.replace(/_/g, " ").toLowerCase());
  if (typeof args.reason_code === "string") parts.push(args.reason_code.replace(/_/g, " ").toLowerCase());
  if (typeof args.txn_id === "string") parts.push(args.txn_id);
  return parts.join(", ");
}

function resultLine(tool: string, result: Record<string, unknown> | undefined): string {
  if (!result) return "";
  if (tool === "find_payments") {
    const m = (result.matches as { status: string }[]) ?? [];
    return m.length ? `${m.length} match${m.length > 1 ? "es" : ""}: ${m.map((x) => x.status.toLowerCase()).join(", ")}` : "no matching payment";
  }
  if (tool === "get_payment_status") return `status ${String(result.status).toLowerCase()}`;
  if (tool === "get_today_summary") return `${result.count} payments, PKR ${Number(result.total_rupees).toLocaleString("en-PK")}`;
  if (tool === "create_payment_request") return `${result.reference}, expires in 5 min`;
  if (tool === "open_exception_case") return String(result.case_id);
  if (tool === "draft_intervention") return `${CHANNEL_LABEL[result.channel as keyof typeof CHANNEL_LABEL] ?? result.channel}, waiting for approval`;
  return "";
}

function toRows(steps: TraceStep[]): Row[] {
  const rows: Row[] = [];
  // Activation sweeps score every merchant; show that as one line right after the plan.
  const healthChecks = steps.filter((s) => s.step === "act" && s.tool === "get_merchant_health" && s.ok).length;
  let healthShown = healthChecks === 0;
  const flushHealth = (i: number) => {
    if (healthShown) return;
    rows.push({ key: `h${i}`, kind: "act", title: "act", body: <>Scored health of <b>{healthChecks}</b> merchants from their payment ledger signals</> });
    healthShown = true;
  };

  steps.forEach((s, i) => {
    if (s.step === "act" && s.tool === "get_merchant_health" && s.ok) return;
    if (s.step !== "observe" && s.step !== "plan") flushHealth(i);
    const k = `${i}`;
    switch (s.step) {
      case "observe":
        rows.push({ key: k, kind: "observe", title: "observe", body: s.text
          ? <>Merchant said <q>{String(s.text)}</q></>
          : s.hotkey ? <>Keypad shortcut <code>{String(s.hotkey)}</code></>
          : s.trigger ? <>{String(s.trigger)} asked the agent to review {String(s.merchants)} merchants</>
          : <>Scheduled run</> });
        break;
      case "understand":
        rows.push({ key: k, kind: "understand", title: "understand", raw: s, body: <>
          Intent <b>{String(s.intent).replace(/_/g, " ").toLowerCase()}</b>
          {typeof s.amount === "number" && <> for <b>PKR {s.amount.toLocaleString("en-PK")}</b></>}
          <span className="muted"> by {s.source === "rules" ? "deterministic rules" : s.source === "llm" ? "language model (needs confirmation)" : "direct keypad input"}</span>
          {Array.isArray(s.notes) && s.notes.length > 0 && <div className="muted small">{(s.notes as string[]).join("; ")}</div>}
        </> });
        break;
      case "plan":
        rows.push({ key: k, kind: "plan", title: "plan", body: <>
          {cap(String(s.decision).replace(/_/g, " "))}
          {Array.isArray(s.tools) && <div className="muted small">Tools: {(s.tools as string[]).map((t) => <code key={t} style={{ marginRight: 4 }}>{t}</code>)}</div>}
          {typeof s.reason === "string" && <div className="muted small">{s.reason}</div>}
        </> });
        break;
      case "act": {
        const tool = String(s.tool);
        rows.push({ key: k, kind: "act", bad: !s.ok, title: "act", raw: s.result ?? s.error, body: <>
          {TOOL_LABEL[tool] ?? tool} <span className="muted">{describeArgs(s.args as Record<string, unknown>)}</span>
          <div className="small">{s.ok ? resultLine(tool, s.result as Record<string, unknown>) : <span style={{ color: "var(--brick)" }}>Blocked: {String(s.error)}</span>}</div>
        </> });
        break;
      }
      case "verify":
        rows.push({ key: k, kind: "verify", bad: s.ok === false, title: "verify", raw: s, body: s.ok === false
          ? <>State did not match. Agent stopped instead of claiming success.</>
          : <>Re-read the ledger before answering{typeof s.status === "string" ? `: status ${s.status.toLowerCase()}` : ""}{typeof s.matches === "number" ? `: ${s.matches} matching payments` : ""}</> });
        break;
      case "human_confirmed":
        rows.push({ key: k, kind: "human_confirmed", title: "confirmed", body: <>Merchant approved the proposed amount on the keypad</> });
        break;
      case "error":
        rows.push({ key: k, kind: "act", bad: true, title: "stopped", body: <>Validation rejected the request: <code>{String(s.code)}</code></> });
        break;
      case "respond":
        rows.push({ key: k, kind: "respond", title: "respond", body: s.text
          ? <>{String(s.text)}</>
          : <>Examined {String(s.examined)} merchants, drafted {String(s.drafted)} interventions</> });
        break;
      default:
        rows.push({ key: k, kind: s.step, title: s.step, body: <code>{JSON.stringify(s)}</code> });
    }
  });
  flushHealth(steps.length);
  return rows;
}

export default function Trace({ run }: { run: AgentRun }) {
  return (
    <div>
      <div className="runhead">
        <div>
          <div className="said">{OUTCOME_LABEL[run.outcome ?? ""] ?? run.outcome}</div>
          <div className="muted small">
            {run.agent === "merchant" ? "Payment exception agent" : "Merchant activation agent"}, {clock(run.created_at)}, run {run.id}
          </div>
        </div>
      </div>
      <ol className="ledger">
        {toRows(run.steps).map((r) => (
          <li key={r.key} className={`${r.kind}${r.bad ? " bad" : ""}`}>
            <span className="n" aria-hidden="true" />
            <span className="stage">{r.title}</span>
            <div className="what">
              {r.body}
              {r.raw !== undefined && (
                <details><summary>Show data</summary><pre>{JSON.stringify(r.raw, null, 2)}</pre></details>
              )}
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}
